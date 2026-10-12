$ErrorActionPreference = "Stop"
Set-Location (Split-Path -Parent $PSScriptRoot)
$BaseVersion = (Get-Content .\VERSION -Raw).Trim()
if ($BaseVersion -notmatch '^\d+\.\d+\.\d+$') { throw "VERSION must contain a semantic version such as 15.0.0" }
$Release = "$BaseVersion-local"
Write-Host "Building Dependency Change Verification release $Release..." -ForegroundColor Cyan
$project = (Get-Location).Path
Write-Host "Project source: $project"

$cfg = Get-Content .\backend\app\config.py -Raw
$expectedSource = 'app_version: str = "' + $BaseVersion + '"'
if ($cfg -notmatch [regex]::Escape($expectedSource)) {
  throw "Wrong project source: backend/app/config.py does not match VERSION $BaseVersion."
}

$builds = @(
  @{ Tag="dcv-backend:$Release"; Path=".\backend"; Name="Backend" },
  @{ Tag="dcv-frontend:$Release"; Path=".\frontend"; Name="Frontend" },
  @{ Tag="dcv-runner-python:$Release"; Path=".\runner\python"; Name="Python runner" },
  @{ Tag="dcv-runner-node:$Release"; Path=".\runner\node"; Name="Node runner" }
)

# Versioned tags make the build deterministic without a destructive pre-build cleanup.
# Re-running the same release simply rebuilds/reuses that tag and then reloads it into kind.
foreach ($build in $builds) {
  docker build -t $build.Tag $build.Path
  if ($LASTEXITCODE -ne 0) { throw "$($build.Name) Docker build failed." }

  # docker image ls returns an empty result, rather than a failure, when a tag is absent.
  $imageId = (docker image ls --quiet $build.Tag 2>$null | Select-Object -First 1)
  if (-not $imageId) { throw "$($build.Name) image was not created: $($build.Tag)" }
}

$images = $builds | ForEach-Object { $_.Tag }
Write-Host "Loading release $Release into kind cluster dcv..." -ForegroundColor Cyan
foreach ($image in $images) {
  kind load docker-image $image --name dcv
  if ($LASTEXITCODE -ne 0) { throw "Failed to load image into kind: $image" }
}
Write-Host "Images loaded: $Release" -ForegroundColor Green
