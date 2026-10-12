from pathlib import Path
import yaml

ROOT = Path(__file__).resolve().parents[2]

def _check_kustomization(path: Path):
    doc = yaml.safe_load(path.read_text())
    base = path.parent
    for item in doc.get("resources", []):
        if not isinstance(item, str) or "://" in item:
            continue
        target = (base / item).resolve()
        assert str(target).startswith(str(ROOT.resolve())), f"resource escapes repository: {path} -> {item}"
        assert target.exists(), f"missing Kustomize resource: {path} -> {item}"

def test_local_kustomize_resources_are_repo_relative():
    _check_kustomization(ROOT / "infra/k8s/local/kustomization.yaml")

def test_production_kustomize_resources_are_repo_relative():
    _check_kustomization(ROOT / "infra/k8s/production/kustomization.yaml")


def test_backend_startup_probe_allows_schema_initialization():
    docs = list(yaml.safe_load_all((ROOT / "infra/k8s/base/backend.yaml").read_text()))
    deployment = next(doc for doc in docs if doc and doc.get("kind") == "Deployment")
    container = deployment["spec"]["template"]["spec"]["containers"][0]
    probe = container["startupProbe"]
    assert probe["httpGet"]["path"] == "/api/health"
    assert probe["failureThreshold"] * probe["periodSeconds"] >= 300

def test_backend_rollout_failure_has_diagnostics():
    script = (ROOT / "scripts/start-local.ps1").read_text()
    diagnostic_script = (ROOT / "scripts/diagnose-local.ps1").read_text()
    assert 'Write-DeploymentDiagnostics -Namespace "dcv" -Deployment "backend"' in script
    assert "kubectl describe pod" in diagnostic_script
    assert "kubectl logs" in diagnostic_script
    assert "kubectl get events" in diagnostic_script


def test_local_bootstrap_triggers_one_rollout_per_apply():
    local = (ROOT / "infra/k8s/local/kustomization.yaml").read_text()
    assert local.count("__DCV_ROLLOUT_STAMP__") == 2
    for relative in ("scripts/start-local.ps1", "scripts/deploy-direct.ps1"):
        script = (ROOT / relative).read_text()
        assert 'Replace("__DCV_ROLLOUT_STAMP__", $RolloutStamp)' in script
        assert "kubectl rollout restart deployment/backend" not in script
        assert "kubectl rollout restart deployment/frontend" not in script

def test_backend_termination_grace_allows_inflight_work_to_finish():
    docs = list(yaml.safe_load_all((ROOT / "infra/k8s/base/backend.yaml").read_text()))
    deployment = next(doc for doc in docs if doc and doc.get("kind") == "Deployment")
    pod_spec = deployment["spec"]["template"]["spec"]
    assert pod_spec["terminationGracePeriodSeconds"] >= 60

def test_post_rollout_release_verification_targets_active_ready_backend_pod():
    script = (ROOT / "scripts/start-local.ps1").read_text()
    assert "= kubectl exec deployment/backend" not in script
    assert "spec.replicas -gt 0" in script
    assert "pod-template-hash" in script
    assert "metadata.deletionTimestamp" in script
    assert "Verifying release against active backend Pod" in script
    assert "kubectl exec $BackendPodName" in script
    assert "/openapi.json" in script and "/api/admin/context" in script

