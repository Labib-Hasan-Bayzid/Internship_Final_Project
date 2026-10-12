$ErrorActionPreference = "Stop"
winget install -e --id Git.Git --accept-source-agreements --accept-package-agreements
winget install -e --id Microsoft.VisualStudioCode --accept-source-agreements --accept-package-agreements
winget install -e --id Kubernetes.kubectl --accept-source-agreements --accept-package-agreements
winget install -e --id Kubernetes.kind --accept-source-agreements --accept-package-agreements
winget install -e --id Helm.Helm --accept-source-agreements --accept-package-agreements
Write-Host "Close and reopen PowerShell so PATH changes take effect."
