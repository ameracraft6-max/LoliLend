from __future__ import annotations

import unittest

from lolilend.ai_security import BootstrapTokenProvider, CF_BOOTSTRAP_TOKEN


class _FakeStore:
    def __init__(self, read_value: str | None = None) -> None:
        self.read_value = read_value
        self.written: list[str] = []

    def read(self) -> str | None:
        return self.read_value

    def write(self, secret: str) -> bool:
        self.written.append(secret)
        self.read_value = secret
        return True


class BootstrapTokenProviderTests(unittest.TestCase):
    def test_returns_existing_secret_without_overwrite(self) -> None:
        store = _FakeStore("existing")
        provider = BootstrapTokenProvider(store)
        self.assertEqual(provider.resolve_token(), "existing")
        self.assertEqual(store.written, [])

    def test_writes_bootstrap_when_missing(self) -> None:
        store = _FakeStore(None)
        provider = BootstrapTokenProvider(store)
        self.assertEqual(provider.resolve_token(), CF_BOOTSTRAP_TOKEN)
        self.assertEqual(store.written, [CF_BOOTSTRAP_TOKEN])


if __name__ == "__main__":
    unittest.main()
