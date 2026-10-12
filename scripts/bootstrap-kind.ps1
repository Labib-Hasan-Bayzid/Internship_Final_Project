$ErrorActionPreference = "Stop"
Write-Host "Checking Docker..."
docker info | Out-Null
if (kind get clusters 2>$null | Select-String -SimpleMatch "dcv") {
  Write-Host "kind cluster 'dcv' already exists."
} else {
  kind create cluster --config .\infra\kind\kind-config.yaml
}
kubectl cluster-info --context kind-dcv
kubectl wait --for=condition=Ready nodes --all --timeout=180s
kubectl get nodes -o wide
