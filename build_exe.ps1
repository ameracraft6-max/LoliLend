Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

function Assert-LastExitCode {
    param(
        [string]$Action
    )

    if ($LASTEXITCODE -ne 0) {
        throw "$Action failed with exit code $LASTEXITCODE."
    }
}

Write-Host "Installing build dependencies..."
python -m pip install -r requirements.txt
Assert-LastExitCode "pip install"

Write-Host "Building portable one-file executable..."
python -m PyInstaller --noconfirm --clean .\LoliLend.spec
Assert-LastExitCode "PyInstaller portable build"

Write-Host "Portable build complete: dist\LoliLend.exe"
