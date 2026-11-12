"""Trig previews distinguish note trigs from other step flags."""

import unittest

from dt_song_mgmt.constants import PATTERN_BASE, PATTERN_STRIDE
from dt_song_mgmt.pattern_steps import TRACK_STRIDE, pattern_trigs


class PatternStepTests(unittest.TestCase):
    def test_digitakt_four_trigs_and_other_flags(self):
        raw = bytearray(PATTERN_BASE + PATTERN_STRIDE)
        start = PATTERN_BASE + 4
        for step in range(16):
            mask = 0x0381 if step in (0, 4, 8, 12) else 0x0010
            raw[start + 2 * step:start + 2 * step + 2] = mask.to_bytes(2, "big")
        raw[start + 32:start + 34] = b"\xff\xff"
        tracks = pattern_trigs(bytes(raw), 0, "DT2")
        self.assertEqual([i + 1 for i, active in enumerate(tracks[0]) if active], [1, 5, 9, 13])
        self.assertFalse(any(tracks[1]))

    def test_digitone_uses_its_track_stride(self):
        raw = bytearray(PATTERN_BASE + PATTERN_STRIDE)
        offset = PATTERN_BASE + 4 + TRACK_STRIDE["DN2"] + 2 * 7
        raw[offset:offset + 2] = b"\x03\x81"
        tracks = pattern_trigs(bytes(raw), 0, "DN2")
        self.assertEqual([i + 1 for i, active in enumerate(tracks[1]) if active], [8])
        self.assertFalse(any(tracks[0]))


if __name__ == "__main__":
    unittest.main()
