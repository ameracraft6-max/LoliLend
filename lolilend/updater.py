from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
import fnmatch
import html
import os
from pathlib import Path
import re
import subprocess
import time
from typing import Any, Callable
from urllib.parse import unquote

import requests


_SEMVER_RE = re.compile(r"^[vV]?(\d+)\.(\d+)\.(\d+)(?:[-+]([0-9A-Za-z.\-]+))?$")
_SEMVER_FALLBACK_RE = re.compile(r"(\d+)\.(\d+)\.(\d+)")


class UpdateError(RuntimeError):
    """Raised when update operations fail."""


class UpdateState(str, Enum):
    CHECKING = "checking"
    UP_TO_DATE = "up_to_date"
    DOWNLOADING = "downloading"
    INSTALLING = "installing"
    FAILED = "failed"


@dataclass(slots=True)
class ReleaseConfig:
    repo: str
    asset_pattern: str
    stable_only: bool = True


@dataclass(slots=True)
class ReleaseInfo:
    version: str
    tag: str
    asset_name: str
    asset_url: str
    published_at: str


def parse_semver(value: str) -> tuple[int, int, int, tuple[str, ...]] | None:
    raw = value.strip()
    match = _SEMVER_RE.match(raw)
    if not match:
        fallback = _SEMVER_FALLBACK_RE.search(raw)
        if not fallback:
            return None
        major, minor, patch = fallback.groups()
        return int(major), int(minor), int(patch), ()
    major, minor, patch, prerelease = match.groups()
    pre_parts = tuple(part for part in (prerelease or "").split(".") if part)
    return int(major), int(minor), int(patch), pre_parts


def normalize_version(value: str) -> str:
    parsed = parse_semver(value)
    if parsed is None:
        return value.strip().lstrip("vV")
    major, minor, patch, prerelease = parsed
    suffix = f"-{'.'.join(prerelease)}" if prerelease else ""
    return f"{major}.{minor}.{patch}{suffix}"


def is_newer_version(candidate: str, current: str) -> bool:
    candidate_parsed = parse_semver(candidate)
    current_parsed = parse_semver(current)
    if candidate_parsed is None or current_parsed is None:
        return normalize_version(candidate) != normalize_version(current)
    return _semver_key(candidate_parsed) > _semver_key(current_parsed)


def fetch_latest_release(
    config: ReleaseConfig,
    *,
    session: requests.Session | None = None,
    timeout: float = 20.0,
) -> ReleaseInfo | None:
    repo = _sanitize_repo(config.repo)
    if not repo:
        raise UpdateError("GitHub repo is not configured.")

    client = session or requests
    headers = _github_api_headers()

    if config.stable_only:
        api_url = f"https://api.github.com/repos/{repo}/releases/latest"
        response = client.get(api_url, headers=headers, timeout=timeout)
        if response.status_code == 200:
            payload = response.json()
            if not isinstance(payload, dict):
                raise UpdateError("GitHub API returned an unexpected payload.")
            return _release_from_payload(payload, config)
        if response.status_code == 404:
            return None
        if response.status_code == 403:
            fallback = _fetch_latest_release_via_web(repo, config, client=client, timeout=timeout)
            if fallback is not None:
                return fallback
            raise UpdateError("GitHub API request failed with status 403.")
        raise UpdateError(f"GitHub API request failed with status {response.status_code}.")

    api_url = f"https://api.github.com/repos/{repo}/releases"
    response = client.get(api_url, headers=headers, timeout=timeout)
    if response.status_code == 403:
        fallback = _fetch_latest_release_via_web(repo, config, client=client, timeout=timeout)
        if fallback is not None:
            return fallback
    if response.status_code >= 400:
        raise UpdateError(f"GitHub API request failed with status {response.status_code}.")

    payload = response.json()
    if not isinstance(payload, list):
        raise UpdateError("GitHub API returned an unexpected payload.")
    return select_latest_release(payload, config)


def select_latest_release(releases_payload: list[dict[str, Any]], config: ReleaseConfig) -> ReleaseInfo | None:
    best: ReleaseInfo | None = None
    for release in releases_payload:
        info = _release_from_payload(release, config)
        if info is None:
            continue
        if best is None or is_newer_version(info.version, best.version):
            best = info
    return best


def download_release_asset(
    release: ReleaseInfo,
    destination: Path,
    *,
    progress: Callable[[int, int | None], None] | None = None,
    session: requests.Session | None = None,
    timeout: float = 30.0,
    max_retries: int = 3,
) -> Path:
    last_exc: Exception | None = None
    for attempt in range(1, max_retries + 1):
        try:
            _download_once(release, destination, progress=progress, session=session, timeout=timeout)
            break
        except (requests.RequestException, OSError, UpdateError) as exc:
            last_exc = exc
            if attempt < max_retries:
                time.sleep(2.0)
    else:
        raise UpdateError(f"Download failed after {max_retries} attempts: {last_exc}")

    if not destination.exists() or destination.stat().st_size == 0:
        destination.unlink(missing_ok=True)
        raise UpdateError("Downloaded file is empty or missing.")

    return destination


def _download_once(
    release: ReleaseInfo,
    destination: Path,
    *,
    progress: Callable[[int, int | None], None] | None,
    session: requests.Session | None,
    timeout: float,
) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    client = session or requests
    response = client.get(release.asset_url, stream=True, timeout=timeout)
    if response.status_code >= 400:
        raise UpdateError(f"Failed to download asset: HTTP {response.status_code}.")

    total_bytes: int | None = None
    raw_total = response.headers.get("Content-Length")
    if raw_total and raw_total.isdigit():
        total_bytes = int(raw_total)

    downloaded = 0
    with destination.open("wb") as target:
        for chunk in response.iter_content(chunk_size=1024 * 128):
            if not chunk:
                continue
            target.write(chunk)
            downloaded += len(chunk)
            if progress is not None:
                progress(downloaded, total_bytes)


def build_silent_install_command(installer_path: Path) -> list[str]:
    return [
        str(installer_path),
        "/VERYSILENT",
        "/SUPPRESSMSGBOXES",
        "/NORESTART",
        "/SP-",
    ]


def build_install_and_relaunch_command(installer_path: Path, relaunch_command: str) -> str:
    silent = " ".join(_quote(item) for item in build_silent_install_command(installer_path))
    return f"{silent} && timeout /t 2 /nobreak >nul && set \"PYINSTALLER_RESET_ENVIRONMENT=1\" && start \"\" {relaunch_command}"


def spawn_install_and_relaunch(installer_path: Path, relaunch_command: str) -> None:
    if not _is_windows():
        raise UpdateError("Silent installer launch is supported on Windows only.")

    # Pre-flight: verify the downloaded file before closing the launcher
    if not installer_path.exists():
        raise UpdateError(f"Installer not found: {installer_path}")
    if installer_path.stat().st_size == 0:
        raise UpdateError("Installer file is empty.")

    # Write a .bat file — avoids list2cmdline vs cmd.exe quoting incompatibility.
    # When passing a list to Popen, Python escapes " as \" which cmd.exe does NOT understand:
    # it strips the outer quotes then sees \"C:\... and misparses the entire command.
    bat_path = installer_path.parent / "_lolilend_update.bat"
    bat_lines = "\r\n".join([
        "@echo off",
        f'"{installer_path}" /VERYSILENT /SUPPRESSMSGBOXES /NORESTART /SP-',
        "timeout /t 3 /nobreak >nul",
        f'start "" {relaunch_command}',
        "",
    ])
    # mbcs = Windows ANSI code page (CP1251 on Russian Windows) so cmd.exe reads paths correctly
    bat_path.write_text(bat_lines, encoding="mbcs", errors="replace")

    # CREATE_NO_WINDOW: no visible console window
    # CREATE_NEW_PROCESS_GROUP: process survives launcher exit
    # Pass as STRING (not list) to bypass list2cmdline and avoid " escaping issues.
    # Double-outer-quote handles bat paths with spaces:
    #   cmd /c ""path with spaces.bat"" → cmd strips outermost → "path with spaces.bat" ✓
    creation_flags = (
        getattr(subprocess, "CREATE_NO_WINDOW", 0x08000000)
        | getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0x00000200)
    )
    bat_str = str(bat_path)
    subprocess.Popen(
        f'cmd.exe /c ""{bat_str}""',
        creationflags=creation_flags,
        close_fds=True,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )


def terminate_processes_by_name(process_name: str, *, skip_pid: int | None = None) -> int:
    try:
        import psutil
    except Exception:
        return 0

    name_norm = process_name.strip().lower()
    if not name_norm:
        return 0

    terminated: list[Any] = []
    for process in psutil.process_iter(["pid", "name"]):
        try:
            pid = int(process.info.get("pid", 0))
            if skip_pid is not None and pid == skip_pid:
                continue
            name = str(process.info.get("name") or "").lower()
            if name != name_norm:
                continue
            process.terminate()
            terminated.append(process)
        except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
            continue
    if terminated:
        psutil.wait_procs(terminated, timeout=3.0)
    return len(terminated)


def _select_asset(assets_payload: Any, pattern: str) -> dict[str, str] | None:
    if not isinstance(assets_payload, list):
        return None
    for asset in assets_payload:
        if not isinstance(asset, dict):
            continue
        name = str(asset.get("name") or "").strip()
        if not name:
            continue
        if not fnmatch.fnmatch(name, pattern):
            continue
        url = str(asset.get("browser_download_url") or "").strip()
        if not url:
            continue
        return {"name": name, "url": url}
    return None


def _release_from_payload(release_payload: Any, config: ReleaseConfig) -> ReleaseInfo | None:
    if not isinstance(release_payload, dict):
        return None
    if bool(release_payload.get("draft", False)):
        return None
    if config.stable_only and bool(release_payload.get("prerelease", False)):
        return None

    tag = str(release_payload.get("tag_name") or release_payload.get("name") or "").strip()
    version = normalize_version(tag)
    if parse_semver(version) is None:
        return None

    asset = _select_asset(release_payload.get("assets"), config.asset_pattern)
    if asset is None:
        return None
    published_at = str(release_payload.get("published_at") or "")
    return ReleaseInfo(
        version=version,
        tag=tag,
        asset_name=asset["name"],
        asset_url=asset["url"],
        published_at=published_at,
    )


def _fetch_latest_release_via_web(
    repo: str,
    config: ReleaseConfig,
    *,
    client: requests.Session | Any,
    timeout: float,
) -> ReleaseInfo | None:
    headers = {"User-Agent": "LoliLend-Launcher-Updater"}
    latest_url = f"https://github.com/{repo}/releases/latest"
    latest_response = client.get(latest_url, headers=headers, timeout=timeout, allow_redirects=True)
    if latest_response.status_code >= 400:
        return None

    tag = _extract_tag_from_url(str(getattr(latest_response, "url", "")).strip())
    if not tag:
        return None
    version = normalize_version(tag)
    if parse_semver(version) is None:
        return None

    expanded_assets_url = f"https://github.com/{repo}/releases/expanded_assets/{tag}"
    assets_response = client.get(expanded_assets_url, headers=headers, timeout=timeout)
    assets_html = ""
    if assets_response.status_code < 400:
        assets_html = str(getattr(assets_response, "text", ""))
    if not assets_html:
        assets_html = str(getattr(latest_response, "text", ""))

    asset = _select_asset_from_html(assets_html, config.asset_pattern)
    if asset is None:
        return None

    return ReleaseInfo(
        version=version,
        tag=tag,
        asset_name=asset["name"],
        asset_url=asset["url"],
        published_at="",
    )


def _extract_tag_from_url(url: str) -> str:
    marker = "/releases/tag/"
    idx = url.find(marker)
    if idx < 0:
        return ""
    return url[idx + len(marker) :].strip().strip("/")


def _select_asset_from_html(page_html: str, pattern: str) -> dict[str, str] | None:
    matches = re.finditer(
        r'href="(?P<href>/[^"#?]+/releases/download/[^"#?]+/(?P<name>[^"#?]+))"',
        page_html,
        flags=re.IGNORECASE,
    )
    for match in matches:
        href = html.unescape(match.group("href"))
        encoded_name = match.group("name")
        asset_name = unquote(encoded_name)
        if not fnmatch.fnmatch(asset_name, pattern):
            continue
        return {"name": asset_name, "url": f"https://github.com{href}"}
    return None


def _github_api_headers() -> dict[str, str]:
    headers = {
        "Accept": "application/vnd.github+json",
        "User-Agent": "LoliLend-Launcher-Updater",
    }
    token = os.getenv("LOLILEND_GITHUB_TOKEN", "").strip() or os.getenv("GITHUB_TOKEN", "").strip()
    if token:
        headers["Authorization"] = f"Bearer {token}"
    return headers


def _sanitize_repo(value: str) -> str:
    raw = value.strip().strip("/")
    if "/" not in raw:
        return ""
    owner, name = raw.split("/", 1)
    owner = owner.strip()
    name = name.strip()
    if not owner or not name:
        return ""
    return f"{owner}/{name}"


def _quote(value: str) -> str:
    escaped = value.replace('"', '""')
    return f'"{escaped}"'


def _semver_key(parsed: tuple[int, int, int, tuple[str, ...]]) -> tuple[int, int, int, int, tuple[str, ...]]:
    major, minor, patch, prerelease = parsed
    # Stable (no prerelease) should sort above prerelease for the same numbers.
    stability_weight = 1 if not prerelease else 0
    return major, minor, patch, stability_weight, prerelease


def _is_windows() -> bool:
    return os.name == "nt"
