$ErrorActionPreference = "Stop"
$RepoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
Set-Location $RepoRoot
$version = (Get-Content (Join-Path $RepoRoot "VERSION") -Raw).Trim()
if ($version -notmatch '^\d+\.\d+\.\d+$') { throw "VERSION is not semantic: $version" }
if ((Get-Content (Join-Path $RepoRoot "RELEASE_VERSION") -Raw).Trim() -ne $version) { throw "RELEASE_VERSION does not match VERSION." }
$legacy = Join-Path $RepoRoot "infra\k8s\overlays"
if (Test-Path $legacy) { throw "Legacy Kustomize overlays directory still exists: $legacy" }
$local = Join-Path $RepoRoot "infra\k8s\local"
$production = Join-Path $RepoRoot "infra\k8s\production"
foreach ($root in @($local, $production)) {
  kubectl kustomize $root *> $null
  if ($LASTEXITCODE -ne 0) { throw "Kustomize render failed: $root" }
}
$yamlFiles = Get-ChildItem (Join-Path $RepoRoot "infra\k8s") -Recurse -Filter *.yaml -File
foreach ($file in $yamlFiles) {
  $text = Get-Content $file.FullName -Raw
  if ($text -match 'type:\s*Recreate[\s\S]*rollingUpdate:|rollingUpdate:[\s\S]*type:\s*Recreate') {
    throw "Invalid Deployment strategy combination found in $($file.FullName)."
  }
}
Write-Host "DCV $version release preflight passed." -ForegroundColor Green
