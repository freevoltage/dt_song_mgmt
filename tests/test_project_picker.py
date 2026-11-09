"""Keyboard selection in the project picker."""

import tempfile
import unittest
from pathlib import Path

from textual.app import App
from textual.widgets import OptionList

from dt_song_mgmt.tui import ProjectPickerModal


class PickerApp(App):
    def __init__(self, directory):
        super().__init__()
        self.directory = directory
        self.chosen = None

    def on_mount(self):
        self.push_screen(ProjectPickerModal(self.directory), self._chosen)

    def _chosen(self, path):
        self.chosen = path


class ProjectPickerTests(unittest.IsolatedAsyncioTestCase):
    async def test_enter_opens_project_ahead_of_extracted_folder(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory).resolve()
            project = root / "SONG(2).dt2prj"
            project.touch()
            (root / "SONG(2).dt2prj_1").mkdir()
            app = PickerApp(root)
            async with app.run_test() as pilot:
                await pilot.pause()
                picker = app.screen
                index = picker.query_one("#project-picker-list", OptionList).highlighted
                self.assertEqual(picker._entries[index], (project, False))
                await pilot.press("enter")
                await pilot.pause()
                self.assertEqual(app.chosen, project)

    async def test_when_no_projects_enter_opens_child_folder(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory).resolve()
            child = root / "Projects"
            child.mkdir()
            app = PickerApp(root)
            async with app.run_test() as pilot:
                await pilot.pause()
                await pilot.press("enter")
                await pilot.pause()
                self.assertEqual(app.screen.directory, child)
                self.assertIsNone(app.chosen)


if __name__ == "__main__":
    unittest.main()
