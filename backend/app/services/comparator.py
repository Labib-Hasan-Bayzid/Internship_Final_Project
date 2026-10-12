from __future__ import annotations
from typing import Any


def _set(value: Any) -> set[str]:
    if not isinstance(value, list):
        return set()
    return {str(x) for x in value}


def _mapping(value: Any) -> dict[str, str]:
    if not isinstance(value, dict):
        return {}
    return {str(k): str(v) for k, v in value.items()}


def compare_behavior(old: dict, new: dict, policy, root_package: str | None = None) -> dict:
    old_files = _set(old.get("files_changed"))
    new_files = _set(new.get("files_changed"))
    old_processes = _set(old.get("process_commands"))
    new_processes = _set(new.get("process_commands"))
    old_network = _set(old.get("network_endpoints"))
    new_network = _set(new.get("network_endpoints"))
    old_deps = _mapping(old.get("dependency_versions"))
    new_deps = _mapping(new.get("dependency_versions"))

    smoke_old = old.get("smoke_test") or {}
    smoke_new = new.get("smoke_test") or {}
    registry_new = new.get("registry") or {}
    install_text = f"{new.get('stdout_tail', '')}\n{new.get('stderr_tail', '')}".lower()

    changed_deps = sorted(
        name for name in set(old_deps) | set(new_deps)
        if old_deps.get(name) != new_deps.get(name) and name.lower() != (root_package or "").lower()
    )

    old_smoke_ms = smoke_old.get("duration_ms")
    new_smoke_ms = smoke_new.get("duration_ms")
    smoke_regression_percent = None
    if isinstance(old_smoke_ms, (int, float)) and isinstance(new_smoke_ms, (int, float)) and old_smoke_ms > 0:
        smoke_regression_percent = round(((new_smoke_ms - old_smoke_ms) / old_smoke_ms) * 100, 2)

    deltas = {
        "network_endpoints_added": sorted(new_network - old_network),
        "network_endpoints_removed": sorted(old_network - new_network),
        "process_commands_added": sorted(new_processes - old_processes),
        "process_commands_removed": sorted(old_processes - new_processes),
        "files_added": sorted(new_files - old_files)[:100],
        "files_removed": sorted(old_files - new_files)[:100],
        "file_count_delta": len(new_files) - len(old_files),
        "network_count_delta": len(new_network) - len(old_network),
        "process_count_delta": len(new_processes) - len(old_processes),
        "dependency_version_changes": changed_deps,
        "dependency_version_change_count": len(changed_deps),
        "old_exit_code": old.get("exit_code"),
        "new_exit_code": new.get("exit_code"),
        "old_smoke_exit_code": smoke_old.get("exit_code"),
        "new_smoke_exit_code": smoke_new.get("exit_code"),
        "old_smoke_duration_ms": old_smoke_ms,
        "new_smoke_duration_ms": new_smoke_ms,
        "smoke_duration_ms_delta": (new_smoke_ms - old_smoke_ms) if isinstance(old_smoke_ms, (int, float)) and isinstance(new_smoke_ms, (int, float)) else None,
        "smoke_regression_percent": smoke_regression_percent,
    }

    score = 0
    reasons: list[str] = []
    hard_failure = False

    if deltas["new_exit_code"] not in (0, None):
        score += 8
        hard_failure = True
        reasons.append("new version installation failed")
    if deltas["new_smoke_exit_code"] not in (0, None):
        score += 8
        hard_failure = True
        reasons.append("new version smoke test failed")
    if deltas["network_count_delta"] > 0:
        if policy.review_network_additions:
            score += min(deltas["network_count_delta"] * 3, 12)
            reasons.append(f"{deltas['network_count_delta']} new network endpoint(s) observed")
        else:
            reasons.append(f"{deltas['network_count_delta']} new network endpoint(s) observed; network review policy is disabled")
    if deltas["process_count_delta"] > 0:
        if policy.review_process_additions:
            score += min(deltas["process_count_delta"] * 3, 12)
            reasons.append(f"{deltas['process_count_delta']} new process behavior(s) observed")
        else:
            reasons.append(f"{deltas['process_count_delta']} new process behavior(s) observed; process review policy is disabled")
    if abs(deltas["file_count_delta"]) > policy.max_file_delta:
        score += 4
        reasons.append(f"filesystem delta exceeded {policy.max_file_delta} files")
    if len(changed_deps) > 0:
        score += min(len(changed_deps) * 1, 4)
        reasons.append(f"{len(changed_deps)} transitive dependency version change(s) observed")

    regression = deltas["smoke_regression_percent"]
    min_ms = getattr(policy, "runtime_regression_min_ms", 100)
    review_pct = getattr(policy, "runtime_regression_review_percent", 50)
    block_pct = getattr(policy, "runtime_regression_block_percent", 150)
    abs_delta = deltas["smoke_duration_ms_delta"]
    if regression is not None and abs_delta is not None and abs_delta >= min_ms and regression >= review_pct:
        if regression >= block_pct:
            score += 8
            hard_failure = True
            reasons.append(f"smoke-test runtime regressed {regression:.1f}%")
        else:
            score += 4
            reasons.append(f"smoke-test runtime regressed {regression:.1f}%")

    new_yanked = bool(registry_new.get("yanked"))
    new_deprecated = bool(registry_new.get("deprecated"))
    warning = any(token in install_text for token in ("yanked version", "deprecated", "deprecat"))

    if registry_new.get("lookup_error"):
        score += 1
        reasons.append("package registry metadata was unavailable")
    if new_yanked:
        score = max(score, 5)
        reasons.append("new package release is marked yanked by the package registry")
    elif new_deprecated or warning:
        score = max(score, 4)
        reasons.append("package installation reported a deprecation warning")

    if policy.review_network_additions and deltas["network_count_delta"] > 0:
        score = max(score, 4)
    if policy.review_process_additions and deltas["process_count_delta"] > 0:
        score = max(score, 4)

    if hard_failure:
        decision = "BLOCK" if policy.block_on_test_failure else "REVIEW"
        severity = "HIGH"
    elif score >= 10:
        decision, severity = "REVIEW", "HIGH"
    elif score >= 4:
        decision, severity = "REVIEW", "MEDIUM"
    else:
        decision, severity = "PASS", "LOW"

    reason = "No material behavioral difference was observed by the configured verification signals." if not reasons else "; ".join(reasons) + "."
    return {"decision": decision, "severity": severity, "score": score, "reason": reason, "deltas": deltas}
