$ErrorActionPreference = "Stop"
Set-Location (Split-Path -Parent $PSScriptRoot)
Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass -Force
Write-Host "Running the same safe local bootstrap/upgrade used by new installs..."
.\scripts\start-local.ps1
