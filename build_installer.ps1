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

function Get-InnoCompiler {
    $candidates = @(
        (Get-Command ISCC.exe -ErrorAction SilentlyContinue | Select-Object -ExpandProperty Source -ErrorAction SilentlyContinue),
        (Join-Path $env:LOCALAPPDATA "Programs\Inno Setup 6\ISCC.exe"),
        "C:\Program Files (x86)\Inno Setup 6\ISCC.exe",
        "C:\Program Files\Inno Setup 6\ISCC.exe"
    ) | Where-Object { $_ }

    foreach ($candidate in $candidates) {
        if (Test-Path $candidate) {
            return $candidate
        }
    }

    return $null
}

function Install-InnoSetup {
    $winget = Get-Command winget -ErrorAction SilentlyContinue
    if ($winget) {
        Write-Host "Installing Inno Setup with winget..."
        winget install `
          --id JRSoftware.InnoSetup `
          --source winget `
          --accept-source-agreements `
          --accept-package-agreements `
          --silent `
          --scope user
        Assert-LastExitCode "winget install Inno Setup"
        return
    }

    $choco = Get-Command choco -ErrorAction SilentlyContinue
    if ($choco) {
        Write-Host "Installing Inno Setup with Chocolatey..."
        choco install InnoSetup -y --no-progress
        Assert-LastExitCode "choco install Inno Setup"
        return
    }

    throw "Neither winget nor choco is available to install Inno Setup."
}

function Get-AppVersion {
    $version = python -c "from lolilend.version import APP_VERSION; print(APP_VERSION)"
    if (-not $version) {
        throw "Unable to resolve APP_VERSION from lolilend.version"
    }
    return $version.Trim()
}

Write-Host "Installing build dependencies..."
python -m pip install -r requirements.txt
Assert-LastExitCode "pip install"

$iscc = Get-InnoCompiler
if (-not $iscc) {
    Write-Host "Inno Setup not found. Installing..."
    Install-InnoSetup
    $iscc = Get-InnoCompiler
}

if (-not $iscc) {
    throw "Inno Setup compiler (ISCC.exe) is not available after installation."
}

$appVersion = Get-AppVersion
$installerDistPath = Join-Path $PWD "dist\installer_app"
$installerWorkPath = Join-Path $PWD "build\pyinstaller-installer"
$installerOutputPath = Join-Path $PWD "dist\installer"
$installerSpec = Join-Path $PWD "LoliLend.installer.spec"

if (-not (Test-Path $installerSpec)) {
    throw "Installer spec file not found: $installerSpec"
}

Write-Host "Building installer application bundle..."
python -m PyInstaller `
  --noconfirm `
  --clean `
  --distpath $installerDistPath `
  --workpath $installerWorkPath `
  $installerSpec
Assert-LastExitCode "PyInstaller installer bundle build"

if (-not (Test-Path $installerOutputPath)) {
    New-Item -ItemType Directory -Path $installerOutputPath | Out-Null
}

Write-Host "Compiling installer..."
& $iscc `
  "/DAppVersion=$appVersion" `
  "/DSourceDir=$installerDistPath" `
  "/DOutputDir=$installerOutputPath" `
  ".\installer\LoliLend.iss"
Assert-LastExitCode "Inno Setup compilation"

Write-Host "Installer build complete: dist\installer"
