"""Checks for estimated project RAM accounting."""

import unittest
from unittest.mock import patch

from dt_song_mgmt.sample_memory import (
    DT2_SAMPLE_POOL_OFFSET,
    DT2_SAMPLE_POOL_ROW_SIZE,
    analyze_sample_memory,
    format_project_ram,
)


class SampleMemoryTests(unittest.TestCase):
    def test_pool_estimate_counts_each_occupied_slot(self):
        raw = bytearray(DT2_SAMPLE_POOL_OFFSET + DT2_SAMPLE_POOL_ROW_SIZE * 2)
        row = (0x12345678).to_bytes(4, "big") + (1_500_000).to_bytes(4, "big") + bytes(8)
        raw[DT2_SAMPLE_POOL_OFFSET:DT2_SAMPLE_POOL_OFFSET + 16] = row
        raw[DT2_SAMPLE_POOL_OFFSET + 16:DT2_SAMPLE_POOL_OFFSET + 32] = row
        with patch("dt_song_mgmt.sample_memory.device_name", return_value="DT2"), patch(
            "dt_song_mgmt.sample_memory.pattern_sample_hashes", return_value={}
        ):
            result = analyze_sample_memory(bytes(raw), {"Samples": []})
        self.assertEqual(result["sample_pool_count"], 2)
        self.assertEqual(result["sample_pool_bytes"], 3_000_000)
        self.assertIn("3.0 / 400 MB", format_project_ram(result))
        self.assertIn("~397.0 MB free", format_project_ram(result))

    def test_remaining_estimate_does_not_go_negative(self):
        text = format_project_ram({"sample_pool_bytes": 410_000_000, "sample_pool_count": 2})
        self.assertIn("410.0 / 400 MB", text)
        self.assertIn("~0.0 MB free", text)


if __name__ == "__main__":
    unittest.main()
