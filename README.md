# LoliLend

Desktop application on `PySide6` with monitoring, game analytics, and advanced UI customization.
Includes a neon bootstrap launcher with automatic GitHub update flow.
Includes an embedded Telegram local SOCKS5 proxy tab powered by `tg-ws-proxy` core.

## Run from source

```powershell
python -m pip install -r requirements.txt
python main.py
```

`main.py` now starts the launcher by default. To run the main app UI directly:

```powershell
python main.py --run-app
```

## Build portable `.exe`

```powershell
.\build_exe.ps1
```

Result: `dist\LoliLend.exe`

## Build Windows installer

```powershell
.\build_installer.ps1
```

The script:
- installs Python build dependencies,
- installs `Inno Setup` automatically if required,
- builds a `PyInstaller` `onedir` bundle for setup packaging,
- compiles a Windows installer with shortcuts and uninstall support.

Result: `dist\installer\LoliLend-Setup-<version>.exe`

## Full release build

```powershell
.\build_release.ps1
```

This command builds both the portable executable and the installer.

## GitHub release publish flow (auto-update)

The launcher checks stable GitHub Releases and downloads installer assets that match:

- tag format: `vX.Y.Z`
- asset format: `LoliLend-Setup-X.Y.Z.exe`
- prerelease builds are ignored

### One-time setup

1. Create a new **public** GitHub repository named `LoliLend` (without README/.gitignore template files).
2. Initialize and push this folder:
   ```powershell
   git init
   git add .
   git commit -m "Initial release-ready project"
   git branch -M main
   git remote add origin https://github.com/<owner>/LoliLend.git
   git push -u origin main
   ```
3. In launcher settings set `GitHub repo` to your real `owner/repo`.
   Default in current build: `ameracraft6-max/LoliLend`.

### Publish steps

1. Bump `APP_VERSION` in `lolilend/version.py`.
2. Commit changes.
3. Create and push tag: `vX.Y.Z`.
4. Wait for GitHub Actions workflow **Release Windows Installer** to finish.
5. Verify Release contains `LoliLend-Setup-X.Y.Z.exe`.

### Operational checklist

1. Install an older launcher/app build on a test machine.
2. Start launcher and confirm it detects newer `vX.Y.Z`.
3. Confirm auto-download starts and silent installer runs.
4. Confirm launcher restarts and app version is updated.

## Key files

- `main.py`: application entry point
- `lolilend/launcher.py`: bootstrap launcher UI and update orchestration
- `lolilend/updater.py`: GitHub release discovery, semver checks, download and silent installer helpers
- `lolilend/app_main.py`: direct main app startup routine
- `lolilend/ui.py`: main UI and runtime behavior
- `lolilend/theme.py`: dynamic QSS generation
- `lolilend/general_settings.py`: settings, profiles, export
- `lolilend/telegram_proxy.py`: Telegram proxy service and config store
- `lolilend/discord_quests.py`: Discord quest tracker and play-quest completion service
- `lolilend/tg_ws_proxy_core.py`: embedded Telegram WS proxy core
- `LoliLend.spec`: portable one-file build
- `LoliLend.installer.spec`: onedir build for installer packaging
- `installer/LoliLend.iss`: Inno Setup installer script
- `.github/workflows/release-installer.yml`: CI release pipeline for installer publishing to GitHub Releases
- `THIRD_PARTY_NOTICES.md`: upstream attribution notices
- `lolilend/assets/docs/token_guide_ru.md`: built-in Discord Quest usage and safety guide (RU)

## Discord Quest notes

- Discord Quest v3 is tokenless and does not require OAuth/manual token input.
- The tab works in upstream-style mode:
  - fetches detectable game catalog (`mirror -> Discord endpoint -> bundled snapshot`),
  - allows adding games to local list,
  - creates/runs dummy executable for completion (`Install & Play` / `Play` / `Stop`),
  - includes experimental `Test RPC`.
- Local non-secret settings are stored in `%APPDATA%/LoliLend/discord_quest.json`.
