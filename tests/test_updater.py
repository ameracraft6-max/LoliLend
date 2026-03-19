from __future__ import annotations

from pathlib import Path
import unittest
from typing import Any

from lolilend.updater import (
    ReleaseConfig,
    build_install_and_relaunch_command,
    build_silent_install_command,
    fetch_latest_release,
    is_newer_version,
    parse_semver,
    select_latest_release,
)


class _FakeResponse:
    def __init__(self, *, status_code: int, payload: Any = None, text: str = "", url: str = "") -> None:
        self.status_code = status_code
        self._payload = payload
        self.text = text
        self.url = url
        self.headers: dict[str, str] = {}

    def json(self) -> Any:
        return self._payload


class _FakeSession:
    def __init__(self, mapping: dict[str, _FakeResponse]) -> None:
        self._mapping = mapping

    def get(self, url: str, **kwargs: Any) -> _FakeResponse:
        del kwargs
        if url not in self._mapping:
            raise AssertionError(f"Unexpected URL call: {url}")
        return self._mapping[url]


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

    def test_fetch_latest_release_uses_latest_endpoint_for_stable(self) -> None:
        config = ReleaseConfig(repo="example/repo", asset_pattern="LoliLend-Setup-*.exe", stable_only=True)
        session = _FakeSession(
            {
                "https://api.github.com/repos/example/repo/releases/latest": _FakeResponse(
                    status_code=200,
                    payload={
                        "tag_name": "v2.2.0",
                        "draft": False,
                        "prerelease": False,
                        "assets": [
                            {
                                "name": "LoliLend-Setup-2.2.0.exe",
                                "browser_download_url": "https://github.com/example/repo/releases/download/v2.2.0/LoliLend-Setup-2.2.0.exe",
                            }
                        ],
                        "published_at": "2026-03-19T10:00:00Z",
                    },
                )
            }
        )
        release = fetch_latest_release(config, session=session)
        self.assertIsNotNone(release)
        assert release is not None
        self.assertEqual(release.version, "2.2.0")
        self.assertEqual(release.asset_name, "LoliLend-Setup-2.2.0.exe")

    def test_fetch_latest_release_fallbacks_to_web_on_403(self) -> None:
        config = ReleaseConfig(repo="example/repo", asset_pattern="LoliLend-Setup-*.exe", stable_only=True)
        session = _FakeSession(
            {
                "https://api.github.com/repos/example/repo/releases/latest": _FakeResponse(status_code=403),
                "https://github.com/example/repo/releases/latest": _FakeResponse(
                    status_code=200,
                    url="https://github.com/example/repo/releases/tag/v2.0.1",
                ),
                "https://github.com/example/repo/releases/expanded_assets/v2.0.1": _FakeResponse(
                    status_code=200,
                    text='<a href="/example/repo/releases/download/v2.0.1/LoliLend-Setup-2.0.1.exe">download</a>',
                ),
            }
        )
        release = fetch_latest_release(config, session=session)
        self.assertIsNotNone(release)
        assert release is not None
        self.assertEqual(release.version, "2.0.1")
        self.assertEqual(release.asset_name, "LoliLend-Setup-2.0.1.exe")
        self.assertEqual(
            release.asset_url,
            "https://github.com/example/repo/releases/download/v2.0.1/LoliLend-Setup-2.0.1.exe",
        )


if __name__ == "__main__":
    unittest.main()
