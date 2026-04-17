from __future__ import annotations

import hashlib
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
    is_game: bool = False  # displays 🎮 marker in UI


@dataclass(slots=True)
class CleanResult:
    freed_bytes: int = 0
    deleted_files: int = 0
    errors: int = 0


@dataclass(slots=True)
class DuplicateGroup:
    hash_digest: str
    size_bytes: int  # size of one file
    files: list[Path] = field(default_factory=list)

    @property
    def total_wasted_bytes(self) -> int:
        """Bytes that could be reclaimed: size × (count - 1)."""
        return self.size_bytes * max(0, len(self.files) - 1)


# Paths that must never be scanned for duplicates — deleting here bricks Windows.
DUPLICATE_SCAN_BLACKLIST: frozenset[str] = frozenset({
    "c:\\windows",
    "c:\\program files",
    "c:\\program files (x86)",
    "c:\\programdata",
    "c:\\$recycle.bin",
    "c:\\system volume information",
})


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


def _expand_glob_paths(path_patterns: list[str]) -> list[str]:
    """Expand glob-style paths (e.g. `.../webcache_*`) into concrete existing directories."""
    resolved: list[str] = []
    for pattern in path_patterns:
        if not pattern:
            continue
        if "*" in pattern or "?" in pattern:
            # Split at first glob char to find the anchor parent
            parts = Path(pattern).parts
            anchor_parts: list[str] = []
            for part in parts:
                if "*" in part or "?" in part:
                    break
                anchor_parts.append(part)
            if not anchor_parts:
                continue
            anchor = Path(*anchor_parts)
            if not anchor.is_dir():
                continue
            remainder = str(Path(*parts[len(anchor_parts):]))
            try:
                for match in anchor.glob(remainder):
                    if match.is_dir():
                        resolved.append(str(match))
            except (OSError, ValueError):
                continue
        else:
            if os.path.isdir(pattern):
                resolved.append(pattern)
    return resolved


def _get_clean_categories() -> list[CleanCategory]:
    """Build list of cleanable categories with their paths."""
    temp = os.environ.get("TEMP", "")
    localappdata = os.environ.get("LOCALAPPDATA", "")
    appdata = os.environ.get("APPDATA", "")
    programdata = os.environ.get("PROGRAMDATA", r"C:\ProgramData")
    pf_x86 = os.environ.get("ProgramFiles(x86)", r"C:\Program Files (x86)")

    categories = [
        # --- System ---
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
        # --- Game caches (checked=False by default — deleting active shader cache triggers rebuild) ---
        CleanCategory(
            id="steam_shader_cache",
            name="Steam shader cache",
            paths=[
                os.path.join(pf_x86, r"Steam\steamapps\shadercache"),
                os.path.join(pf_x86, r"Steam\appcache\httpcache"),
            ],
            checked=False,
            is_game=True,
        ),
        CleanCategory(
            id="epic_cache",
            name="Epic Games cache",
            paths=[
                os.path.join(localappdata, r"EpicGamesLauncher\Saved\Logs"),
                os.path.join(localappdata, r"EpicGamesLauncher\Saved\webcache_*"),
            ],
            checked=False,
            is_game=True,
        ),
        CleanCategory(
            id="nvidia_cache",
            name="NVIDIA shader cache",
            paths=[
                os.path.join(localappdata, r"NVIDIA\DXCache"),
                os.path.join(localappdata, r"NVIDIA\GLCache"),
                os.path.join(localappdata, r"NVIDIA Corporation\NV_Cache"),
            ],
            checked=False,
            is_game=True,
        ),
        CleanCategory(
            id="dx_shader_cache",
            name="DirectX shader cache",
            paths=[os.path.join(localappdata, r"D3DSCache")],
            checked=False,
            is_game=True,
        ),
        CleanCategory(
            id="discord_cache",
            name="Discord cache",
            paths=[
                os.path.join(appdata, r"discord\Cache"),
                os.path.join(appdata, r"discord\Code Cache"),
                os.path.join(appdata, r"discord\GPUCache"),
            ],
            checked=False,
            is_game=True,
        ),
        CleanCategory(
            id="battlenet_cache",
            name="Battle.net cache",
            paths=[
                os.path.join(programdata, r"Battle.net\Cache"),
                os.path.join(localappdata, r"Battle.net\Cache"),
            ],
            checked=False,
            is_game=True,
        ),
        CleanCategory(
            id="riot_logs",
            name="Riot Games logs",
            paths=[os.path.join(localappdata, r"Riot Games\League of Legends\Logs")],
            checked=False,
            is_game=True,
        ),
    ]
    # Resolve globs and filter to existing paths
    for cat in categories:
        cat.paths = _expand_glob_paths(cat.paths)
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


def list_category_files(paths: list[str], max_items: int = 200) -> list[tuple[str, int, float]]:
    """List top-level entries of the given category paths as (display_path, size_bytes, mtime).

    Files are returned directly; directories are summarized as a single entry with aggregate size.
    Sorted by size descending, capped at max_items.
    """
    items: list[tuple[str, int, float]] = []
    for root in paths:
        try:
            for entry in os.scandir(root):
                try:
                    if entry.is_file(follow_symlinks=False):
                        stat = entry.stat(follow_symlinks=False)
                        items.append((entry.path, stat.st_size, stat.st_mtime))
                    elif entry.is_dir(follow_symlinks=False):
                        size, _count = _dir_size(entry.path)
                        stat = entry.stat(follow_symlinks=False)
                        items.append((entry.path + os.sep, size, stat.st_mtime))
                except (PermissionError, OSError):
                    continue
        except (PermissionError, OSError):
            continue
    items.sort(key=lambda t: t[1], reverse=True)
    return items[:max_items]


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


# --------- Duplicate finder ---------

def _is_blacklisted_root(path: Path) -> bool:
    """Guard against scanning system directories for duplicates."""
    try:
        resolved = str(path.resolve()).lower().rstrip("\\/")
    except OSError:
        return True
    for forbidden in DUPLICATE_SCAN_BLACKLIST:
        if resolved == forbidden or resolved.startswith(forbidden + "\\"):
            return True
    return False


def _hash_file(path: Path, chunk_size: int = 65536) -> str | None:
    """MD5 of file content. MD5 is fine here: this is deduplication, not a security check."""
    try:
        hasher = hashlib.md5()
        with path.open("rb") as fh:
            while True:
                chunk = fh.read(chunk_size)
                if not chunk:
                    break
                hasher.update(chunk)
        return hasher.hexdigest()
    except (OSError, PermissionError):
        return None


def find_duplicates(
    root: Path,
    min_size_bytes: int = 1024 * 1024,
    progress: Callable[[int, int], None] | None = None,
    cancel_check: Callable[[], bool] | None = None,
) -> list[DuplicateGroup]:
    """Two-phase duplicate search: group files by size, then hash only candidates.

    Skips files smaller than min_size_bytes to keep runtime reasonable.
    Returns groups with 2+ matching files, sorted by reclaimable space descending.
    """
    root = Path(root)
    if _is_blacklisted_root(root):
        raise ValueError(f"Сканирование системных путей запрещено: {root}")

    def _cancelled() -> bool:
        return cancel_check is not None and cancel_check()

    # Phase 1: group by size
    by_size: dict[int, list[Path]] = {}
    for dirpath, _dirnames, filenames in os.walk(root):
        if _cancelled():
            return []
        for name in filenames:
            p = Path(dirpath) / name
            try:
                size = p.stat().st_size
            except (OSError, PermissionError):
                continue
            if size < min_size_bytes:
                continue
            by_size.setdefault(size, []).append(p)

    # Phase 2: hash same-size groups
    candidates = [files for files in by_size.values() if len(files) >= 2]
    total_to_hash = sum(len(files) for files in candidates)
    hashed = 0
    groups_by_hash: dict[str, DuplicateGroup] = {}

    for files in candidates:
        if _cancelled():
            return []
        for p in files:
            if _cancelled():
                return []
            digest = _hash_file(p)
            hashed += 1
            if progress and total_to_hash > 0:
                progress(hashed, total_to_hash)
            if digest is None:
                continue
            try:
                size = p.stat().st_size
            except OSError:
                continue
            group = groups_by_hash.get(digest)
            if group is None:
                groups_by_hash[digest] = DuplicateGroup(hash_digest=digest, size_bytes=size, files=[p])
            else:
                group.files.append(p)

    duplicates = [g for g in groups_by_hash.values() if len(g.files) >= 2]
    duplicates.sort(key=lambda g: g.total_wasted_bytes, reverse=True)
    return duplicates


def delete_duplicates(groups: list[DuplicateGroup], keep_strategy: str = "keep_oldest") -> CleanResult:
    """Delete all-but-one file in each group according to keep_strategy.

    Strategies:
        - "keep_oldest" : keeps the file with the smallest mtime
        - "keep_newest" : keeps the file with the largest mtime
        - "keep_first"  : keeps files[0] (insertion order)
    """
    result = CleanResult()
    for group in groups:
        if len(group.files) < 2:
            continue
        try:
            if keep_strategy == "keep_newest":
                kept = max(group.files, key=lambda p: p.stat().st_mtime)
            elif keep_strategy == "keep_first":
                kept = group.files[0]
            else:  # keep_oldest (default)
                kept = min(group.files, key=lambda p: p.stat().st_mtime)
        except OSError:
            result.errors += 1
            continue
        for p in group.files:
            if p == kept:
                continue
            try:
                size = p.stat().st_size
                p.unlink()
                result.freed_bytes += size
                result.deleted_files += 1
            except (OSError, PermissionError):
                result.errors += 1
    return result


class SystemCleanerService:
    """Threaded scanner/cleaner for categories + duplicate search."""

    def __init__(self) -> None:
        self._thread: threading.Thread | None = None
        self._categories: list[CleanCategory] = []
        self._result: CleanResult | None = None
        self._duplicates: list[DuplicateGroup] = []
        self._progress: tuple[int, int] = (0, 0)
        self._running = False
        self._mode = ""  # "scan" / "clean" / "scan_dupes" / "delete_dupes"
        self._cancel_event = threading.Event()
        self._last_error: str = ""

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
    def duplicates(self) -> list[DuplicateGroup]:
        return self._duplicates

    @property
    def result(self) -> CleanResult | None:
        return self._result

    @property
    def last_error(self) -> str:
        return self._last_error

    def cancel(self) -> None:
        self._cancel_event.set()

    def start_scan(self) -> None:
        if self._running:
            return
        self._running = True
        self._mode = "scan"
        self._categories = []
        self._result = None
        self._last_error = ""
        self._cancel_event.clear()

        def _worker() -> None:
            try:
                self._categories = scan_categories()
            except Exception as exc:  # noqa: BLE001
                self._last_error = f"Ошибка сканирования: {exc}"
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
        self._last_error = ""

        def _worker() -> None:
            try:
                self._result = clean_categories(categories, self._on_progress)
            except Exception as exc:  # noqa: BLE001
                self._last_error = f"Ошибка очистки: {exc}"
            finally:
                self._running = False

        self._thread = threading.Thread(target=_worker, daemon=True)
        self._thread.start()

    def start_duplicate_scan(self, root: Path, min_size_bytes: int) -> None:
        if self._running:
            return
        self._running = True
        self._mode = "scan_dupes"
        self._duplicates = []
        self._progress = (0, 0)
        self._last_error = ""
        self._cancel_event.clear()

        def _worker() -> None:
            try:
                self._duplicates = find_duplicates(
                    root,
                    min_size_bytes=min_size_bytes,
                    progress=self._on_progress,
                    cancel_check=self._cancel_event.is_set,
                )
            except ValueError as exc:
                self._last_error = str(exc)
            except Exception as exc:  # noqa: BLE001
                self._last_error = f"Ошибка поиска дубликатов: {exc}"
            finally:
                self._running = False

        self._thread = threading.Thread(target=_worker, daemon=True)
        self._thread.start()

    def start_duplicate_delete(self, groups: list[DuplicateGroup], keep_strategy: str) -> None:
        if self._running:
            return
        self._running = True
        self._mode = "delete_dupes"
        self._result = None
        self._last_error = ""

        def _worker() -> None:
            try:
                self._result = delete_duplicates(groups, keep_strategy)
            except Exception as exc:  # noqa: BLE001
                self._last_error = f"Ошибка удаления дубликатов: {exc}"
            finally:
                self._running = False

        self._thread = threading.Thread(target=_worker, daemon=True)
        self._thread.start()

    def _on_progress(self, current: int, total: int) -> None:
        self._progress = (current, total)
