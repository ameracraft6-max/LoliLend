from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
import fnmatch
import os
from pathlib import Path
import re
import subprocess
from typing import Any, Callable

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
    url = f"https://api.github.com/repos/{repo}/releases"
    headers = {
        "Accept": "application/vnd.github+json",
        "User-Agent": "LoliLend-Launcher-Updater",
    }
    response = client.get(url, headers=headers, timeout=timeout)
    if response.status_code >= 400:
        raise UpdateError(f"GitHub API request failed with status {response.status_code}.")

    payload = response.json()
    if not isinstance(payload, list):
        raise UpdateError("GitHub API returned an unexpected payload.")
    return select_latest_release(payload, config)


def select_latest_release(releases_payload: list[dict[str, Any]], config: ReleaseConfig) -> ReleaseInfo | None:
    best: ReleaseInfo | None = None
    for release in releases_payload:
        if not isinstance(release, dict):
            continue
        if bool(release.get("draft", False)):
            continue
        if config.stable_only and bool(release.get("prerelease", False)):
            continue

        tag = str(release.get("tag_name") or release.get("name") or "").strip()
        version = normalize_version(tag)
        if parse_semver(version) is None:
            continue

        asset = _select_asset(release.get("assets"), config.asset_pattern)
        if asset is None:
            continue
        published_at = str(release.get("published_at") or "")
        info = ReleaseInfo(
            version=version,
            tag=tag,
            asset_name=asset["name"],
            asset_url=asset["url"],
            published_at=published_at,
        )
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
) -> Path:
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
    return destination


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
    script = build_install_and_relaunch_command(installer_path, relaunch_command)
    if not _is_windows():
        raise UpdateError("Silent installer launch is supported on Windows only.")
    creation_flags = 0
    detached = getattr(subprocess, "DETACHED_PROCESS", 0)
    new_group = getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
    creation_flags |= detached | new_group
    subprocess.Popen(
        ["cmd.exe", "/c", script],
        creationflags=creation_flags,
        close_fds=True,
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
