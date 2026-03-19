Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

Write-Host "Starting full release build..."
& ".\build_exe.ps1"
& ".\build_installer.ps1"
Write-Host "Release artifacts are available in dist\ and dist\installer\."
