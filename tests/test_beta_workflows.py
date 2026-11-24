"""Beta acceptance workflows through real project tabs and Pattern Manager."""
import copy
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest.mock import patch

from textual.widgets import Static

from dt_song_mgmt.constants import KIT_BASE, PATTERN_STRIDE, kit_stride
from dt_song_mgmt.dt2_samples import SOUND_BASE, SOUND_SAMPLE_SLOT_OFFSET, pattern_sample_hashes
from dt_song_mgmt.project import pack_project
from dt_song_mgmt.session import ProjectSession
from dt_song_mgmt.songs import get_song_rows, get_song_slots, song_table_off
from dt_song_mgmt.tui import ProjectBrowser, SongPatternMappingModal, UnsavedExitModal
from dt_song_mgmt.tui_patterns import PatternConfirmModal, PatternManagerScreen
from tests.project_fixtures import (
    SAMPLE_A, SAMPLE_B, UNUSED_SAMPLE, TARGET_SAMPLE, AUDIO, NAMES,
    archive_data, pattern_bytes, kit_bytes, write_fixture,
)
from tests.tui_helpers import TuiDriver


class BetaWorkflowTests(unittest.IsolatedAsyncioTestCase):
    def assert_audio(self, session, hashes):
        entries = {int(e['Hash']): e for e in session.working_manifest()['Samples']}
        self.assertEqual(set(entries), hashes)
        members = archive_data(session)
        for value, entry in entries.items():
            self.assertEqual(members[entry['FileName']], AUDIO[value])

    async def test_pattern_copy_move_confirmed_delete_save_and_reopen(self):
        for device in ('DN2', 'DT2'):
            with self.subTest(device=device), tempfile.TemporaryDirectory() as directory:
                path = write_fixture(Path(directory), device)
                original_file = path.read_bytes()
                original = ProjectSession(path).base_raw
                app = ProjectBrowser(path)
                async with app.run_test(size=(140, 50)) as pilot:
                    ui = TuiDriver(self, pilot, app)
                    await pilot.press('f2')
                    await ui.pattern('A01')
                    await pilot.press('y')
                    await ui.pattern('B04')
                    await pilot.press('p')
                    self.assertEqual(pattern_bytes(app.session.working_raw(), 19), pattern_bytes(original, 0))
                    self.assertEqual(kit_bytes(app.session.working_raw(), 19), kit_bytes(original, 0))
                    await ui.pattern('A01')
                    await pilot.press('x')
                    await ui.pattern('B16')
                    await pilot.press('p')
                    moved = app.session.working_raw()
                    self.assertEqual(pattern_bytes(moved, 0), bytes(PATTERN_STRIDE))
                    self.assertEqual(pattern_bytes(moved, 31), pattern_bytes(original, 0))
                    self.assertEqual(kit_bytes(moved, 31), kit_bytes(original, 0))
                    self.assertEqual([r[0] for r in get_song_rows(get_song_slots(moved)[0])], [31, 1, 31])
                    await ui.pattern('B04')
                    await pilot.press('d')
                    self.assertIsInstance(app.screen, PatternConfirmModal)
                    self.assertEqual(app.focused.id, 'cancel')
                    await pilot.press('escape')
                    self.assertEqual(app.session.working_raw(), moved)
                    await pilot.press('d')
                    await pilot.click('#confirm')
                    self.assertEqual(pattern_bytes(app.session.working_raw(), 19), bytes(PATTERN_STRIDE))
                    self.assertEqual(kit_bytes(app.session.working_raw(), 19), bytes(kit_stride(original)))
                    await pilot.press('escape', 'u')
                    self.assertEqual(app.session.working_raw(), moved)
                    await pilot.press('ctrl+y')
                    expected = app.session.working_raw()
                    self.assertEqual(path.read_bytes(), original_file)
                    self.assertFalse(path.with_suffix(path.suffix + '.bak').exists())
                    await ui.save()
                    await ui.quit()
                reopened = ProjectSession(path)
                self.assertEqual(reopened.base_raw, expected)
                self.assertEqual(path.with_suffix(path.suffix + '.bak').read_bytes(), original_file)
                self.assertEqual(pattern_bytes(reopened.base_raw, 1), pattern_bytes(original, 1))
                self.assertEqual(kit_bytes(reopened.base_raw, 1), kit_bytes(original, 1))
                if device == 'DT2':
                    self.assert_audio(reopened, {SAMPLE_A, SAMPLE_B, UNUSED_SAMPLE})

    async def test_failed_pattern_cut_preserves_both_projects_and_redo_history(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source_path = write_fixture(root, 'DT2')
            target_path = write_fixture(root, 'DT2', False)
            # Leave A referenced but remove its audio from the source archive.
            with zipfile.ZipFile(source_path) as zf:
                members = [(info, zf.read(info.filename)) for info in zf.infolist() if info.filename != NAMES[SAMPLE_A]]
            with zipfile.ZipFile(source_path, 'w') as zf:
                for info, data in members:
                    zf.writestr(info, data)
            source_file, target_file = source_path.read_bytes(), target_path.read_bytes()
            app = ProjectBrowser(source_path)
            with patch.object(ProjectSession, '_nearby_digitakt_asset_additions', return_value=([], set())):
                async with app.run_test(size=(140, 50)) as pilot:
                    ui = TuiDriver(self, pilot, app)
                    source = app.session
                    await pilot.press('r')
                    await ui.enter('TEMP NAME')
                    await pilot.press('u')
                    before_redo = copy.deepcopy(source.redo_operations)
                    self.assertTrue(before_redo)
                    await ui.open(target_path)
                    target = app.session
                    await pilot.press('[', 'f2')
                    await ui.pattern('A03')  # Unreferenced pattern may be cut.
                    await pilot.press('x', 'escape', ']', 'f2')
                    await ui.pattern('C01')
                    await pilot.press('p')
                    self.assertIsInstance(app.screen, PatternManagerScreen)
                    self.assertEqual(source.working_raw(), source.base_raw)
                    self.assertEqual(target.working_raw(), target.base_raw)
                    self.assertFalse(source.operations)
                    self.assertFalse(target.operations)
                    self.assertEqual(source.redo_operations, before_redo)
                    self.assertEqual(app._dsm_clipboard['mode'], 'cut')
                    await pilot.press('escape')
                    await ui.quit()
            self.assertEqual(source_path.read_bytes(), source_file)
            self.assertEqual(target_path.read_bytes(), target_file)

    async def test_pattern_clipboard_between_tabs_copies_unsaved_edits_and_moves_unreferenced_pattern(self):
        for device in ('DN2', 'DT2'):
            with self.subTest(device=device), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                source_path = write_fixture(root, device)
                target_path = write_fixture(root, device, False)
                original_source, original_target = source_path.read_bytes(), target_path.read_bytes()
                app = ProjectBrowser(source_path)
                async with app.run_test(size=(140, 50)) as pilot:
                    ui = TuiDriver(self, pilot, app)
                    source = app.session
                    await pilot.press('f2', 'r')
                    await ui.enter('UI SOUND')
                    copied_pattern = pattern_bytes(source.working_raw(), 0)
                    await pilot.press('y', 'escape')
                    await ui.open(target_path)
                    target = app.session
                    await pilot.press('f2')
                    await ui.pattern('B04')
                    await pilot.press('p')
                    self.assertEqual(app.session.path, target_path.resolve())
                    if device == 'DN2':
                        self.assertEqual(pattern_bytes(target.working_raw(), 19), copied_pattern)
                        self.assertEqual(kit_bytes(target.working_raw(), 19), kit_bytes(source.working_raw(), 0))
                    else:
                        self.assertEqual(set(pattern_sample_hashes(target.working_raw(), 19)), {SAMPLE_A, SAMPLE_B})
                        self.assert_audio(target, {SAMPLE_A, SAMPLE_B, TARGET_SAMPLE})
                    await pilot.press('escape', '[', 'f2')
                    await ui.pattern('A03')
                    moved_pattern = pattern_bytes(source.working_raw(), 2)
                    moved_kit = kit_bytes(source.working_raw(), 2)
                    await pilot.press('x', 'escape', ']', 'f2')
                    await ui.pattern('C01')
                    await pilot.press('p')
                    self.assertIsNone(app._dsm_clipboard)
                    self.assertEqual(pattern_bytes(source.working_raw(), 2), bytes(PATTERN_STRIDE))
                    self.assertEqual(kit_bytes(source.working_raw(), 2), bytes(kit_stride(source.base_raw)))
                    if device == 'DN2':
                        self.assertEqual(pattern_bytes(target.working_raw(), 32), moved_pattern)
                        self.assertEqual(kit_bytes(target.working_raw(), 32), moved_kit)
                    else:
                        self.assertEqual(set(pattern_sample_hashes(target.working_raw(), 32)), {SAMPLE_A})
                    self.assertEqual(source_path.read_bytes(), original_source)
                    self.assertEqual(target_path.read_bytes(), original_target)
                    await pilot.press('escape')
                    expected_target, expected_source = target.working_raw(), source.working_raw()
                    await ui.save()
                    await pilot.press('[')
                    self.assertIs(app.session, source)
                    await ui.save()
                    await ui.quit()
                self.assertEqual(ProjectSession(source_path).base_raw, expected_source)
                reopened = ProjectSession(target_path)
                self.assertEqual(reopened.base_raw, expected_target)
                self.assertEqual(source_path.with_suffix(source_path.suffix + '.bak').read_bytes(), original_source)
                self.assertEqual(target_path.with_suffix(target_path.suffix + '.bak').read_bytes(), original_target)
                if device == 'DT2':
                    self.assert_audio(reopened, {SAMPLE_A, SAMPLE_B, TARGET_SAMPLE})

    async def test_song_archive_copy_and_cut_remap_patterns_save_both_projects_and_reopen(self):
        for device in ('DN2', 'DT2'):
            with self.subTest(device=device), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                source_path = write_fixture(root, device)
                archive_path = root / f'ARCHIVE.{device.lower()}prj'
                original_source_file = source_path.read_bytes()
                app = ProjectBrowser(source_path)
                async with app.run_test(size=(140, 50)) as pilot:
                    ui = TuiDriver(self, pilot, app)
                    source = app.session
                    source_raw = source.base_raw
                    await pilot.press('y', 'ctrl+n')
                    archive = app.session
                    self.assertTrue(archive.is_new_project)
                    self.assertFalse(archive_path.exists())
                    self.assertTrue(all(not s['rows'] for s in archive.state()['songs']))
                    if device == 'DT2':
                        self.assert_audio(archive, set())
                    await pilot.press('p')
                    self.assertIsInstance(app.screen, SongPatternMappingModal)
                    # A duplicate destination must not stage or close the dialog.
                    await ui.mapping({0: 'B16', 1: 'B16'})
                    self.assertIsInstance(app.screen, SongPatternMappingModal)
                    self.assertFalse(archive.operations)
                    self.assertIn('unique', str(app.screen.query_one('#mapping-error', Static).render()))
                    await ui.mapping({0: 'B16', 1: 'D01'})
                    self.assertNotIsInstance(app.screen, SongPatternMappingModal)
                    archive_raw = archive.working_raw()
                    for before, after in zip(get_song_rows(get_song_slots(source_raw)[0]), get_song_rows(get_song_slots(archive_raw)[0])):
                        self.assertEqual(after[0], {0: 31, 1: 48}[before[0]])
                        self.assertEqual(after[1:], before[1:])
                    for src, dst in ((0, 31), (1, 48)):
                        self.assertEqual(pattern_bytes(archive_raw, dst), pattern_bytes(source_raw, src))
                        self.assertEqual(kit_bytes(archive_raw, dst), kit_bytes(source_raw, src))
                    if device == 'DT2':
                        self.assert_audio(archive, {SAMPLE_A, SAMPLE_B})
                        await pilot.press('f5', 's', 'u', 'escape')
                    await ui.save(archive_path)
                    archive_file = archive_path.read_bytes()
                    self.assertEqual(source_path.read_bytes(), original_source_file)
                    self.assertFalse(source.operations)
                    # Move the source song into another slot of the archive.
                    await pilot.press('[', 'x', ']', 'down', 'p')
                    self.assertIsInstance(app.screen, SongPatternMappingModal)
                    await ui.mapping({0: 'B16', 1: 'D01'})
                    self.assertIsNone(app._dsm_clipboard)
                    self.assertEqual(get_song_rows(get_song_slots(source.working_raw())[0]), [])
                    self.assertEqual(pattern_bytes(source.working_raw(), 0), bytes(PATTERN_STRIDE))
                    self.assertEqual(pattern_bytes(source.working_raw(), 1), pattern_bytes(source_raw, 1))
                    self.assertEqual(len(archive.state()['songs'][1]['rows']), 3)
                    self.assertEqual(source_path.read_bytes(), original_source_file)
                    self.assertEqual(archive_path.read_bytes(), archive_file)
                    if device == 'DT2':
                        self.assert_audio(source, {SAMPLE_A, UNUSED_SAMPLE})
                        self.assert_audio(archive, {SAMPLE_A, SAMPLE_B})
                    await pilot.press('q')
                    self.assertIsInstance(app.screen, UnsavedExitModal)
                    await pilot.press('escape')
                    expected_archive, expected_source = archive.working_raw(), source.working_raw()
                    await ui.save()
                    await pilot.press('[')
                    await ui.save()
                    await ui.quit()
                self.assertEqual(ProjectSession(source_path).base_raw, expected_source)
                reopened = ProjectSession(archive_path)
                self.assertEqual(reopened.base_raw, expected_archive)
                if device == 'DT2':
                    self.assert_audio(reopened, {SAMPLE_A, SAMPLE_B})
                    self.assert_audio(ProjectSession(source_path), {SAMPLE_A, UNUSED_SAMPLE})

    async def test_arrangement_paste_keeps_destination_patterns_sounds_and_samples(self):
        for device in ('DN2', 'DT2'):
            with self.subTest(device=device), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                source_path = write_fixture(root, device)
                target_path = write_fixture(root, device, False)
                original_source_file = source_path.read_bytes()
                app = ProjectBrowser(source_path)
                async with app.run_test(size=(140, 50)) as pilot:
                    ui = TuiDriver(self, pilot, app)
                    source = app.session
                    source_record = get_song_slots(source.base_raw)[0]
                    await pilot.press('y')
                    await ui.open(target_path)
                    target = app.session
                    original_target = target.base_raw
                    await pilot.press('end', 'p')
                    self.assertIsInstance(app.screen, SongPatternMappingModal)
                    await pilot.press('escape')
                    self.assertFalse(target.operations)
                    await pilot.press('p')
                    await pilot.click('#keep')
                    changed = target.working_raw()
                    self.assertEqual(get_song_slots(changed)[15], source_record)
                    self.assertEqual(get_song_slots(changed)[:15], get_song_slots(original_target)[:15])
                    self.assertEqual(changed[:song_table_off(changed)], original_target[:song_table_off(original_target)])
                    if device == 'DT2':
                        self.assert_audio(target, {TARGET_SAMPLE, SAMPLE_B})
                    await ui.save()
                    await ui.quit()
                self.assertEqual(ProjectSession(target_path).base_raw, changed)
                self.assertEqual(source_path.read_bytes(), original_source_file)

    async def test_cross_device_pattern_cut_is_rejected_without_altering_history(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source_path = write_fixture(root, 'DN2')
            target_path = write_fixture(root, 'DT2', False)
            app = ProjectBrowser(source_path)
            async with app.run_test(size=(140, 50)) as pilot:
                ui = TuiDriver(self, pilot, app)
                source = app.session
                await pilot.press('r')
                await ui.enter('TEMP NAME')
                await pilot.press('u')
                before_redo = copy.deepcopy(source.redo_operations)
                await ui.open(target_path)
                target = app.session
                await pilot.press('[', 'f2')
                await ui.pattern('A03')
                await pilot.press('x', 'escape', ']', 'f2')
                await ui.pattern('C01')
                await pilot.press('p')
                self.assertFalse(source.operations)
                self.assertFalse(target.operations)
                self.assertEqual(source.redo_operations, before_redo)
                self.assertEqual(source.working_raw(), source.base_raw)
                self.assertEqual(target.working_raw(), target.base_raw)
                self.assertEqual(app._dsm_clipboard['mode'], 'cut')
                await pilot.press('escape')
                await ui.quit()

    async def test_failed_song_cut_restores_destination_and_both_redo_histories(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source_path = write_fixture(root, 'DT2')
            target_path = write_fixture(root, 'DT2', False)
            source_image = ProjectSession(source_path)
            raw = bytearray(source_image.base_raw)
            # The copied song uses A01/A02, which are valid. An unrelated sketch
            # has an unresolved sample, so safe source-side cleanup must fail.
            offset = KIT_BASE + 2 * kit_stride(raw) + SOUND_BASE + SOUND_SAMPLE_SLOT_OFFSET
            raw[offset:offset + 2] = b'\xff\xff'
            with zipfile.ZipFile(source_path, 'w') as zf:
                for info, data in source_image.members:
                    zf.writestr(info, pack_project(source_image.head, bytes(raw)) if info.filename == source_image.name else data)
            original_source_file, original_target_file = source_path.read_bytes(), target_path.read_bytes()
            app = ProjectBrowser(source_path)
            async with app.run_test(size=(140, 50)) as pilot:
                ui = TuiDriver(self, pilot, app)
                source = app.session
                await pilot.press('r')
                await ui.enter('SOURCE EDIT')
                await pilot.press('u')
                source_redo = copy.deepcopy(source.redo_operations)
                await pilot.press('x')
                await ui.open(target_path)
                target = app.session
                await pilot.press('r')
                await ui.enter('TARGET EDIT')
                await pilot.press('u')
                target_redo = copy.deepcopy(target.redo_operations)
                source_members, target_members = archive_data(source), archive_data(target)
                await pilot.press('p')
                self.assertIsInstance(app.screen, SongPatternMappingModal)
                await ui.mapping({0: 'B16', 1: 'D01'})
                self.assertNotIsInstance(app.screen, SongPatternMappingModal)
                self.assertFalse(source.operations)
                self.assertFalse(target.operations)
                self.assertEqual(source.redo_operations, source_redo)
                self.assertEqual(target.redo_operations, target_redo)
                self.assertEqual(source.working_raw(), source.base_raw)
                self.assertEqual(target.working_raw(), target.base_raw)
                self.assertEqual(archive_data(source), source_members)
                self.assertEqual(archive_data(target), target_members)
                self.assertEqual(app._dsm_clipboard['mode'], 'cut')
                await ui.quit()
            self.assertEqual(source_path.read_bytes(), original_source_file)
            self.assertEqual(target_path.read_bytes(), original_target_file)
