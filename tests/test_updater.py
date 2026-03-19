from __future__ import annotations

from pathlib import Path
import unittest

from lolilend.updater import (
    ReleaseConfig,
    build_install_and_relaunch_command,
    build_silent_install_command,
    is_newer_version,
    parse_semver,
    select_latest_release,
)


class UpdaterHelpersTests(unittest.TestCase):
    def test_parse_semver_supports_v_prefix(self) -> None:
        self.assertEqual(parse_semver("v2.4.1"), (2, 4, 1, ()))
        self.assertEqual(parse_semver("2.4.1-beta.1"), (2, 4, 1, ("beta", "1")))

    def test_is_newer_version_compares_semver(self) -> None:
        self.assertTrue(is_newer_version("2.1.0", "2.0.9"))
        self.assertFalse(is_newer_version("2.0.0", "2.0.0"))
        self.assertFalse(is_newer_version("2.0.0-beta.1", "2.0.0"))

    def test_select_latest_release_filters_stable_and_asset_pattern(self) -> None:
        payload = [
            {
                "tag_name": "v2.3.0-beta.1",
                "draft": False,
                "prerelease": True,
                "assets": [{"name": "LoliLend-Setup-2.3.0-beta.1.exe", "browser_download_url": "https://example/prerelease.exe"}],
                "published_at": "2026-03-10T12:00:00Z",
            },
            {
                "tag_name": "v2.2.0",
                "draft": False,
                "prerelease": False,
                "assets": [{"name": "LoliLend-Setup-2.2.0.exe", "browser_download_url": "https://example/stable220.exe"}],
                "published_at": "2026-03-11T12:00:00Z",
            },
            {
                "tag_name": "v2.1.9",
                "draft": True,
                "prerelease": False,
                "assets": [{"name": "LoliLend-Setup-2.1.9.exe", "browser_download_url": "https://example/draft.exe"}],
                "published_at": "2026-03-09T12:00:00Z",
            },
        ]
        config = ReleaseConfig(repo="example/repo", asset_pattern="LoliLend-Setup-*.exe", stable_only=True)
        selected = select_latest_release(payload, config)
        self.assertIsNotNone(selected)
        assert selected is not None
        self.assertEqual(selected.version, "2.2.0")
        self.assertEqual(selected.asset_name, "LoliLend-Setup-2.2.0.exe")

    def test_silent_install_command_contains_required_flags(self) -> None:
        command = build_silent_install_command(Path("C:/temp/LoliLend-Setup-2.2.0.exe"))
        self.assertIn("/VERYSILENT", command)
        self.assertIn("/SUPPRESSMSGBOXES", command)
        self.assertIn("/NORESTART", command)
        self.assertIn("/SP-", command)

    def test_install_and_relaunch_command_contains_relaunch(self) -> None:
        command = build_install_and_relaunch_command(
            Path("C:/temp/LoliLend-Setup-2.2.0.exe"),
            "\"C:/Program Files/LoliLend/LoliLend.exe\"",
        )
        self.assertIn("VERYSILENT", command)
        self.assertIn("start \"\"", command)
        self.assertIn("LoliLend.exe", command)


if __name__ == "__main__":
    unittest.main()
