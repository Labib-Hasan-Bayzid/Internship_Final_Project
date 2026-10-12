$ErrorActionPreference = "Stop"
$RepoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
Set-Location $RepoRoot
$BaseVersion = (Get-Content (Join-Path $RepoRoot "VERSION") -Raw).Trim()
if ($BaseVersion -notmatch '^\d+\.\d+\.\d+$') { throw "VERSION must contain a semantic version such as 15.0.0" }
$Release = "$BaseVersion-local"
$SourceKustomize = Join-Path $RepoRoot "infra\k8s\local"
$LocalPostgres = Join-Path $SourceKustomize "postgres.yaml"
$LocalPostgresService = Join-Path $SourceKustomize "postgres-service.yaml"

# Resolve local image tags from VERSION without editing the checked-in Kustomize source.
$RenderRoot = Join-Path ([System.IO.Path]::GetTempPath()) ("dcv-direct-k8s-" + $PID)
if (Test-Path $RenderRoot) { Remove-Item -Recurse -Force $RenderRoot }
New-Item -ItemType Directory -Path $RenderRoot | Out-Null
Copy-Item -Recurse (Join-Path $RepoRoot "infra\k8s\base") $RenderRoot
Copy-Item -Recurse $SourceKustomize $RenderRoot
$local = Join-Path $RenderRoot "local"
$kustomizationPath = Join-Path $local "kustomization.yaml"
$kustomization = Get-Content $kustomizationPath -Raw
$overlayVersionMatch = [regex]::Match($kustomization, 'newTag:\s*(\d+\.\d+\.\d+)-local')
if (-not $overlayVersionMatch.Success) { throw "Local Kustomize overlay does not contain a semantic local image tag." }
$OverlayBaseVersion = $overlayVersionMatch.Groups[1].Value
$kustomization = $kustomization.Replace("$OverlayBaseVersion-local", $Release)
$kustomization = $kustomization.Replace('value: "' + $OverlayBaseVersion + '"', 'value: "' + $BaseVersion + '"')
$RolloutStamp = [DateTime]::UtcNow.ToString("yyyy-MM-ddTHH:mm:ss.fffZ")
$kustomization = $kustomization.Replace("__DCV_ROLLOUT_STAMP__", $RolloutStamp)
Set-Content -Path $kustomizationPath -Value $kustomization -Encoding UTF8

kubectl kustomize $local *> $null
if ($LASTEXITCODE -ne 0) { throw "Kustomize rendering failed." }
kubectl apply -f (Join-Path $RepoRoot "infra\k8s\base\namespace.yaml")
if ($LASTEXITCODE -ne 0) { throw "DCV namespace creation failed." }
kubectl apply -f (Join-Path $RepoRoot "infra\k8s\base\runner-namespace.yaml")
if ($LASTEXITCODE -ne 0) { throw "Runner namespace creation failed." }
kubectl apply -k $local --dry-run=server
if ($LASTEXITCODE -ne 0) { throw "Manifest server-side validation failed." }
kubectl apply -k $local
if ($LASTEXITCODE -ne 0) { throw "Application deployment failed." }
kubectl apply -f $LocalPostgresService
if ($LASTEXITCODE -ne 0) { throw "PostgreSQL Service deployment failed." }
if (-not (kubectl get statefulset postgres -n dcv --ignore-not-found -o name)) {
  kubectl apply -f $LocalPostgres
  if ($LASTEXITCODE -ne 0) { throw "PostgreSQL StatefulSet creation failed." }
}
kubectl wait --for=condition=ready pod/postgres-0 -n dcv --timeout=240s
if ($LASTEXITCODE -ne 0) { throw "PostgreSQL did not become ready." }
# Applying the per-run pod-template annotation above triggers exactly one fresh rollout,
# including when a local image is rebuilt under an unchanged version tag. A second explicit
# rollout restart here would create overlapping ReplicaSet revisions.
kubectl rollout status deployment/backend -n dcv --timeout=420s
if ($LASTEXITCODE -ne 0) {
  Write-Warning "Backend rollout failed. Run .\scripts\diagnose-local.ps1 for pod state, events, and logs."
  throw "Backend rollout failed or timed out. PostgreSQL and its PVC were not deleted."
}
kubectl rollout status deployment/frontend -n dcv --timeout=420s
if ($LASTEXITCODE -ne 0) {
  Write-Warning "Frontend rollout failed. Run .\scripts\diagnose-local.ps1 for pod state, events, and logs."
  throw "Frontend rollout failed or timed out."
}
kubectl get pods -n dcv -o wide
Remove-Item -Recurse -Force $RenderRoot -ErrorAction SilentlyContinue
