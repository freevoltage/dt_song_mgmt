"""Regression coverage for Digitakt II sample selectors and lock remapping."""

import unittest

from dt_song_mgmt.constants import KIT_BASE, PATTERN_BASE
from dt_song_mgmt.dt2_samples import (
    DT2_IMAGE_MIN_SIZE,
    EMPTY_POOL_ROW,
    SAMPLE_LOCKS_OFFSET,
    SAMPLE_LOCK_PARAM_ID,
    SAMPLE_LOCK_RECORD_SIZE,
    SAMPLE_POOL_OFFSET,
    SAMPLE_POOL_ROW_COUNT,
    SAMPLE_POOL_ROW_SIZE,
    SOUND_BASE,
    SOUND_SAMPLE_SLOT_OFFSET,
    pattern_sample_hashes,
    pattern_sample_lock_slots,
    remap_pattern_sample_pool,
    sample_pool_rows,
)


def empty_image():
    raw = bytearray(DT2_IMAGE_MIN_SIZE)
    for index in range(SAMPLE_POOL_ROW_COUNT):
        offset = SAMPLE_POOL_OFFSET + index * SAMPLE_POOL_ROW_SIZE
        raw[offset:offset + SAMPLE_POOL_ROW_SIZE] = EMPTY_POOL_ROW
    return raw


def pool_row(sample_hash):
    return sample_hash.to_bytes(4, "big") + (1024).to_bytes(4, "big") + bytes(8)


class SampleSelectorTests(unittest.TestCase):
    def test_default_selector_and_locks_follow_pool_rows_when_remapped(self):
        source = empty_image()
        first, second = 0x12345678, 0xA0D9C475
        source[SAMPLE_POOL_OFFSET:SAMPLE_POOL_OFFSET + 16] = pool_row(first)
        source[SAMPLE_POOL_OFFSET + 16:SAMPLE_POOL_OFFSET + 32] = pool_row(second)
        selector = KIT_BASE + SOUND_BASE + SOUND_SAMPLE_SLOT_OFFSET
        source[selector:selector + 2] = (3).to_bytes(2, "big")
        lock = PATTERN_BASE + SAMPLE_LOCKS_OFFSET
        source[lock:lock + SAMPLE_LOCK_RECORD_SIZE] = bytes([SAMPLE_LOCK_PARAM_ID, 0]) + b"\xff" * 256
        source[lock + 2:lock + 6] = b"\x00\x02\x00\x03"

        references = pattern_sample_hashes(bytes(source), 0)
        self.assertEqual(references[second]["default_tracks"], {0})
        self.assertEqual(references[first]["locked_tracks"], {0})

        target = empty_image()
        target[SAMPLE_POOL_OFFSET:SAMPLE_POOL_OFFSET + 16] = pool_row(second)
        target[selector:selector + 2] = source[selector:selector + 2]
        target[lock:lock + SAMPLE_LOCK_RECORD_SIZE] = source[lock:lock + SAMPLE_LOCK_RECORD_SIZE]
        remapped, mapping, _ = remap_pattern_sample_pool(bytes(source), bytes(target), 0, 0)

        self.assertEqual(mapping[3], 2)
        self.assertEqual(int.from_bytes(remapped[selector:selector + 2], "big"), 2)
        source_pool, target_pool = sample_pool_rows(bytes(source)), sample_pool_rows(remapped)
        for slot in pattern_sample_lock_slots(bytes(source), 0)[0]:
            self.assertEqual(source_pool[slot - 2].sample_hash, target_pool[mapping[slot] - 2].sample_hash)
        self.assertEqual(pattern_sample_lock_slots(remapped, 0)[0], {mapping[2], mapping[3]})


if __name__ == "__main__":
    unittest.main()
