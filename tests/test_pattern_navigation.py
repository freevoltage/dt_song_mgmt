"""Pattern navigation uses project slot numbers after bank and search filters."""

import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from textual.app import App
from textual.widgets import Static

from dt_song_mgmt.constants import PATTERN_BASE, PATTERN_STRIDE
from dt_song_mgmt.songs import pattern_label
from dt_song_mgmt.tui_patterns import PatternManagerScreen


class PatternApp(App):
    def __init__(self, raw=b""):
        super().__init__()
        self.raw = raw

    def on_mount(self):
        session = SimpleNamespace(
            working_raw=lambda: self.raw, path=Path("test.dt2prj"),
            is_new_project=False, device="DT2", operations=[],
        )
        self.push_screen(PatternManagerScreen(session))


class PatternNavigationTests(unittest.IsolatedAsyncioTestCase):
    async def test_optional_preview_follows_pattern_and_pages(self):
        raw = bytearray(PATTERN_BASE + PATTERN_STRIDE)
        for step in (0, 4, 8, 12):
            offset = PATTERN_BASE + 4 + 2 * step
            raw[offset:offset + 2] = b"\x03\x81"
        patterns = [
            {"index": i, "label": pattern_label(i), "name": "", "ref_count": 0, "references": []}
            for i in range(128)
        ]
        with patch("dt_song_mgmt.tui_patterns.get_all_patterns_info", return_value=patterns):
            app = PatternApp(bytes(raw))
            async with app.run_test(size=(55, 30)) as pilot:
                await pilot.press("v")
                await pilot.pause()
                screen = app.screen
                self.assertTrue(screen.preview_visible)
                text = str(screen.query_one("#pattern-preview-grid", Static).render())
                self.assertIn("A01  STEPS 001–016", text)
                self.assertEqual(text.splitlines()[2].count("●"), 4)
                await pilot.press("right")
                self.assertIn("STEPS 017–032", str(screen.query_one("#pattern-preview-grid", Static).render()))
                await pilot.press("v")
                self.assertFalse(screen.preview_visible)

    async def test_song_use_stays_visible_in_narrow_pattern_list(self):
        patterns = [
            {"index": i, "label": pattern_label(i), "name": "FROSCH" if i == 16 else "",
             "ref_count": 15 if i == 16 else 0,
             "references": [{"song_slot": 0, "song_name": "FROSCH", "row": 1}] if i == 16 else []}
            for i in range(128)
        ]
        with patch("dt_song_mgmt.tui_patterns.get_all_patterns_info", return_value=patterns):
            app = PatternApp()
            async with app.run_test(size=(45, 30)) as pilot:
                await pilot.press("2", "home")
                await pilot.pause()
                screen = app.screen
                line = str(screen.query_one("#pattern-list", Static).render()).splitlines()[0]
                visible_width = screen.query_one("#pattern-results").size.width
                self.assertIn("15r", line[:visible_width])
                self.assertIn("FROSCH", str(screen.query_one("#pattern-selection", Static).render()))

    async def test_arrows_and_pages_follow_slots_in_every_bank_and_search(self):
        patterns = [
            {
                "index": index, "label": pattern_label(index),
                "name": "keep" if index in {18, 22, 27} else "",
                "ref_count": 0, "references": [],
            }
            for index in range(128)
        ]
        with patch("dt_song_mgmt.tui_patterns.get_all_patterns_info", return_value=patterns):
            app = PatternApp()
            async with app.run_test() as pilot:
                await pilot.pause()
                screen = app.screen
                for bank in range(8):
                    await pilot.press(str(bank + 1))
                    await pilot.press("home", "down")
                    self.assertEqual(screen.selected_pattern, bank * 16 + 1)
                    await pilot.press("up")
                    self.assertEqual(screen.selected_pattern, bank * 16)
                    await pilot.press("pagedown")
                    self.assertEqual(screen.selected_pattern, bank * 16 + 12)
                    await pilot.press("pageup")
                    self.assertEqual(screen.selected_pattern, bank * 16)
                await pilot.press("0", "home", "down")
                self.assertEqual(screen.selected_pattern, 1)
                await pilot.press("2")
                screen.filter_text = "keep"
                screen._refresh_view()
                await pilot.press("home", "down")
                self.assertEqual(screen.selected_pattern, 22)
                await pilot.press("down")
                self.assertEqual(screen.selected_pattern, 27)


if __name__ == "__main__":
    unittest.main()
