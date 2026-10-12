# DCV local rollout failure: diagnosis and patched remediation

## Findings from the supplied diagnostics

The current cluster snapshot shows backend `1/1` Ready and frontend `1/1` Ready. The latest backend logs show normal ASGI startup and successful `/api/health` and `/api/ready` responses. The startup probe's initial `connection refused` event is consistent with a probe arriving before Uvicorn had bound port 8000; it was followed by successful 200 responses, so it is not itself the persistent rollout failure.

The important event sequence creates a specific, reproducible deployment race: `backend-696d7d5d88` was scaled up, then scaled down about one second later while `backend-744fb9ddc8` scaled up. Both used `dcv-backend:15.0.0-local`. The scripts first apply a changed pod template and then call `kubectl rollout restart`, which can create a second ReplicaSet while the first rollout is still in flight. The old pod is then told to stop and remains in its 30-second termination period. The follow-up patch removes this duplicate rollout path.

A separate environmental signal is present: Kubernetes reported `SandboxChanged` for backend, frontend, and PostgreSQL. PostgreSQL's previous container state was `Unknown` with exit code 255, but PostgreSQL recovered its existing data directory and became Ready. The transcript is insufficient to identify whether Docker Desktop, WSL2, or the kind node/container runtime caused that sandbox interruption. Do not delete the PostgreSQL PVC.

## Changes in the new patch

- The local Kustomize overlay now includes a per-run pod-template annotation for backend and frontend. The scripts substitute a fresh UTC timestamp in the disposable rendered overlay before applying it. This refreshes the Deployment even when a local image is rebuilt under an unchanged version tag.
- Removed `kubectl rollout restart` after `kubectl apply`. The annotation itself triggers a single rollout, avoiding overlapping ReplicaSet revisions.
- Increased backend `terminationGracePeriodSeconds` from 30 to 60 seconds because some worker paths may have an in-flight database/provider operation.
- Increased rollout wait bounds from 300 to 420 seconds to accommodate the 300-second startup probe allowance plus graceful termination and rollout convergence.
- Retained the dedicated startup probe and bounded background-worker shutdown changes from the previous patch.
- Retained read-only rollout diagnostics and preservation of the existing PostgreSQL StatefulSet and PVC.
- Added regression tests for annotation substitution and absence of explicit second restarts.

## Validation in this workspace

- Python source compilation: passed.
- 19 focused offline tests: passed.
- All 23 YAML/YML files parsed successfully. Both embedded Kustomize strategic-merge patches were parsed separately and contain the expected annotation/grace configuration.
- Script-source checks confirmed both Windows deployment scripts substitute the rollout timestamp and no longer contain explicit backend/frontend `kubectl rollout restart` commands.
- This environment does not have Windows PowerShell, Docker, kubectl, or kind, so the patched scripts have not been executed against the user's live Windows cluster.

## Verification on Windows PowerShell

From the extracted patched project root, run:

```powershell
Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass -Force
.\scripts\start-local.ps1
```

Then verify:

```powershell
kubectl rollout status deployment/backend -n dcv --timeout=420s
kubectl rollout status deployment/frontend -n dcv --timeout=420s
kubectl get pods -n dcv -o wide
kubectl get rs -n dcv -l app=dcv-backend -o wide
```

Success means both Deployments finish, one backend and one frontend Pod are Ready, the backend build-info reports the expected release, and no Pod remains stuck in `Terminating`. If `SandboxChanged` recurs, investigate Docker Desktop/WSL2/kind node restarts separately; the source patch cannot repair a crashing container runtime. Never delete the PostgreSQL PVC to resolve this rollout.


## Follow-up: Admin API route verification after a successful rollout

The next run shows both rollouts succeeding, followed by `Admin API route is missing from the deployed backend image.` The backend source does register `admin_router` under `/api/admin`, and `backend/app/api/admin.py` declares `GET /context`, so the expected path is `/api/admin/context`. The previous post-rollout check used `kubectl exec deployment/backend`; this resolves through a Deployment selector rather than pinning every check to the new active ReplicaSet Pod. During a rolling update, a terminating old Pod can still match that selector, leading to a false negative even though the new Pod is healthy.

The bootstrap now identifies the active ReplicaSet (`spec.replicas > 0` and highest Deployment revision), validates its image tag, selects a Ready, non-terminating Pod with that ReplicaSet's `pod-template-hash`, and runs all release checks against that exact Pod. The Admin API check now queries the running process's `/openapi.json` instead of importing `app.main` in a second Python process. The database and PVC are not modified by these checks.

Verification on Windows: rerun `scripts/start-local.ps1` from this patched project. The script prints the exact Pod used for verification. It should finish with the DCV release success message. If the check fails, the error includes the active Pod name; inspect it with `kubectl describe pod <pod-name> -n dcv` and `kubectl logs <pod-name> -n dcv --tail=200`.
