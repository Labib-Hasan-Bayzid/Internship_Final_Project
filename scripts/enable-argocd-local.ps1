$ErrorActionPreference = "Stop"
Set-Location (Split-Path -Parent $PSScriptRoot)
if (-not (kubectl get namespace argocd --ignore-not-found)) { .\scripts\install-argocd.ps1 }
kubectl apply -f .\infra\k8s\argocd\project.yaml
kubectl apply -f .\infra\k8s\argocd\application-local.yaml
Write-Host "Argo CD application registered."
Write-Host "Open Argo CD UI in another terminal with:"
Write-Host "  kubectl port-forward svc/argocd-server -n argocd 8080:443"
Write-Host "Then browse: https://localhost:8080"
