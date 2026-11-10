"""Song sequencer follows the selected row and its mute state."""

import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from textual.widgets import Static

from dt_song_mgmt.constants import PATTERN_BASE, PATTERN_STRIDE
from dt_song_mgmt.tui import EntryModal, ProjectBrowser


class SongSequencerTests(unittest.IsolatedAsyncioTestCase):
    async def test_song_row_headers_align_with_values(self):
        row = {"pattern": 0, "label": "INTRO", "repeat": 2, "bpm_raw": 14400, "length": 64, "mute": 0}
        state = {"project_name": "TEST", "device": "DT2", "songs": [
            {"slot": 0, "name": "TEST", "row_count": 1, "rows": [row]}
        ], "pending_changes": 0}
        session = SimpleNamespace(
            path=Path("test.dt2prj").resolve(), name="TEST", device="DT2",
            is_new_project=False, operations=[], working_raw=lambda: b"", state=lambda: state,
        )
        with patch("dt_song_mgmt.tui.ProjectSession", return_value=session), patch(
            "dt_song_mgmt.tui.collect_pattern_names", return_value=[""] * 128
        ):
            app = ProjectBrowser(session.path)
            async with app.run_test(size=(120, 35)) as pilot:
                await pilot.pause()
                header = str(app.query_one("#rows-columns", Static).render())
                values = str(app.query_one("#rows-list", Static).render()).splitlines()[0]
                self.assertEqual(header.index("#"), values.index("01") + 1)
                self.assertEqual(header.index("PATTERN/NAME"), values.index("A01"))
                self.assertEqual(header.index("LABEL"), values.index("INTRO"))
                self.assertEqual(header.index("REP"), values.index("×2"))
                self.assertEqual(header.index("BPM") + 3, values.index("120") + 3)
                self.assertEqual(header.index("LEN") + 3, values.index("64") + 2)
                self.assertEqual(header.index("MUTES"), values.index("16 trk"))
                app.editing_label_idx = 1
                app._show_song(0)
                editing = str(app.query_one("#rows-list", Static).render()).splitlines()[0]
                self.assertEqual(header.index("REP"), editing.index("×2"))

    async def test_preview_follows_rows_mutes_pages_and_window_size(self):
        raw = bytearray(PATTERN_BASE + 2 * PATTERN_STRIDE)
        raw[PATTERN_BASE + 4:PATTERN_BASE + 6] = b"\x03\x81"
        raw[PATTERN_BASE + PATTERN_STRIDE + 6:PATTERN_BASE + PATTERN_STRIDE + 8] = b"\x03\x81"
        rows = [
            {"pattern": 0, "label": "", "repeat": 1, "bpm_raw": 0, "length": 16, "mute": 1},
            {"pattern": 1, "label": "", "repeat": 1, "bpm_raw": 0, "length": 16, "mute": 2},
        ]
        state = {"project_name": "TEST", "device": "DT2", "songs": [
            {"slot": 0, "name": "TEST", "row_count": 2, "rows": rows}
        ], "pending_changes": 0}
        session = SimpleNamespace(
            path=Path("test.dt2prj").resolve(), name="TEST", device="DT2",
            is_new_project=False, operations=[], working_raw=lambda: bytes(raw), state=lambda: state,
        )
        with patch("dt_song_mgmt.tui.ProjectSession", return_value=session), patch(
            "dt_song_mgmt.tui.collect_pattern_names", return_value=[""] * 128
        ):
            app = ProjectBrowser(session.path)
            async with app.run_test(size=(140, 35)) as pilot:
                await pilot.press("v")
                await pilot.pause()
                grid = app.query_one("#song-sequencer-grid", Static)
                first = str(grid.render()).splitlines()
                self.assertIn("ROW 01/02 · A01 · PAGE 1", first[0])
                self.assertFalse(app.query_one("#rows-pane").display)
                self.assertFalse(app.query_one("#mute-display").display)
                self.assertTrue(first[2].startswith("T01 M"))
                self.assertEqual(first[2].count("●"), 1)
                await pilot.press("d")
                self.assertFalse(session.operations)
                await pilot.press("down")
                await pilot.pause()
                second = str(grid.render()).splitlines()
                self.assertIn("ROW 02/02 · A02 · PAGE 1", second[0])
                self.assertTrue(second[2].startswith("T01  "))
                self.assertTrue(second[3].startswith("T02 M"))
                await pilot.press("right")
                page_two = str(grid.render()).splitlines()
                self.assertIn("PAGE 2", page_two[0])
                self.assertEqual(page_two[1].split(), ["1", "5", "9", "13"])
                await pilot.resize_terminal(70, 16)
                await pilot.pause()
                self.assertTrue(app.query_one("#workspace").has_class("compact"))
                self.assertGreater(app.query_one("#song-sequencer").region.width, 20)
                await pilot.press("ctrl+down")
                await pilot.pause()
                self.assertGreater(app.query_one("#song-sequencer").scroll_y, 0)
                await pilot.press("tab")
                self.assertEqual(app.focused.id, "songs-list")
                await pilot.press("tab")
                self.assertEqual(app.focused.id, "song-sequencer-grid")
                await pilot.press("v")
                self.assertFalse(app.song_preview_visible)
                self.assertTrue(app.query_one("#rows-pane").display)
                self.assertTrue(app.query_one("#mute-display").display)
                await pilot.press("f6")
                self.assertTrue(app.song_preview_visible)
                await pilot.press("v")
                await pilot.press("i")
                self.assertIsInstance(app.screen, EntryModal)


if __name__ == "__main__":
    unittest.main()
