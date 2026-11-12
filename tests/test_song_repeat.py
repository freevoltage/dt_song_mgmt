"""Repeat decoding checked against the user's Digitone II debug project."""
import unittest

from dt_song_mgmt.constants import DN2_IMAGE_SIZE, DT2_IMAGE_SIZE, MAGIC_TAIL
from dt_song_mgmt.songs import get_all_songs_info, get_song_rows, get_song_slots, set_song_rows, set_song_slots
from dt_song_mgmt.state import apply_operations


def project(size):
    raw = bytearray(size)
    raw[-4:] = MAGIC_TAIL
    slots = get_song_slots(bytes(raw))
    # The 16 hardware-created rows use byte 1 values 0..15 for repeats 1..16.
    rows = [bytes.fromhex(f"00 {value:02x} 03 00 00 38 40 00 00 00 10" + " 00" * 18) for value in range(16)]
    slots[0] = set_song_rows(slots[0], rows)
    return set_song_slots(bytes(raw), slots)


class SongRepeatTests(unittest.TestCase):
    def test_digitone_reads_and_edits_repeat_without_touching_other_bytes(self):
        raw = project(DN2_IMAGE_SIZE)
        self.assertEqual([r['repeat'] for r in get_all_songs_info(raw)[0]['rows']], list(range(1, 17)))
        changed = apply_operations(raw, [{'type': 'update_rows', 'slot': 0, 'rows': [0], 'updates': {'repeat': 2}}])
        before = get_song_rows(get_song_slots(raw)[0])
        after = get_song_rows(get_song_slots(changed)[0])
        self.assertEqual(after[0][1], 1)
        self.assertEqual(after[0][:1] + after[0][2:], before[0][:1] + before[0][2:])
        self.assertEqual(after[1], before[1])
        self.assertEqual(get_all_songs_info(changed)[0]['rows'][0]['repeat'], 2)
        with self.assertRaises(ValueError):
            apply_operations(raw, [{'type': 'update_rows', 'slot': 0, 'rows': [0], 'updates': {'repeat': 100}}])
        self.assertEqual(get_all_songs_info(raw)[0]['rows'][0]['label'], 'OUTRO')
        labelled = apply_operations(raw, [{'type': 'update_rows', 'slot': 0, 'rows': [0], 'updates': {'label_idx': 2}}])
        labelled_row = get_song_rows(get_song_slots(labelled)[0])[0]
        self.assertEqual(labelled_row[2], 2)
        self.assertEqual(labelled_row[:2] + labelled_row[3:], before[0][:2] + before[0][3:])
        self.assertEqual(get_all_songs_info(labelled)[0]['rows'][0]['label'], 'INTRO')
        self.assertEqual(get_all_songs_info(labelled)[0]['rows'][0]['repeat'], 1)

    def test_digitakt_keeps_existing_encoding_until_verified(self):
        raw = project(DT2_IMAGE_SIZE)
        self.assertEqual([r['repeat'] for r in get_all_songs_info(raw)[0]['rows']], [3] * 16)
        changed = apply_operations(raw, [{'type': 'update_rows', 'slot': 0, 'rows': [0], 'updates': {'repeat': 2}}])
        self.assertEqual(get_song_rows(get_song_slots(changed)[0])[0][2], 2)
