from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from lolilend.ai_ui import _asset_kind, _mime_to_suffix


class AiUiHelpersTests(unittest.TestCase):
    def test_mime_to_suffix_uses_magic_for_octet_stream_images(self) -> None:
        blob = b"\x89PNG\r\n\x1a\n" + b"\x00" * 16
        self.assertEqual(_mime_to_suffix("application/octet-stream", ".png", data=blob), ".png")

    def test_asset_kind_detects_image_from_bin_header(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "image.bin"
            path.write_bytes(b"\x89PNG\r\n\x1a\n" + b"\x00" * 32)
            self.assertEqual(_asset_kind(path), "image")

    def test_asset_kind_detects_text_from_bin_payload(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "note.bin"
            path.write_bytes("hello from lolilend".encode("utf-8"))
            self.assertEqual(_asset_kind(path), "text")


if __name__ == "__main__":
    unittest.main()
