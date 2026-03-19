from __future__ import annotations

import unittest

from lolilend.ai_text import repair_mojibake_text


class AiTextTests(unittest.TestCase):
    def test_repairs_typical_utf8_cp1251_mojibake(self) -> None:
        fixed, changed = repair_mojibake_text("РџСЂРёРІРµС‚, РјРёСЂ")
        self.assertTrue(changed)
        self.assertEqual(fixed, "Привет, мир")

    def test_keeps_normal_unicode_intact(self) -> None:
        fixed, changed = repair_mojibake_text("Привет, мир")
        self.assertFalse(changed)
        self.assertEqual(fixed, "Привет, мир")


if __name__ == "__main__":
    unittest.main()
