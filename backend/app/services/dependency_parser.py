from __future__ import annotations

import json
import re
import tomllib
from dataclasses import dataclass
from typing import Any


@dataclass
class DependencyChange:
    package: str
    old_version: str
    new_version: str
    ecosystem: str
    manifest: str = ""


def _clean_version(spec: str) -> str | None:
    value = str(spec).strip()
    value = re.sub(r"^[=~^><!* ]+", "", value)
    match = re.search(r"(\d+(?:\.\d+){0,3}(?:[-+][A-Za-z0-9.-]+)?)", value)
    return match.group(1) if match else None


def parse_requirements(text: str) -> dict[str, str]:
    result: dict[str, str] = {}
    for raw in text.splitlines():
        line = raw.split("#", 1)[0].strip()
        if not line or line.startswith(("-", "git+", "http:", "https:")):
            continue
        match = re.match(r"^([A-Za-z0-9_.-]+)\s*([=!~<>]{1,2})\s*([A-Za-z0-9_.+!-]+)", line)
        if match:
            version = _clean_version(match.group(3))
            if version:
                result[match.group(1).lower()] = version
    return result


def parse_pyproject(text: str) -> dict[str, str]:
    data = tomllib.loads(text)
    candidates: list[str] = []
    project = data.get("project") or {}
    candidates.extend(project.get("dependencies") or [])
    optional = project.get("optional-dependencies") or {}
    for values in optional.values():
        candidates.extend(values or [])
    poetry = ((data.get("tool") or {}).get("poetry") or {}).get("dependencies") or {}
    for name, spec in poetry.items():
        if name.lower() == "python":
            continue
        candidates.append(f"{name} {spec}" if isinstance(spec, str) else f"{name} == {((spec or {}).get('version') or '')}")
    return _parse_pep508(candidates)


def _parse_pep508(values: list[str]) -> dict[str, str]:
    result: dict[str, str] = {}
    for item in values:
        match = re.match(r"^([A-Za-z0-9_.-]+)(?:\[[^]]+\])?\s*(?:[<>=!~^]+)\s*([0-9][A-Za-z0-9_.+!-]*)", item.strip())
        if match:
            result[match.group(1).lower()] = _clean_version(match.group(2)) or match.group(2)
    return result


def parse_poetry_lock(text: str) -> dict[str, str]:
    result: dict[str, str] = {}
    current: dict[str, str] = {}
    in_package = False
    for raw in text.splitlines():
        line = raw.strip()
        if line == "[[package]]":
            if current.get("name") and current.get("version"):
                result[current["name"].lower()] = current["version"]
            current = {}
            in_package = True
        elif in_package:
            m = re.match(r'name\s*=\s*"([^"]+)"', line)
            if m:
                current["name"] = m.group(1)
            m = re.match(r'version\s*=\s*"([^"]+)"', line)
            if m:
                current["version"] = m.group(1)
    if current.get("name") and current.get("version"):
        result[current["name"].lower()] = current["version"]
    return result


def parse_pipfile_lock(text: str) -> dict[str, str]:
    data = json.loads(text)
    result: dict[str, str] = {}
    for section in ("default", "develop"):
        for name, spec in (data.get(section) or {}).items():
            if isinstance(spec, dict):
                version = _clean_version(spec.get("version", ""))
                if version:
                    result[name.lower()] = version
    return result


def parse_package_json(text: str) -> dict[str, str]:
    data = json.loads(text)
    deps: dict[str, str] = {}
    for section in ("dependencies", "devDependencies", "optionalDependencies", "peerDependencies"):
        for name, value in (data.get(section) or {}).items():
            if isinstance(value, str):
                version = _clean_version(value)
                if version:
                    deps[name.lower()] = version
    return deps


def _package_lock_dependencies(data: dict[str, Any]) -> dict[str, str]:
    result: dict[str, str] = {}
    packages = data.get("packages") or {}
    for path, info in packages.items():
        if not path or not isinstance(info, dict):
            continue
        name = path.rsplit("node_modules/", 1)[-1]
        if "/" in name or not info.get("version"):
            continue
        result[name.lower()] = str(info["version"])
    if result:
        return result
    for name, info in (data.get("dependencies") or {}).items():
        if isinstance(info, dict) and info.get("version"):
            result[name.lower()] = str(info["version"])
    return result


def parse_package_lock(text: str) -> dict[str, str]:
    return _package_lock_dependencies(json.loads(text))


def parse_manifest(ecosystem: str, path: str, text: str) -> dict[str, str]:
    name = path.lower().split("/")[-1]
    if ecosystem == "python":
        if name == "pyproject.toml":
            return parse_pyproject(text)
        if name == "poetry.lock":
            return parse_poetry_lock(text)
        if name == "pipfile.lock":
            return parse_pipfile_lock(text)
        return parse_requirements(text)
    if name == "package-lock.json":
        return parse_package_lock(text)
    return parse_package_json(text)


def changed_dependencies(ecosystem: str, old_text: str, new_text: str, path: str = "") -> list[DependencyChange]:
    old = parse_manifest(ecosystem, path, old_text)
    new = parse_manifest(ecosystem, path, new_text)
    changes: list[DependencyChange] = []
    for package in sorted(set(old) | set(new)):
        if package not in old or package not in new or old[package] == new[package]:
            continue
        changes.append(
            DependencyChange(package=package, old_version=old[package], new_version=new[package], ecosystem=ecosystem, manifest=path)
        )
    return changes


def is_supported_dependency_manifest(path: str) -> str | None:
    lower = path.lower()
    if lower.endswith(("requirements.txt", "requirements-dev.txt", "pyproject.toml", "poetry.lock", "pipfile.lock")):
        return "python"
    if lower.endswith(("package.json", "package-lock.json")):
        return "node"
    return None
