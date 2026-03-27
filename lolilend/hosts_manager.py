from __future__ import annotations

import os
import re
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path


_HOSTS_PATH = Path(r"C:\Windows\System32\drivers\etc\hosts")
_APPDATA_DIR = Path(os.getenv("APPDATA", str(Path.home()))) / "LoliLend"

# Common ad/tracking domains to block
COMMON_ADBLOCK_ENTRIES: list[tuple[str, str]] = [
    ("0.0.0.0", "ads.google.com"),
    ("0.0.0.0", "doubleclick.net"),
    ("0.0.0.0", "googleadservices.com"),
    ("0.0.0.0", "googlesyndication.com"),
    ("0.0.0.0", "adservice.google.com"),
    ("0.0.0.0", "pagead2.googlesyndication.com"),
    ("0.0.0.0", "ads.youtube.com"),
    ("0.0.0.0", "mc.yandex.ru"),
    ("0.0.0.0", "counter.yadro.ru"),
    ("0.0.0.0", "ads.vk.com"),
    ("0.0.0.0", "top-fwz1.mail.ru"),
    ("0.0.0.0", "stats.g.doubleclick.net"),
]

_IP_RE = re.compile(
    r"^(\d{1,3}\.){3}\d{1,3}$"          # IPv4
    r"|^([0-9a-fA-F]{0,4}:){2,7}[0-9a-fA-F]{0,4}$"  # IPv6 simplified
)


@dataclass(slots=True)
class HostEntry:
    ip: str
    hostname: str
    comment: str
    enabled: bool


class HostsManagerService:
    def load_entries(self) -> list[HostEntry]:
        if not _HOSTS_PATH.exists():
            return []
        try:
            text = _HOSTS_PATH.read_text(encoding="utf-8", errors="replace")
        except OSError:
            return []
        return _parse_hosts(text)

    def save_entries(self, entries: list[HostEntry]) -> tuple[bool, str]:
        text = _render_hosts(entries)
        try:
            _HOSTS_PATH.write_text(text, encoding="utf-8")
            return True, "Файл hosts сохранён"
        except PermissionError:
            return False, "Нет доступа. Запустите приложение от имени администратора"
        except OSError as e:
            return False, f"Ошибка записи: {e}"

    def backup(self, entries: list[HostEntry]) -> tuple[bool, Path]:
        try:
            _APPDATA_DIR.mkdir(parents=True, exist_ok=True)
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            path = _APPDATA_DIR / f"hosts_backup_{timestamp}.txt"
            path.write_text(_render_hosts(entries), encoding="utf-8")
            return True, path
        except OSError as e:
            return False, Path(str(e))

    def add_adblock_presets(self, entries: list[HostEntry]) -> list[HostEntry]:
        existing = {e.hostname for e in entries}
        for ip, hostname in COMMON_ADBLOCK_ENTRIES:
            if hostname not in existing:
                entries.append(HostEntry(ip=ip, hostname=hostname, comment="AdBlock preset", enabled=True))
        return entries

    def close(self) -> None:
        pass


def _looks_like_ip(token: str) -> bool:
    return bool(_IP_RE.match(token))


def _parse_hosts(text: str) -> list[HostEntry]:
    entries: list[HostEntry] = []
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line:
            continue

        enabled = not line.startswith("#")
        working = line.lstrip("#").strip()

        # Strip inline comment
        inline_comment = ""
        if "#" in working:
            parts = working.split("#", 1)
            working = parts[0].strip()
            inline_comment = parts[1].strip()

        tokens = working.split()
        if len(tokens) < 2:
            continue
        ip = tokens[0]
        hostname = tokens[1]

        # Skip lines that don't look like host entries (pure comment blocks)
        if not _looks_like_ip(ip):
            continue

        entries.append(HostEntry(ip=ip, hostname=hostname, comment=inline_comment, enabled=enabled))

    return entries


def _render_hosts(entries: list[HostEntry]) -> str:
    lines = ["# Hosts file managed by LoliLend", "# " + datetime.now().strftime("%Y-%m-%d %H:%M:%S"), ""]
    for e in entries:
        prefix = "" if e.enabled else "# "
        comment_part = f"  # {e.comment}" if e.comment else ""
        lines.append(f"{prefix}{e.ip}\t{e.hostname}{comment_part}")
    return "\n".join(lines) + "\n"
