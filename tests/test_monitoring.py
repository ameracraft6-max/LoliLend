from __future__ import annotations

import unittest

from lolilend.monitoring import HistoryBuffer, compute_counter_rate, format_bitrate_auto


class MonitoringHelpersTests(unittest.TestCase):
    def test_format_bitrate_auto_uses_mbps_for_high_values(self) -> None:
        value, unit = format_bitrate_auto(125_000)  # 1,000,000 bits/s
        self.assertEqual(unit, "Mbps")
        self.assertAlmostEqual(value, 1.0, places=3)

    def test_format_bitrate_auto_uses_kbps_for_low_values(self) -> None:
        value, unit = format_bitrate_auto(512)  # 4096 bits/s
        self.assertEqual(unit, "Kbps")
        self.assertAlmostEqual(value, 4.096, places=3)

    def test_compute_counter_rate(self) -> None:
        self.assertAlmostEqual(compute_counter_rate(100, 160, 2.0), 30.0)
        self.assertEqual(compute_counter_rate(None, 160, 2.0), 0.0)
        self.assertEqual(compute_counter_rate(160, 100, 2.0), 0.0)
        self.assertEqual(compute_counter_rate(100, 160, 0.0), 0.0)

    def test_history_buffer_keeps_last_values_and_left_pads(self) -> None:
        history = HistoryBuffer(max_points=3)
        history.push(10)
        history.push(20)
        self.assertEqual(history.values(), [0.0, 10.0, 20.0])
        history.push(30)
        history.push(40)
        self.assertEqual(history.values(), [20.0, 30.0, 40.0])


if __name__ == "__main__":
    unittest.main()
