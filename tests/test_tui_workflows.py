"""Drive the real TUI with keys, including file IO, then reopen the project."""
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from dt_song_mgmt.session import ProjectSession
from dt_song_mgmt.songs import get_song_rows, get_song_slots
from dt_song_mgmt.tui import ConfirmModal, EntryModal, ProjectBrowser, ProjectPickerModal, SaveValidationModal, UnsavedExitModal
from tests.test_project_integrity import write_fixture


class TuiWorkflowTests(unittest.IsolatedAsyncioTestCase):
    async def enter_value(self, pilot, app, value):
        self.assertIsInstance(app.screen, EntryModal)
        await pilot.press('home', 'shift+end', *str(value), 'enter')
        await pilot.pause()

    async def open_project(self, pilot, app, path):
        await pilot.press('ctrl+o')
        self.assertIsInstance(app.screen, ProjectPickerModal)
        await pilot.press('enter')
        await pilot.pause()
        self.assertEqual(app.session.path, path.resolve())

    async def test_open_edit_save_quit_and_reopen_through_real_tui(self):
        for device in ('DN2', 'DT2'):
            with self.subTest(device=device), tempfile.TemporaryDirectory() as directory, patch(
                'dt_song_mgmt.tui.Path.cwd', return_value=Path(directory)
            ):
                path = write_fixture(Path(directory), device)
                original_file = path.read_bytes()
                app = ProjectBrowser()
                async with app.run_test(size=(140, 50)) as pilot:
                    await self.open_project(pilot, app, path)
                    # Song 1 starts with all tracks playing.
                    await pilot.press('down', 'r')
                    await self.enter_value(pilot, app, 'UI TEST')
                    await pilot.press('enter', 'right', 'right', 'enter')
                    await self.enter_value(pilot, app, '7')
                    # OUTRO -> BRIDGE through the inline label selector.
                    await pilot.press('left', 'enter', 'down', 'enter')
                    await pilot.press('right', 'right', 'right', 'right', 'enter')
                    await self.enter_value(pilot, app, '1')
                    row = app.songs[1]['rows'][0]
                    self.assertEqual((row['repeat'], row['label'], row['mute']), (7, 'BRIDGE', 1))
                    await pilot.press('u')
                    self.assertEqual(app.songs[1]['rows'][0]['mute'], 0)
                    await pilot.press('ctrl+y')
                    self.assertEqual(app.songs[1]['rows'][0]['mute'], 1)
                    self.assertEqual(path.read_bytes(), original_file)
                    self.assertFalse(path.with_suffix(path.suffix + '.bak').exists())
                    await pilot.press('s')
                    self.assertIsInstance(app.screen, SaveValidationModal)
                    self.assertTrue(app.screen.can_continue, app.screen.checks)
                    await pilot.click('#continue')
                    await pilot.pause()
                    self.assertFalse(app.session.operations)
                    await pilot.press('q')
                    self.assertFalse(app.is_running)

                self.assertEqual(path.with_suffix(path.suffix + '.bak').read_bytes(), original_file)
                reopened = ProjectSession(path)
                row = get_song_rows(get_song_slots(reopened.base_raw)[1])[0]
                # Independent encoded expectation: track 1, not track 9.
                self.assertEqual(bytes(row[7:9]), b'\x01\x00')
                self.assertEqual((row[1], row[2]), (6, 4))
                self.assertEqual(reopened.state()['songs'][1]['name'], 'UI TEST')

                # Start the TUI again and check what it actually displays.
                second_app = ProjectBrowser()
                async with second_app.run_test(size=(140, 50)) as pilot:
                    await self.open_project(pilot, second_app, path)
                    await pilot.press('down', 'enter')
                    row = second_app.songs[1]['rows'][0]
                    self.assertEqual((row['repeat'], row['label'], row['mute']), (7, 'BRIDGE', 1))
                    await pilot.press('q')
                    self.assertFalse(second_app.is_running)

    async def test_cancel_save_and_discard_quit_preserve_original_project(self):
        with tempfile.TemporaryDirectory() as directory:
            path = write_fixture(Path(directory), 'DN2')
            original_file = path.read_bytes()
            app = ProjectBrowser(path)
            async with app.run_test(size=(140, 50)) as pilot:
                await pilot.press('d')
                self.assertIsInstance(app.screen, ConfirmModal)
                await pilot.press('escape')
                self.assertFalse(app.session.operations)
                await pilot.press('enter', 'right', 'right', 'enter')
                await self.enter_value(pilot, app, '8')
                await pilot.press('q')
                self.assertIsInstance(app.screen, UnsavedExitModal)
                await pilot.press('escape')
                self.assertTrue(app.is_running)
                self.assertTrue(app.session.operations)
                await pilot.press('s')
                self.assertIsInstance(app.screen, SaveValidationModal)
                await pilot.press('escape')
                self.assertEqual(path.read_bytes(), original_file)
                self.assertFalse(path.with_suffix(path.suffix + '.bak').exists())
                self.assertTrue(app.session.operations)
                await pilot.press('q')
                self.assertIsInstance(app.screen, UnsavedExitModal)
                await pilot.click('#discard')
                await pilot.pause()
                self.assertFalse(app.is_running)
            self.assertEqual(path.read_bytes(), original_file)
            self.assertEqual(ProjectSession(path).state()['songs'][0]['rows'][0]['repeat'], 1)
