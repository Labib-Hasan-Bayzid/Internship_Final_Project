$ErrorActionPreference = "Continue"
$context = kubectl config current-context 2>$null
Write-Host "DCV local diagnostics" -ForegroundColor Cyan
Write-Host "Current Kubernetes context: $context"
if ($context -ne "kind-dcv") {
  Write-Warning "Expected context kind-dcv. This script is read-only, but verify the target cluster before sharing output."
}
Write-Host "--- Nodes ---" -ForegroundColor Yellow
kubectl get nodes -o wide
Write-Host "--- DCV deployments ---" -ForegroundColor Yellow
kubectl get deployments -n dcv -o wide
Write-Host "--- DCV ReplicaSets ---" -ForegroundColor Yellow
kubectl get rs -n dcv -o wide
Write-Host "--- DCV pods ---" -ForegroundColor Yellow
kubectl get pods -n dcv -o wide
Write-Host "--- Backend pod details and logs ---" -ForegroundColor Yellow
$podNamesRaw = kubectl get pods -n dcv -l app=dcv-backend -o jsonpath='{.items[*].metadata.name}' 2>$null
$podNames = @($podNamesRaw -split '\s+' | Where-Object { $_ })
foreach ($podName in $podNames) {
  kubectl describe pod $podName -n dcv
  kubectl logs $podName -n dcv --all-containers=true --tail=250 --prefix=true
  kubectl logs $podName -n dcv --all-containers=true --previous --tail=150 --prefix=true 2>$null
}
Write-Host "--- PostgreSQL state and recent logs ---" -ForegroundColor Yellow
kubectl get pods -n dcv -l app=dcv-postgres -o wide
$pgPodsRaw = kubectl get pods -n dcv -l app=dcv-postgres -o jsonpath='{.items[*].metadata.name}' 2>$null
$pgPods = @($pgPodsRaw -split '\s+' | Where-Object { $_ })
foreach ($podName in $pgPods) {
  kubectl describe pod $podName -n dcv
  kubectl logs $podName -n dcv --tail=150 --prefix=true
}
Write-Host "--- Recent events ---" -ForegroundColor Yellow
kubectl get events -n dcv --sort-by=.metadata.creationTimestamp
Write-Host "--- Done ---" -ForegroundColor Cyan
