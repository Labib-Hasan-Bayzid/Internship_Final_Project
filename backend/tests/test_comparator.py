from types import SimpleNamespace
from app.services.comparator import compare_behavior


def policy(**kwargs):
    defaults = dict(review_network_additions=True, review_process_additions=True, max_file_delta=20, block_on_test_failure=True)
    defaults.update(kwargs)
    return SimpleNamespace(**defaults)


def test_pass_when_no_material_change():
    a = {"exit_code": 0, "files_changed": ["a"], "process_commands": [], "network_endpoints": [], "smoke_test": {"exit_code": 0}}
    r = compare_behavior(a, a, policy())
    assert r["decision"] == "PASS"


def test_review_on_new_network():
    old = {"exit_code": 0, "files_changed": [], "process_commands": [], "network_endpoints": []}
    new = {"exit_code": 0, "files_changed": [], "process_commands": [], "network_endpoints": ["1.1.1.1:443"]}
    r = compare_behavior(old, new, policy())
    assert r["decision"] == "REVIEW"
    assert r["deltas"]["network_count_delta"] == 1


def test_block_on_smoke_failure():
    old = {"exit_code": 0, "files_changed": [], "process_commands": [], "network_endpoints": [], "smoke_test": {"exit_code": 0}}
    new = {"exit_code": 0, "files_changed": [], "process_commands": [], "network_endpoints": [], "smoke_test": {"exit_code": 1}}
    r = compare_behavior(old, new, policy())
    assert r["decision"] == "BLOCK"


def test_root_dependency_is_not_counted_as_transitive_change():
    old = {"exit_code": 0, "files_changed": [], "process_commands": [], "network_endpoints": [], "dependency_versions": {"requests": "2.31.0", "urllib3": "2.0.0"}}
    new = {"exit_code": 0, "files_changed": [], "process_commands": [], "network_endpoints": [], "dependency_versions": {"requests": "2.32.1", "urllib3": "2.1.0"}}
    r = compare_behavior(old, new, policy(), root_package="requests")
    assert r["deltas"]["dependency_version_changes"] == ["urllib3"]
    assert r["deltas"]["dependency_version_change_count"] == 1


def test_runtime_regression_triggers_review():
    p = policy(runtime_regression_review_percent=50, runtime_regression_block_percent=150, runtime_regression_min_ms=100)
    old = {"exit_code": 0, "files_changed": [], "process_commands": [], "network_endpoints": [], "smoke_test": {"exit_code": 0, "duration_ms": 1000}}
    new = {"exit_code": 0, "files_changed": [], "process_commands": [], "network_endpoints": [], "smoke_test": {"exit_code": 0, "duration_ms": 1600}}
    r = compare_behavior(old, new, p)
    assert r["decision"] == "REVIEW"
    assert r["deltas"]["smoke_regression_percent"] == 60.0


def test_runtime_regression_can_block():
    p = policy(runtime_regression_review_percent=50, runtime_regression_block_percent=150, runtime_regression_min_ms=100)
    old = {"exit_code": 0, "files_changed": [], "process_commands": [], "network_endpoints": [], "smoke_test": {"exit_code": 0, "duration_ms": 1000}}
    new = {"exit_code": 0, "files_changed": [], "process_commands": [], "network_endpoints": [], "smoke_test": {"exit_code": 0, "duration_ms": 2600}}
    r = compare_behavior(old, new, p)
    assert r["decision"] == "BLOCK"


def test_network_and_process_policy_can_disable_gate_scoring():
    p = policy(review_network_additions=False, review_process_additions=False)
    old = {"exit_code": 0, "files_changed": [], "process_commands": [], "network_endpoints": []}
    new = {"exit_code": 0, "files_changed": [], "process_commands": ["helper"], "network_endpoints": ["1.1.1.1:443"]}
    r = compare_behavior(old, new, p)
    assert r["decision"] == "PASS"
    assert r["deltas"]["network_count_delta"] == 1
    assert r["deltas"]["process_count_delta"] == 1
