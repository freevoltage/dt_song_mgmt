"""The TUI can start with or without an explicit project path."""

import sys
import tempfile
import types
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from dt_song_mgmt.cli import main


class CliStartupTests(unittest.TestCase):
    def test_empty_and_tui_commands_open_picker(self):
        tui = types.ModuleType("dt_song_mgmt.tui")
        tui.run_tui = Mock()
        with patch.dict(sys.modules, {"dt_song_mgmt.tui": tui}):
            main([])
            main(["tui"])
        self.assertEqual(tui.run_tui.call_count, 2)
        tui.run_tui.assert_called_with()

    def test_project_then_tui_still_opens_that_project(self):
        tui = types.ModuleType("dt_song_mgmt.tui")
        tui.run_tui = Mock()
        with tempfile.TemporaryDirectory() as directory:
            project = Path(directory) / "song.dt2prj"
            project.touch()
            with patch.dict(sys.modules, {"dt_song_mgmt.tui": tui}):
                main([str(project), "tui"])
            tui.run_tui.assert_called_once_with(project.resolve())


if __name__ == "__main__":
    unittest.main()
