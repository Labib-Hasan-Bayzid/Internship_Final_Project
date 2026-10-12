from __future__ import annotations

import hashlib
import json
import os
import shutil
import signal
import subprocess
import threading
import time
from pathlib import Path
from typing import Any
from urllib.parse import quote
from urllib.request import Request, urlopen

import psutil

WORK = Path("/work")


def snapshot_files(root: Path) -> dict[str, str]:
    if not root.exists():
        return {}
    result: dict[str, str] = {}
    for p in root.rglob("*"):
        if p.is_file():
            try:
                result[str(p.relative_to(root))] = hashlib.sha256(p.read_bytes()).hexdigest()
            except OSError:
                pass
    return result


def snapshot_network() -> set[str]:
    out: set[str] = set()
    try:
        for conn in psutil.net_connections(kind="inet"):
            if not conn.raddr:
                continue
            try:
                out.add(f"{conn.raddr.ip}:{conn.raddr.port}")
            except Exception:
                continue
    except (psutil.Error, OSError):
        pass
    return out


def process_tree(root_pid: int) -> set[int]:
    pids = {root_pid}
    try:
        root = psutil.Process(root_pid)
        pids.update(child.pid for child in root.children(recursive=True))
    except (psutil.Error, OSError):
        pass
    return pids


def command_for(pid: int) -> str:
    try:
        return " ".join(psutil.Process(pid).cmdline())[:500]
    except (psutil.Error, OSError):
        return ""


def run(command: list[str], env: dict[str, str], cwd: Path, timeout: int = 300) -> dict[str, Any]:
    before_files = snapshot_files(cwd / "site")
    before_network = snapshot_network()
    started = time.perf_counter()
    proc = subprocess.Popen(
        command,
        cwd=cwd,
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        start_new_session=True,
    )
    seen_pids: set[int] = {proc.pid}
    observed_process_commands: set[str] = set()
    observed_network: set[str] = set(before_network)
    stop = threading.Event()

    def monitor() -> None:
        while not stop.is_set():
            pids = process_tree(proc.pid)
            seen_pids.update(pids)
            for pid in pids:
                cmd = command_for(pid)
                if cmd and pid != proc.pid:
                    observed_process_commands.add(cmd)
            observed_network.update(snapshot_network())
            time.sleep(0.08)
        observed_network.update(snapshot_network())
        for pid in list(seen_pids):
            cmd = command_for(pid)
            if cmd and pid != proc.pid:
                observed_process_commands.add(cmd)

    thread = threading.Thread(target=monitor, daemon=True)
    thread.start()
    timed_out = False
    try:
        proc.wait(timeout=timeout)
    except subprocess.TimeoutExpired:
        timed_out = True
        try:
            os.killpg(proc.pid, signal.SIGKILL)
        except Exception:
            try:
                proc.kill()
            except Exception:
                pass
        try:
            proc.wait(timeout=10)
        except Exception:
            pass
    finally:
        stop.set()
        thread.join(timeout=2)

    output = proc.stdout.read() if proc.stdout else ""
    after_files = snapshot_files(cwd / "site")
    after_network = snapshot_network()
    observed_network.update(after_network)
    added = sorted(set(after_files) - set(before_files))
    removed = sorted(set(before_files) - set(after_files))
    modified = sorted(k for k in set(before_files) & set(after_files) if before_files[k] != after_files[k])
    return {
        "exit_code": proc.returncode,
        "timed_out": timed_out,
        "duration_ms": round((time.perf_counter() - started) * 1000),
        "files_changed": sorted(set(added + removed + modified))[:500],
        "files_added": added[:500],
        "files_removed": removed[:500],
        "files_modified": modified[:500],
        "process_commands": sorted(observed_process_commands)[:100],
        "network_endpoints": sorted(observed_network - before_network)[:200],
        "stdout_tail": output[-6000:],
    }


def fresh_dir(name: str) -> Path:
    target = WORK / name
    shutil.rmtree(target, ignore_errors=True)
    target.mkdir(parents=True, exist_ok=True)
    return target


def registry_metadata(package: str, version: str) -> dict[str, Any]:
    url = f"https://pypi.org/pypi/{quote(package)}/{quote(version)}/json"
    try:
        req = Request(url, headers={"User-Agent": "dependency-change-verification/10.0"})
        with urlopen(req, timeout=15) as response:
            data = json.loads(response.read().decode("utf-8"))
        files = data.get("urls") or []
        yanked_files = [f for f in files if f.get("yanked")]
        return {
            "name": data.get("info", {}).get("name"),
            "version": version,
            "yanked": bool(yanked_files),
            "yanked_reasons": sorted({f.get("yanked_reason") for f in yanked_files if f.get("yanked_reason")}),
        }
    except Exception as exc:
        return {"lookup_error": type(exc).__name__}


def installed_versions(site: Path, env: dict[str, str]) -> dict[str, str]:
    try:
        command = [
            "python",
            "-c",
            "import json,sys,subprocess; print(json.dumps({i['name'].lower(): i['version'] for i in json.loads(subprocess.check_output([sys.executable,'-m','pip','list','--path',sys.argv[1],'--format','json'], text=True))}))",
            str(site),
        ]
        raw = subprocess.check_output(command, env=env, text=True, timeout=30)
        return json.loads(raw)
    except Exception:
        return {}


def install_and_smoke(package: str, version: str, smoke_import: str | None) -> dict[str, Any]:
    safe_version = version.replace("/", "_")
    work = fresh_dir(f"experiment-{safe_version}")
    site = work / "site"
    home = work / "home"
    cache = work / "pip-cache"
    for p in (site, home, cache):
        p.mkdir(parents=True, exist_ok=True)
    env = os.environ.copy()
    env.update({"HOME": str(home), "PIP_CACHE_DIR": str(cache), "PYTHONPATH": str(site)})

    report = work / "install-report.json"
    install = run(
        [
            "python",
            "-m",
            "pip",
            "install",
            "--no-input",
            "--disable-pip-version-check",
            "--report",
            str(report),
            "--target",
            str(site),
            f"{package}=={version}",
        ],
        env,
        work,
    )
    install["phase"] = "install"
    install["version"] = version
    install["registry"] = registry_metadata(package, version)
    install["dependency_versions"] = installed_versions(site, env) if install["exit_code"] == 0 else {}

    if smoke_import and install["exit_code"] == 0:
        expression = json.dumps(smoke_import)
        smoke = run(["python", "-c", f"import importlib; importlib.import_module({expression})"], env, work, timeout=60)
        smoke["phase"] = "smoke_import"
        smoke["import"] = smoke_import
        install["smoke_test"] = smoke
    return install


def main() -> None:
    package = os.environ["PACKAGE_NAME"]
    old_version = os.environ["OLD_VERSION"]
    new_version = os.environ["NEW_VERSION"]
    smoke_import = os.environ.get("SMOKE_IMPORT", "").strip() or package
    old = install_and_smoke(package, old_version, smoke_import)
    new = install_and_smoke(package, new_version, smoke_import)
    print(
        "VERIFICATION_RESULT:" + json.dumps(
            {
                "package_name": package,
                "ecosystem": "python",
                "old_version": old_version,
                "new_version": new_version,
                "old": old,
                "new": new,
                "verification_model": "install + registry metadata + dependency tree + runtime import smoke test + live process/network/filesystem observation",
            },
            separators=(",", ":"),
        )
    )


if __name__ == "__main__":
    main()
