"""Arrangement-only pastes preserve patterns and support one-step undo."""

import unittest
from pathlib import Path

from dt_song_mgmt.constants import DT2_IMAGE_SIZE, KIT_BASE, MAGIC_TAIL, PATTERN_BASE
from dt_song_mgmt.session import ProjectSession
from dt_song_mgmt.songs import get_song_rows, get_song_slots, rename_song, set_song_rows, set_song_slots, song_table_off


class SongArrangementPasteTests(unittest.TestCase):
    def test_same_project_cut_moves_only_song_and_undoes_atomically(self):
        raw = bytearray(DT2_IMAGE_SIZE)
        raw[-4:] = MAGIC_TAIL
        raw[PATTERN_BASE + 10] = 0x93
        raw[KIT_BASE + 42] = 0x71
        slots = get_song_slots(bytes(raw))
        row = bytearray(29)
        row[0], row[2], row[7], row[8] = 5, 3, 0x12, 0x34
        slots[0] = rename_song(set_song_rows(slots[0], [row]), "SOURCE")
        slots[1] = rename_song(slots[1], "DESTINATION")
        original = set_song_slots(bytes(raw), slots)
        session = ProjectSession.__new__(ProjectSession)
        session.path = Path("/tmp/example.dt2prj")
        session.device = "DT2"
        session.base_raw = original
        session.members = []
        session.operations = []
        session.redo_operations = []

        session.stage_song_arrangement_paste(1, slots[0], clear_source_slot=0)
        updated = session.working_raw()
        songs = get_song_slots(updated)
        self.assertEqual(songs[1], slots[0])
        self.assertEqual(get_song_rows(songs[0]), [])
        self.assertEqual(updated[:song_table_off(updated)], original[:song_table_off(original)])
        self.assertEqual(len(session.operations), 1)
        self.assertTrue(session.undo())
        self.assertEqual(session.working_raw(), original)
        self.assertTrue(session.redo())
        self.assertEqual(session.working_raw(), updated)


if __name__ == "__main__":
    unittest.main()
