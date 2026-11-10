"""Song sequencer follows the selected row and its mute state."""

import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from textual.widgets import Static

from dt_song_mgmt.constants import PATTERN_BASE, PATTERN_STRIDE
from dt_song_mgmt.tui import ProjectBrowser


class SongSequencerTests(unittest.IsolatedAsyncioTestCase):
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
                await pilot.press("f6")
                await pilot.pause()
                grid = app.query_one("#song-sequencer-grid", Static)
                first = str(grid.render()).splitlines()
                self.assertIn("A01  STEPS 001–016", first[0])
                self.assertTrue(first[2].startswith("T01 M"))
                self.assertEqual(first[2].count("●"), 1)
                await pilot.press("right", "down")
                await pilot.pause()
                second = str(grid.render()).splitlines()
                self.assertIn("A02  STEPS 001–016", second[0])
                self.assertTrue(second[2].startswith("T01  "))
                self.assertTrue(second[3].startswith("T02 M"))
                await pilot.press("alt+right")
                self.assertIn("STEPS 017–032", str(grid.render()))
                await pilot.resize_terminal(70, 30)
                await pilot.pause()
                self.assertTrue(app.query_one("#workspace").has_class("compact"))
                self.assertEqual(app.query_one("#song-sequencer").region.height, 9)
                await pilot.press("ctrl+down")
                await pilot.pause()
                self.assertGreater(app.query_one("#song-sequencer").scroll_y, 0)
                await pilot.press("f6")
                self.assertFalse(app.song_preview_visible)


if __name__ == "__main__":
    unittest.main()
