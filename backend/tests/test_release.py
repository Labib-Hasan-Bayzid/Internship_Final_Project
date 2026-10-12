from pathlib import Path
import re

ROOT = Path(__file__).resolve().parents[2]


def test_release_version_is_single_source_of_truth():
    version = (ROOT / "VERSION").read_text().strip()
    cfg = (ROOT / "backend/app/config.py").read_text()
    assert re.search(rf'app_version:\s*str\s*=\s*"{re.escape(version)}"', cfg)
    assert (ROOT / "RELEASE_VERSION").read_text().strip() == version


def test_local_scripts_do_not_pin_an_old_release():
    version = (ROOT / "VERSION").read_text().strip()
    build = (ROOT / "scripts/build-local.ps1").read_text()
    start = (ROOT / "scripts/start-local.ps1").read_text()
    assert "$BaseVersion = (Get-Content .\\VERSION -Raw).Trim()" in build
    assert "$BaseVersion = (Get-Content (Join-Path $RepoRoot \"VERSION\") -Raw).Trim()" in start
    assert "-local" not in (build.split("$Release", 1)[0] if "$Release" in build else "")
    local = (ROOT / "infra/k8s/local/kustomization.yaml").read_text()
    assert re.search(r"newTag:\s*\d+\.\d+\.\d+-local", local)
    assert "__DCV_RELEASE__" not in local and "__DCV_BASE_VERSION__" not in local
    start = (ROOT / "scripts/start-local.ps1").read_text()
    direct = (ROOT / "scripts/deploy-direct.ps1").read_text()
    assert "overlayVersionMatch" in start and 'Replace("$OverlayBaseVersion-local", $Release)' in start
    assert "overlayVersionMatch" in direct and 'Replace("$OverlayBaseVersion-local", $Release)' in direct
