$ErrorActionPreference = "Stop"
Set-Location (Split-Path -Parent $PSScriptRoot)
$remote = (git config --get remote.origin.url)
if (-not $remote) { throw "No git remote origin found. Run this script from a cloned Git repository." }
if ($remote -match 'github\.com[/:]([^/]+)/([^/.]+)(\.git)?$') {
    $owner = $Matches[1]
    $repo = $Matches[2]
} else { throw "GitHub origin could not be parsed: $remote" }
$files = @(
    'infra/k8s/argocd/application.yaml',
    'infra/k8s/argocd/application-local.yaml',
    'infra/k8s/argocd/project.yaml',
    'infra/k8s/base/backend.yaml',
    'infra/k8s/base/frontend.yaml',
    'infra/k8s/local/kustomization.yaml',
    'infra/k8s/production/kustomization.yaml',
    'README.md',
    'docs/ARCHITECTURE.md'
)
foreach ($file in $files) {
    if (Test-Path $file) {
        $content = Get-Content $file -Raw
        $content = $content.Replace('https://github.com/OWNER/dependency-change-verification.git', "https://github.com/$owner/$repo.git")
        $content = $content.Replace('ghcr.io/OWNER/', "ghcr.io/$owner/")
        Set-Content -Path $file -Value $content -NoNewline
    }
}
Write-Host "Configured GitHub owner=$owner repository=$repo"
