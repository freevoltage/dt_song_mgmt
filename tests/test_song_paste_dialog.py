"""The song paste dialog offers both pattern handling choices."""

import unittest

from textual.app import App
from textual.widgets import Input

from dt_song_mgmt.tui import SongPatternMappingModal


class PasteApp(App):
    def __init__(self, arrangement_only=False):
        super().__init__()
        self.arrangement_only = arrangement_only
        self.result = None

    def on_mount(self):
        self.push_screen(
            SongPatternMappingModal(
                {0}, [""] * 128, [""] * 128, "source", 0, "destination", 1,
                arrangement_only=self.arrangement_only,
            ),
            self._result,
        )

    def _result(self, result):
        self.result = result


class SongPasteDialogTests(unittest.IsolatedAsyncioTestCase):
    async def test_keep_destination_patterns(self):
        app = PasteApp()
        async with app.run_test(size=(100, 40)) as pilot:
            await pilot.pause()
            await pilot.click("#keep")
            await pilot.pause()
            self.assertEqual(app.result, {"mode": "arrangement"})

    async def test_copy_patterns_uses_mapping(self):
        app = PasteApp()
        async with app.run_test(size=(100, 40)) as pilot:
            await pilot.pause()
            app.screen.query_one("#mapping-destination-0", Input).value = "B02"
            await pilot.click("#apply")
            await pilot.pause()
            self.assertEqual(app.result, {"mode": "patterns", "mappings": [{"src_idx": 0, "dst_idx": 17}]})

    async def test_arrangement_file_offers_only_keep_patterns(self):
        app = PasteApp(arrangement_only=True)
        async with app.run_test(size=(100, 40)) as pilot:
            await pilot.pause()
            self.assertEqual(len(app.screen.query("#apply")), 0)
            await pilot.press("enter")
            await pilot.pause()
            self.assertEqual(app.result, {"mode": "arrangement"})


if __name__ == "__main__":
    unittest.main()
