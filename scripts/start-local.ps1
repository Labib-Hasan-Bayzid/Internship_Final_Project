$ErrorActionPreference = "Stop"
$RepoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
Set-Location $RepoRoot
$BaseVersion = (Get-Content (Join-Path $RepoRoot "VERSION") -Raw).Trim()
if ($BaseVersion -notmatch '^\d+\.\d+\.\d+$') { throw "VERSION must contain a semantic version such as 15.0.0" }
$Release = "$BaseVersion-local"
Write-Host "DCV $Release local bootstrap" -ForegroundColor Cyan
Write-Host "Project source: $RepoRoot" -ForegroundColor DarkGray

function Write-DeploymentDiagnostics {
  param(
    [Parameter(Mandatory=$true)][string]$Namespace,
    [Parameter(Mandatory=$true)][string]$Deployment,
    [Parameter(Mandatory=$true)][string]$Label
  )
  $oldEap = $ErrorActionPreference
  $ErrorActionPreference = "Continue"
  try {
    Write-Host "`n===== DCV rollout diagnostics: $Deployment / namespace $Namespace =====" -ForegroundColor Yellow
    Write-Host "--- Deployment ---" -ForegroundColor Yellow
    kubectl get deployment $Deployment -n $Namespace -o wide
    kubectl describe deployment $Deployment -n $Namespace
    Write-Host "--- ReplicaSets ---" -ForegroundColor Yellow
    kubectl get rs -n $Namespace -l $Label -o wide
    Write-Host "--- Pods ---" -ForegroundColor Yellow
    kubectl get pods -n $Namespace -l $Label -o wide
    $podNamesRaw = kubectl get pods -n $Namespace -l $Label -o jsonpath='{.items[*].metadata.name}' 2>$null
    $podNames = @($podNamesRaw -split '\s+' | Where-Object { $_ })
    foreach ($podName in $podNames) {
      Write-Host "--- Describe pod: $podName ---" -ForegroundColor Yellow
      kubectl describe pod $podName -n $Namespace
      Write-Host "--- Current logs: $podName ---" -ForegroundColor Yellow
      kubectl logs $podName -n $Namespace --all-containers=true --tail=200 --prefix=true
      Write-Host "--- Previous container logs: $podName (if any) ---" -ForegroundColor Yellow
      kubectl logs $podName -n $Namespace --all-containers=true --previous --tail=120 --prefix=true 2>$null
    }
    Write-Host "--- PostgreSQL pod state ---" -ForegroundColor Yellow
    kubectl get pods -n dcv -l app=dcv-postgres -o wide
    Write-Host "--- Recent namespace events ---" -ForegroundColor Yellow
    kubectl get events -n $Namespace --sort-by=.metadata.creationTimestamp
    Write-Host "===== End rollout diagnostics =====`n" -ForegroundColor Yellow
  } finally {
    $ErrorActionPreference = $oldEap
  }
}

$cfg = Get-Content (Join-Path $RepoRoot "backend\app\config.py") -Raw
$expectedSource = 'app_version: str = "' + $BaseVersion + '"'
if ($cfg -notmatch [regex]::Escape($expectedSource)) { throw "backend/app/config.py does not match VERSION $BaseVersion." }

docker info *> $null
if ($LASTEXITCODE -ne 0) { throw "Docker Desktop is not running." }

$clusters = @(kind get clusters 2>$null)
if ($clusters -notcontains "dcv") {
  kind create cluster --config (Join-Path $RepoRoot "infra\kind\kind-config.yaml")
  if ($LASTEXITCODE -ne 0) { throw "Failed to create the dcv kind cluster." }
}
kind export kubeconfig --name dcv | Out-Null
kubectl config use-context kind-dcv | Out-Null
kubectl wait --for=condition=Ready nodes --all --timeout=180s | Out-Null
kubectl get nodes | Out-Host

.\scripts\build-local.ps1

$SourceKustomize = Join-Path $RepoRoot "infra\k8s\local"
$LocalPostgres = Join-Path $SourceKustomize "postgres.yaml"
$LocalPostgresService = Join-Path $SourceKustomize "postgres-service.yaml"

# Render from a disposable copy so release tags and expected-release markers always match
# VERSION, while the checked-in Kustomize files remain immutable.
$RenderRoot = Join-Path ([System.IO.Path]::GetTempPath()) ("dcv-k8s-local-" + $PID)
if (Test-Path $RenderRoot) { Remove-Item -Recurse -Force $RenderRoot }
New-Item -ItemType Directory -Path $RenderRoot | Out-Null
Copy-Item -Recurse (Join-Path $RepoRoot "infra\k8s\base") $RenderRoot
Copy-Item -Recurse $SourceKustomize $RenderRoot
$LocalKustomize = Join-Path $RenderRoot "local"
$localKustomizationPath = Join-Path $LocalKustomize "kustomization.yaml"
$localKustomization = Get-Content $localKustomizationPath -Raw
$overlayVersionMatch = [regex]::Match($localKustomization, 'newTag:\s*(\d+\.\d+\.\d+)-local')
if (-not $overlayVersionMatch.Success) { throw "Local Kustomize overlay does not contain a semantic local image tag." }
$OverlayBaseVersion = $overlayVersionMatch.Groups[1].Value
$localKustomization = $localKustomization.Replace("$OverlayBaseVersion-local", $Release)
$localKustomization = $localKustomization.Replace('value: "' + $OverlayBaseVersion + '"', 'value: "' + $BaseVersion + '"')
$RolloutStamp = [DateTime]::UtcNow.ToString("yyyy-MM-ddTHH:mm:ss.fffZ")
$localKustomization = $localKustomization.Replace("__DCV_ROLLOUT_STAMP__", $RolloutStamp)
Set-Content -Path $localKustomizationPath -Value $localKustomization -Encoding UTF8

# Ensure namespaces exist before server-side dry-run validation. This is safe to re-run.
kubectl apply -f (Join-Path $RepoRoot "infra\k8s\base\namespace.yaml") | Out-Host
if ($LASTEXITCODE -ne 0) { throw "DCV namespace creation failed." }
kubectl apply -f (Join-Path $RepoRoot "infra\k8s\base\runner-namespace.yaml") | Out-Host
if ($LASTEXITCODE -ne 0) { throw "Runner namespace creation failed." }

# Critical preflight: validate Kustomize before touching application resources.
kubectl kustomize $LocalKustomize *> $null
if ($LASTEXITCODE -ne 0) { throw "Kustomize rendering failed. The local Kustomize root is invalid." }

# Apply application resources only. PostgreSQL is deliberately excluded so an existing
# data-bearing StatefulSet/PVC is never patched through Kustomize.
kubectl apply -k $LocalKustomize --dry-run=server | Out-Host
if ($LASTEXITCODE -ne 0) { throw "Kubernetes manifest validation failed. Existing application resources were not changed." }
kubectl apply -k $LocalKustomize | Out-Host
if ($LASTEXITCODE -ne 0) { throw "Kubernetes application deployment failed." }

# The Service is safe to reconcile independently. The StatefulSet is created only when absent.
kubectl apply -f $LocalPostgresService | Out-Host
if ($LASTEXITCODE -ne 0) { throw "PostgreSQL Service deployment failed." }
$pgStatefulSet = kubectl get statefulset postgres -n dcv --ignore-not-found -o name
if (-not $pgStatefulSet) {
  Write-Host "PostgreSQL StatefulSet not found; creating the initial local database." -ForegroundColor Yellow
  kubectl apply -f $LocalPostgres | Out-Host
  if ($LASTEXITCODE -ne 0) { throw "PostgreSQL StatefulSet creation failed." }
} else {
  Write-Host "Existing PostgreSQL StatefulSet detected; preserving it and its PVC." -ForegroundColor Green
}
kubectl wait --for=condition=ready pod/postgres-0 -n dcv --timeout=240s | Out-Host
if ($LASTEXITCODE -ne 0) { throw "PostgreSQL did not become ready." }

# Force the versioned image into the active pods even when the release tag is unchanged.
# The per-run pod-template annotation above makes apply trigger exactly one fresh rollout,
# including when a local image is rebuilt under an unchanged version tag. Do not issue a
# second kubectl rollout restart here: that creates overlapping ReplicaSet revisions.
kubectl rollout status deployment/backend -n dcv --timeout=420s
if ($LASTEXITCODE -ne 0) {
  Write-DeploymentDiagnostics -Namespace "dcv" -Deployment "backend" -Label "app=dcv-backend"
  Write-Host "Release-specific manifests are in: $RenderRoot" -ForegroundColor DarkGray
  throw "Backend rollout failed or timed out. Diagnostics above include pod termination state, events, and current/previous logs. Do not delete PostgreSQL or its PVC."
}
kubectl rollout status deployment/frontend -n dcv --timeout=420s
if ($LASTEXITCODE -ne 0) {
  Write-DeploymentDiagnostics -Namespace "dcv" -Deployment "frontend" -Label "app=dcv-frontend"
  Write-Host "Release-specific manifests are in: $RenderRoot" -ForegroundColor DarkGray
  throw "Frontend rollout failed or timed out. Diagnostics above include pod state, events, and current/previous logs."
}

# Resolve the backend Pod belonging to the active ReplicaSet. `kubectl exec deployment/backend`
# can select any matching Pod, including an old Pod still terminating after a successful
# rollout. That can produce false version/route failures when the same local image tag was rebuilt.
$replicaSetJson = kubectl get rs -n dcv -l app=dcv-backend -o json
if ($LASTEXITCODE -ne 0) { throw "Could not list backend ReplicaSets for release verification." }
$replicaSets = (ConvertFrom-Json -InputObject ($replicaSetJson -join "`n")).items
$activeReplicaSet = $replicaSets |
  Where-Object { [int]$_.spec.replicas -gt 0 } |
  Sort-Object { [int]$_.metadata.annotations.'deployment.kubernetes.io/revision' } -Descending |
  Select-Object -First 1
if (-not $activeReplicaSet) {
  Write-DeploymentDiagnostics -Namespace "dcv" -Deployment "backend" -Label "app=dcv-backend"
  throw "Could not identify the active backend ReplicaSet after rollout."
}
$activeBackendImages = @($activeReplicaSet.spec.template.spec.containers | Where-Object { $_.name -eq "backend" })
if ($activeBackendImages.Count -ne 1 -or $activeBackendImages[0].image -ne "dcv-backend:$Release") {
  throw "Active backend ReplicaSet image does not match expected release image dcv-backend:$Release."
}
$podTemplateHash = $activeReplicaSet.spec.selector.matchLabels.'pod-template-hash'
if (-not $podTemplateHash) { throw "Active backend ReplicaSet has no pod-template-hash selector." }
$podJson = kubectl get pods -n dcv -l "app=dcv-backend,pod-template-hash=$podTemplateHash" -o json
if ($LASTEXITCODE -ne 0) { throw "Could not list Pods for the active backend ReplicaSet." }
$podItems = (ConvertFrom-Json -InputObject ($podJson -join "`n")).items
$readyBackendPods = @($podItems | Where-Object {
  $readyContainers = @($_.status.containerStatuses | Where-Object { $_.name -eq "backend" -and $_.ready -eq $true })
  $_.status.phase -eq "Running" -and -not $_.metadata.deletionTimestamp -and $readyContainers.Count -gt 0
})
$backendPod = $readyBackendPods | Sort-Object { [DateTime]$_.metadata.creationTimestamp } -Descending | Select-Object -First 1
if (-not $backendPod) {
  Write-DeploymentDiagnostics -Namespace "dcv" -Deployment "backend" -Label "app=dcv-backend"
  throw "The active backend ReplicaSet has no Ready, non-terminating Pod for release verification."
}
$BackendPodName = $backendPod.metadata.name
Write-Host "Verifying release against active backend Pod: $BackendPodName" -ForegroundColor DarkGray
$expected = kubectl exec $BackendPodName -n dcv -- printenv DCV_EXPECTED_RELEASE
if ($LASTEXITCODE -ne 0) { throw "Could not read DCV_EXPECTED_RELEASE from $BackendPodName." }
$loaded = kubectl exec $BackendPodName -n dcv -- python -c "from app.config import get_settings; print(get_settings().app_version)"
if ($LASTEXITCODE -ne 0) { throw "Could not read the loaded application version from $BackendPodName." }
$route = kubectl exec $BackendPodName -n dcv -- python -c "import json,urllib.request; d=json.load(urllib.request.urlopen('http://127.0.0.1:8000/openapi.json', timeout=5)); print('/api/admin/context' in d.get('paths', {}))"
if ($LASTEXITCODE -ne 0) { throw "Could not verify the Admin API route in the running backend on $BackendPodName." }
$health = kubectl exec $BackendPodName -n dcv -- python -c "import urllib.request; print(urllib.request.urlopen('http://127.0.0.1:8000/api/build-info', timeout=5).read().decode())"
if ($LASTEXITCODE -ne 0) { throw "Could not read build-info from $BackendPodName." }
if ($expected.Trim() -ne $BaseVersion) { throw "Backend expected-release marker is wrong: $expected" }
if ($loaded.Trim() -ne $BaseVersion) { throw "Wrong backend image/source loaded. Expected $BaseVersion, got $loaded" }
if ($route.Trim() -ne "True") { throw "Admin API route is missing from the active backend Pod $BackendPodName (image dcv-backend:$Release). Inspect its /openapi.json and image contents." }
if ($health -notmatch $BaseVersion) { throw "Backend build-info did not report $BaseVersion." }

Write-Host "DCV $Release deployed successfully; release identity verified." -ForegroundColor Green
Write-Host "Frontend: kubectl port-forward svc/frontend 3000:3000 -n dcv"
Write-Host "Backend:  kubectl port-forward svc/backend 8000:8000 -n dcv"
Remove-Item -Recurse -Force $RenderRoot -ErrorAction SilentlyContinue
