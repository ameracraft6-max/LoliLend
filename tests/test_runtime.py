from __future__ import annotations

import sys
import unittest

from lolilend.runtime import FPS_ELEVATION_FLAG, WindowsElevationManager, sanitize_argv


class _FakeShell32:
    def __init__(self, result: int = 42) -> None:
        self.result = result
        self.calls: list[tuple[object, ...]] = []

    def ShellExecuteW(self, hwnd, operation, executable, parameters, directory, show_mode):  # noqa: N802
        self.calls.append((hwnd, operation, executable, parameters, directory, show_mode))
        return self.result


class RuntimeHelpersTests(unittest.TestCase):
    def test_sanitize_argv_removes_internal_fps_flag(self) -> None:
        argv = ["main.py", "--demo", FPS_ELEVATION_FLAG]
        self.assertEqual(sanitize_argv(argv), ["main.py", "--demo"])

    def test_windows_elevation_manager_uses_runas_and_appends_flag(self) -> None:
        shell32 = _FakeShell32()
        manager = WindowsElevationManager(
            argv=["main.py", "--demo"],
            shell32=shell32,
            executable=sys.executable,
            working_directory="E:\\NEW GAMES",
        )

        ok, message = manager.relaunch_for_fps()
        self.assertTrue(ok)
        self.assertIn("administrator", message.lower())
        self.assertEqual(len(shell32.calls), 1)
        _, operation, executable, parameters, directory, show_mode = shell32.calls[0]
        self.assertEqual(operation, "runas")
        self.assertEqual(executable, sys.executable)
        self.assertIn("--demo", parameters)
        self.assertIn(FPS_ELEVATION_FLAG, parameters)
        self.assertEqual(directory, "E:\\NEW GAMES")
        self.assertEqual(show_mode, 1)

    def test_windows_elevation_manager_blocks_second_restart_attempt(self) -> None:
        manager = WindowsElevationManager(argv=["main.py", FPS_ELEVATION_FLAG])
        ok, message = manager.relaunch_for_fps()
        self.assertFalse(ok)
        self.assertIn("already attempted", message.lower())


if __name__ == "__main__":
    unittest.main()
