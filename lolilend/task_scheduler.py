from __future__ import annotations

import csv
import io
import os
import subprocess
from dataclasses import dataclass

_NO_WINDOW = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0


@dataclass(slots=True)
class ScheduledTask:
    name: str
    path: str
    status: str
    next_run: str
    last_run: str
    author: str


class TaskSchedulerService:
    def load_tasks(self) -> list[ScheduledTask]:
        if os.name != "nt":
            return []
        try:
            result = subprocess.run(
                ["schtasks", "/query", "/fo", "CSV", "/v"],
                capture_output=True,
                text=True,
                timeout=15,
                encoding="utf-8",
                errors="replace",
                creationflags=_NO_WINDOW,
            )
        except Exception:
            return []

        if result.returncode not in (0, 1):
            return []

        return self._parse_csv(result.stdout)

    def enable_task(self, task: ScheduledTask) -> tuple[bool, str]:
        return self._schtasks("/change", task.path, "/enable")

    def disable_task(self, task: ScheduledTask) -> tuple[bool, str]:
        return self._schtasks("/change", task.path, "/disable")

    def run_task(self, task: ScheduledTask) -> tuple[bool, str]:
        return self._schtasks("/run", task.path)

    def delete_task(self, task: ScheduledTask) -> tuple[bool, str]:
        return self._schtasks("/delete", task.path, "/f")

    def close(self) -> None:
        pass

    # --- private ---

    def _schtasks(self, command: str, task_path: str, *extra: str) -> tuple[bool, str]:
        if os.name != "nt":
            return False, "Только Windows"
        try:
            args = ["schtasks", command, "/tn", task_path, *extra]
            result = subprocess.run(
                args,
                capture_output=True,
                text=True,
                timeout=10,
                encoding="utf-8",
                errors="replace",
                creationflags=_NO_WINDOW,
            )
            if result.returncode == 0:
                return True, f"OK: {task_path}"
            stderr = result.stderr.strip() or result.stdout.strip()
            if "доступ" in stderr.lower() or "access" in stderr.lower():
                return False, "Требуются права администратора"
            return False, stderr or f"Ошибка {result.returncode}"
        except subprocess.TimeoutExpired:
            return False, "Таймаут операции"
        except Exception as e:
            return False, str(e)

    @staticmethod
    def _parse_csv(output: str) -> list[ScheduledTask]:
        tasks: list[ScheduledTask] = []
        seen: set[str] = set()

        # schtasks /fo CSV /v can output multiple CSV blocks separated by empty lines.
        # We parse each non-empty block independently.
        blocks = _split_blocks(output)
        for block in blocks:
            reader = csv.DictReader(io.StringIO(block))
            for row in reader:
                name = _col(row, "TaskName", "HostName") or ""
                name = name.strip().strip('"')
                if not name or name in ("TaskName", "HostName", ""):
                    continue
                if name in seen:
                    continue
                seen.add(name)

                path = _col(row, "Task To Run", "TaskToRun") or name
                status = _col(row, "Status", "Статус") or "Unknown"
                next_run = _col(row, "Next Run Time", "Следующий запуск") or "N/A"
                last_run = _col(row, "Last Run Time", "Последний запуск") or "N/A"
                author = _col(row, "Author", "Автор") or "—"

                tasks.append(ScheduledTask(
                    name=name,
                    path=name,  # use name as the /tn argument
                    status=status.strip(),
                    next_run=next_run.strip(),
                    last_run=last_run.strip(),
                    author=author.strip(),
                ))

        return tasks


def _split_blocks(output: str) -> list[str]:
    """Split schtasks CSV output into blocks (separated by blank lines)."""
    blocks: list[str] = []
    current: list[str] = []
    for line in output.splitlines():
        if line.strip():
            current.append(line)
        else:
            if current:
                blocks.append("\n".join(current))
                current = []
    if current:
        blocks.append("\n".join(current))
    return blocks


def _col(row: dict[str, str], *keys: str) -> str | None:
    for key in keys:
        val = row.get(key)
        if val is not None:
            return val.strip().strip('"')
    return None
