# Local Kind rollout troubleshooting

## Symptom

`kubectl rollout status deployment/backend -n dcv` reports `old replicas are pending termination` and the local bootstrap times out.

## Why the bootstrap was changed

The local startup script used to apply the manifests and then unconditionally run `kubectl rollout restart` for both Deployments. If `kubectl apply` had already changed an image tag, this could trigger a second rollout before the first one finished. Rebuilding a local image under the same tag also made Kubernetes unaware that the image contents had changed.

The updated script records each local Docker image ID. It triggers a Pod-template change only when an image's contents changed while its image tag stayed the same, and otherwise lets `kubectl apply` handle tag changes. During rollout it reports Deployment/Pod status and recent namespace events. In the **local `kind-dcv` cluster only**, if replacement replicas are healthy and an old Pod has remained in `Terminating` for over 60 seconds on a Ready node, the script removes that stale Pod object so the rollout can finish.

This stale-Pod cleanup is a local development recovery mechanism. Do not copy the force-delete behavior into a production deployment script; production recovery must follow the cluster's node-health and workload-specific runbook.


## Symptom: `Admin API route is missing from the deployed backend image`

If the backend and frontend rollout are healthy and release identity checks pass, this message may come from a false-negative route-registry check. FastAPI's internal `app.routes` representation is not a reliable substitute for testing that an endpoint can actually answer. The bootstrap now makes an HTTP request from inside the backend container to `http://127.0.0.1:8000/api/admin/context` and requires HTTP 200. If that live check fails, the script reports the command output; inspect `kubectl logs deployment/backend -n dcv` and confirm PostgreSQL readiness rather than restarting deployments blindly.

## Run the fixed local bootstrap

Open PowerShell and run:

```powershell
cd C:\dev\dependency-change-verification-final
Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass -Force
.\scripts\start-local.ps1
```

The script does not delete the PostgreSQL StatefulSet or PVC. It continues to preserve existing database data.

## If it still fails

The script now prints Deployment status, selected Pods, `describe` output, recent namespace events, and current/previous container logs. These commands can also be run manually:

```powershell
kubectl config use-context kind-dcv
kubectl get nodes -o wide
kubectl get deployments,pods,replicasets -n dcv -o wide
kubectl get events -n dcv --sort-by=.lastTimestamp
kubectl describe deployment backend -n dcv
kubectl get pods -n dcv -l app=dcv-backend -o wide
```

Check whether the replacement backend Pod is Ready and whether the old Pod's node is Ready before taking manual action. Do not delete the PostgreSQL Pod/PVC as a rollout workaround.

### `invalid JSON patch` while updating an image-content annotation

On Windows PowerShell, passing nested JSON directly with `kubectl patch -p $json` can be altered by native-command argument quoting. The local bootstrap writes a UTF-8 JSON patch file without a BOM and invokes `kubectl patch --patch-file <path>` instead. If this error appears on an older checkout, update `scripts/start-local.ps1` to the current packaged version; do not delete the Kind cluster or PostgreSQL PVC to resolve a patch-argument problem.

