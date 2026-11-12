"""Deletion follows focus and requires confirmation before staging."""
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

from dt_song_mgmt.tui import ConfirmModal, ProjectBrowser


class DeletionTests(unittest.IsolatedAsyncioTestCase):
    async def test_song_and_row_deletions_require_confirmation(self):
        row = {"pattern": 0, "label": "", "repeat": 1, "bpm_raw": 0, "length": 16, "mute": 0}
        state = {"project_name": "TEST", "device": "DT2", "songs": [
            {"slot": 0, "name": "SONG", "row_count": 2, "rows": [row, dict(row)]}
        ], "pending_changes": 0}
        session = SimpleNamespace(path=Path("test.dt2prj").resolve(), name="TEST", device="DT2",
            is_new_project=False, operations=[], working_raw=lambda: b"", state=lambda: state, stage=Mock())
        with patch("dt_song_mgmt.tui.ProjectSession", return_value=session), patch(
            "dt_song_mgmt.tui.collect_pattern_names", return_value=[""] * 128
        ):
            app = ProjectBrowser(session.path)
            async with app.run_test(size=(120, 35)) as pilot:
                await pilot.press("d")
                self.assertIsInstance(app.screen, ConfirmModal)
                self.assertEqual(app.focused.id, "cancel")
                session.stage.assert_not_called()
                await pilot.press("escape")
                session.stage.assert_not_called()
                await pilot.press("d")
                await pilot.click("#confirm")
                session.stage.assert_called_once_with({"type": "empty_song", "slot": 0})
                session.stage.reset_mock()
                for key in ("k", "e"):
                    await pilot.press(key)
                    self.assertIsInstance(app.screen, ConfirmModal)
                    await pilot.press("escape")
                    session.stage.assert_not_called()
                await pilot.press("right")
                self.assertEqual(app.focused.id, "rows-list")
                app.selected_row_indices = {0, 1}
                await pilot.press("shift+space")
                self.assertEqual(app.selected_row_indices, set())
                app.selected_row_indices = {0, 1}
                await pilot.press("backslash")
                self.assertEqual(app.selected_row_indices, set())
                app.selected_row_indices = {0, 1}
                await pilot.press("d")
                self.assertIsInstance(app.screen, ConfirmModal)
                session.stage.assert_not_called()
                await pilot.press("escape")
                session.stage.assert_not_called()
                await pilot.press("d")
                await pilot.click("#confirm")
                session.stage.assert_called_once_with({"type": "delete_rows", "slot": 0, "rows": [0, 1]})
