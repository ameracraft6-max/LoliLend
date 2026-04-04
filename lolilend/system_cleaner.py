from __future__ import annotations

import logging
import os
import shutil
import threading
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

_log = logging.getLogger(__name__)


@dataclass(slots=True)
class CleanCategory:
    id: str
    name: str
    paths: list[str]
    size_bytes: int = 0
    file_count: int = 0
    checked: bool = True


@dataclass(slots=True)
class CleanResult:
    freed_bytes: int = 0
    deleted_files: int = 0
    errors: int = 0


def _dir_size(path: str) -> tuple[int, int]:
    """Return (total_bytes, file_count) for a directory."""
    total = 0
    count = 0
    try:
        for entry in os.scandir(path):
            try:
                if entry.is_file(follow_symlinks=False):
                    total += entry.stat(follow_symlinks=False).st_size
                    count += 1
                elif entry.is_dir(follow_symlinks=False):
                    sub_total, sub_count = _dir_size(entry.path)
                    total += sub_total
                    count += sub_count
            except (PermissionError, OSError):
                continue
    except (PermissionError, OSError):
        pass
    return total, count


def _get_clean_categories() -> list[CleanCategory]:
    """Build list of cleanable categories with their paths."""
    temp = os.environ.get("TEMP", "")
    localappdata = os.environ.get("LOCALAPPDATA", "")
    appdata = os.environ.get("APPDATA", "")

    categories = [
        CleanCategory(
            id="windows_temp",
            name="Windows Temp",
            paths=[temp, r"C:\Windows\Temp"],
        ),
        CleanCategory(
            id="browser_cache",
            name="Kэш браузеров",
            paths=[
                os.path.join(localappdata, r"Google\Chrome\User Data\Default\Cache"),
                os.path.join(localappdata, r"Google\Chrome\User Data\Default\Code Cache"),
                os.path.join(localappdata, r"Microsoft\Edge\User Data\Default\Cache"),
                os.path.join(localappdata, r"Microsoft\Edge\User Data\Default\Code Cache"),
                os.path.join(appdata, r"Mozilla\Firefox\Profiles"),
            ],
        ),
        CleanCategory(
            id="recycle_bin",
            name="Корзина",
            paths=[r"C:\$Recycle.Bin"],
            checked=False,
        ),
        CleanCategory(
            id="windows_logs",
            name="Логи Windows",
            paths=[r"C:\Windows\Logs", r"C:\Windows\Panther"],
        ),
        CleanCategory(
            id="update_cache",
            name="Кэш обновлений",
            paths=[r"C:\Windows\SoftwareDistribution\Download"],
        ),
        CleanCategory(
            id="thumbnails",
            name="Thumbnails",
            paths=[os.path.join(localappdata, r"Microsoft\Windows\Explorer")],
        ),
        CleanCategory(
            id="prefetch",
            name="Prefetch",
            paths=[r"C:\Windows\Prefetch"],
            checked=False,
        ),
    ]
    # Filter to only paths that exist
    for cat in categories:
        cat.paths = [p for p in cat.paths if os.path.isdir(p)]
    return [c for c in categories if c.paths]


def scan_categories() -> list[CleanCategory]:
    """Scan all categories and calculate sizes."""
    categories = _get_clean_categories()
    for cat in categories:
        total_size = 0
        total_count = 0
        for path in cat.paths:
            size, count = _dir_size(path)
            total_size += size
            total_count += count
        cat.size_bytes = total_size
        cat.file_count = total_count
    return categories


def clean_categories(
    categories: list[CleanCategory],
    progress: Callable[[int, int], None] | None = None,
) -> CleanResult:
    """Delete files in checked categories."""
    result = CleanResult()
    total = sum(c.file_count for c in categories if c.checked)
    done = 0

    for cat in categories:
        if not cat.checked:
            continue
        for dir_path in cat.paths:
            try:
                for entry in os.scandir(dir_path):
                    try:
                        if entry.is_file(follow_symlinks=False):
                            size = entry.stat(follow_symlinks=False).st_size
                            os.unlink(entry.path)
                            result.freed_bytes += size
                            result.deleted_files += 1
                        elif entry.is_dir(follow_symlinks=False):
                            size, count = _dir_size(entry.path)
                            shutil.rmtree(entry.path, ignore_errors=True)
                            result.freed_bytes += size
                            result.deleted_files += count
                    except (PermissionError, OSError):
                        result.errors += 1
                    done += 1
                    if progress and total > 0:
                        progress(done, total)
            except (PermissionError, OSError):
                continue

    return result


def format_size(size_bytes: int) -> str:
    """Human-readable file size."""
    if size_bytes < 1024:
        return f"{size_bytes} B"
    if size_bytes < 1024 * 1024:
        return f"{size_bytes / 1024:.1f} KB"
    if size_bytes < 1024 * 1024 * 1024:
        return f"{size_bytes / (1024 * 1024):.1f} MB"
    return f"{size_bytes / (1024 * 1024 * 1024):.2f} GB"


class SystemCleanerService:
    """Threaded scanner/cleaner."""

    def __init__(self) -> None:
        self._thread: threading.Thread | None = None
        self._categories: list[CleanCategory] = []
        self._result: CleanResult | None = None
        self._progress: tuple[int, int] = (0, 0)
        self._running = False
        self._mode = ""  # "scan" or "clean"

    @property
    def running(self) -> bool:
        return self._running

    @property
    def mode(self) -> str:
        return self._mode

    @property
    def progress(self) -> tuple[int, int]:
        return self._progress

    @property
    def categories(self) -> list[CleanCategory]:
        return self._categories

    @property
    def result(self) -> CleanResult | None:
        return self._result

    def start_scan(self) -> None:
        if self._running:
            return
        self._running = True
        self._mode = "scan"
        self._categories = []
        self._result = None

        def _worker() -> None:
            try:
                self._categories = scan_categories()
            finally:
                self._running = False

        self._thread = threading.Thread(target=_worker, daemon=True)
        self._thread.start()

    def start_clean(self, categories: list[CleanCategory]) -> None:
        if self._running:
            return
        self._running = True
        self._mode = "clean"
        self._result = None
        self._progress = (0, 0)

        def _worker() -> None:
            try:
                self._result = clean_categories(categories, self._on_progress)
            finally:
                self._running = False

        self._thread = threading.Thread(target=_worker, daemon=True)
        self._thread.start()

    def _on_progress(self, current: int, total: int) -> None:
        self._progress = (current, total)
