"""Exercise real project archives, staged edits, transfers and save/reopen.

Fixtures are generated and contain no personal projects. Song rows use the
hardware-verified repeat/label layout; other unknown bytes act as sentinels.
"""
import copy
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from dt_song_mgmt.constants import PATTERN_STRIDE, SONG_ROW_OFF, SONG_ROW_SIZE, kit_stride
from dt_song_mgmt.dt2_samples import (
    SAMPLE_LOCKS_OFFSET, SOUND_BASE, SOUND_SAMPLE_SLOT_OFFSET, pattern_sample_hashes,
)
from dt_song_mgmt.project import encode_project_name_field
from dt_song_mgmt.session import ProjectSession
from dt_song_mgmt.songs import get_song_rows, get_song_slots

from tests.project_fixtures import (
    SAMPLE_A, SAMPLE_B, UNUSED_SAMPLE, TARGET_SAMPLE, AUDIO, NAMES,
    write_fixture, archive_data, pattern_bytes, kit_bytes,
)


class ProjectIntegrityTests(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        self.addCleanup(self.folder.cleanup)
        self.root = Path(self.folder.name)

    def test_staged_song_edits_undo_redo_save_and_reopen_preserve_other_bytes(self):
        for device in ('DN2', 'DT2'):
            with self.subTest(device=device):
                path = write_fixture(self.root, device)
                original_file = path.read_bytes()
                session = ProjectSession(path)
                original = session.base_raw
                offset = len(original) - 16 * 3072 - 4 + SONG_ROW_OFF
                session.stage({'type': 'update_rows', 'slot': 0, 'rows': [0],
                               'updates': {'repeat': 16, 'label_idx': 4, 'mute_mask': 0x0201}})
                expected = bytearray(original)
                expected[offset + 1], expected[offset + 2] = 15, 4
                expected[offset + 7:offset + 9] = b'\x01\x02'
                self.assertEqual(session.working_raw(), bytes(expected))
                self.assertEqual(path.read_bytes(), original_file)
                self.assertFalse(path.with_suffix(path.suffix + '.bak').exists())
                self.assertTrue(session.undo())
                self.assertEqual(session.working_raw(), original)
                self.assertTrue(session.redo())
                self.assertEqual(session.working_raw(), bytes(expected))
                backup = session.apply()
                self.assertEqual(backup.read_bytes(), original_file)
                reopened = ProjectSession(path)
                self.assertEqual(reopened.base_raw, bytes(expected))
                self.assertEqual(archive_data(reopened)['extras/keep.bin'], b'unknown archive member\x00\xff')
                self.assertEqual(reopened.manifest['UnknownMetadata'], {'preserve': [1, 2, 3]})
                row = reopened.state()['songs'][0]['rows'][0]
                self.assertEqual((row['repeat'], row['label'], row['mute']), (16, 'BRIDGE', 0x0201))
                self.assertFalse(session.operations)
                self.assertFalse(session.redo_operations)

    def test_pattern_move_retargets_song_rows_and_moves_complete_sound_kit(self):
        path = write_fixture(self.root, 'DN2')
        session = ProjectSession(path)
        original = session.base_raw
        original_file = path.read_bytes()
        session.stage_pattern_move(0, 31)
        moved = session.working_raw()
        self.assertEqual(pattern_bytes(moved, 31), pattern_bytes(original, 0))
        self.assertEqual(kit_bytes(moved, 31), kit_bytes(original, 0))
        self.assertEqual(pattern_bytes(moved, 0), bytes(PATTERN_STRIDE))
        self.assertEqual(kit_bytes(moved, 0), bytes(kit_stride(original)))
        self.assertEqual(pattern_bytes(moved, 1), pattern_bytes(original, 1))
        for old, new in zip(get_song_rows(get_song_slots(original)[0]), get_song_rows(get_song_slots(moved)[0])):
            self.assertEqual(new[0], 31 if old[0] == 0 else old[0])
            self.assertEqual(new[1:], old[1:])
        self.assertEqual(path.read_bytes(), original_file)
        self.assertTrue(session.undo())
        self.assertEqual(session.working_raw(), original)
        self.assertTrue(session.redo())
        session.apply()
        self.assertEqual(ProjectSession(path).base_raw, moved)

    def test_digitone_song_bundle_copies_all_pattern_and_sound_bytes(self):
        source_path = write_fixture(self.root, 'DN2')
        target_path = write_fixture(self.root, 'DN2', False)
        source, target = ProjectSession(source_path), ProjectSession(target_path)
        source_file, target_file = source_path.read_bytes(), target_path.read_bytes()
        # The clipboard must capture unsaved edits from an open source tab.
        source.stage({'type': 'update_rows', 'slot': 0, 'rows': [0], 'updates': {'repeat': 9}})
        source_raw = source.working_raw()
        target.stage_song_bundle_import(source_path, 0, 15, [{'src_idx': 0, 'dst_idx': 31}, {'src_idx': 1, 'dst_idx': 48}],
                                        source_raw, source.working_manifest(), source.working_members())
        copied = target.working_raw()
        for src, dst in ((0, 31), (1, 48)):
            self.assertEqual(pattern_bytes(copied, dst), pattern_bytes(source_raw, src))
            self.assertEqual(kit_bytes(copied, dst), kit_bytes(source_raw, src))
        self.assertEqual(pattern_bytes(copied, 0), pattern_bytes(target.base_raw, 0))
        expected_song = bytearray(get_song_slots(source_raw)[0])
        for index, pat in enumerate((31, 48, 31)):
            expected_song[SONG_ROW_OFF + index * SONG_ROW_SIZE] = pat
        self.assertEqual(get_song_slots(copied)[15], bytes(expected_song))
        self.assertEqual(source_path.read_bytes(), source_file)
        self.assertEqual(target_path.read_bytes(), target_file)
        self.assertTrue(target.undo())
        self.assertEqual(target.working_raw(), target.base_raw)
        self.assertTrue(target.redo())
        target.apply()
        self.assertEqual(ProjectSession(target_path).base_raw, copied)

    def test_digitakt_song_bundle_transfers_audio_locks_and_handles_filename_collisions(self):
        source_path = write_fixture(self.root, 'DT2')
        target_path = write_fixture(self.root, 'DT2', False)
        source, target = ProjectSession(source_path), ProjectSession(target_path)
        source_file = source_path.read_bytes()
        target.stage_song_bundle_import(source_path, 0, 15, [{'src_idx': 0, 'dst_idx': 31}, {'src_idx': 1, 'dst_idx': 48}])
        copied = target.working_raw()
        self.assertEqual(set(pattern_sample_hashes(copied, 31)), {SAMPLE_A, SAMPLE_B})
        self.assertEqual(set(pattern_sample_hashes(copied, 48)), {SAMPLE_A})
        self.assertEqual(set(pattern_sample_hashes(copied, 0)), {TARGET_SAMPLE})
        # Source A selector 2 moves to 4; B reuses destination selector 3.
        expected_pattern = bytearray(pattern_bytes(source.base_raw, 0))
        expected_pattern[SAMPLE_LOCKS_OFFSET + 2:SAMPLE_LOCKS_OFFSET + 6] = b'\x00\x04\x00\x03'
        self.assertEqual(pattern_bytes(copied, 31), bytes(expected_pattern))
        expected_kit = bytearray(kit_bytes(source.base_raw, 0))
        selector = SOUND_BASE + SOUND_SAMPLE_SLOT_OFFSET
        expected_kit[selector:selector + 2] = b'\x00\x04'
        self.assertEqual(kit_bytes(copied, 31), bytes(expected_kit))
        entries = {int(entry['Hash']): entry for entry in target.working_manifest()['Samples']}
        self.assertEqual(set(entries), {SAMPLE_A, SAMPLE_B, TARGET_SAMPLE})
        self.assertNotEqual(entries[SAMPLE_A]['FileName'], entries[TARGET_SAMPLE]['FileName'])
        for value, entry in entries.items():
            self.assertEqual(archive_data(target)[entry['FileName']], AUDIO[value])
        self.assertTrue(target.undo())
        self.assertEqual(target.working_raw(), target.base_raw)
        self.assertEqual(set(int(e['Hash']) for e in target.working_manifest()['Samples']), {SAMPLE_B, TARGET_SAMPLE})
        self.assertTrue(target.redo())
        target.apply()
        reopened = ProjectSession(target_path)
        self.assertEqual(reopened.base_raw, copied)
        for entry in reopened.manifest['Samples']:
            self.assertEqual(archive_data(reopened)[entry['FileName']], AUDIO[int(entry['Hash'])])
        self.assertEqual(source_path.read_bytes(), source_file)

    def test_standalone_pattern_import_keeps_songs_and_transfers_required_assets(self):
        for device in ('DN2', 'DT2'):
            with self.subTest(device=device):
                source_path = write_fixture(self.root, device)
                target_path = write_fixture(self.root, device, False)
                source, target = ProjectSession(source_path), ProjectSession(target_path)
                before_songs = get_song_slots(target.base_raw)
                target.stage_pattern_import(source_path, [{'src_idx': 0, 'dst_idx': 31}])
                changed = target.working_raw()
                self.assertEqual(get_song_slots(changed), before_songs)
                if device == 'DN2':
                    self.assertEqual(pattern_bytes(changed, 31), pattern_bytes(source.base_raw, 0))
                    self.assertEqual(kit_bytes(changed, 31), kit_bytes(source.base_raw, 0))
                else:
                    self.assertEqual(set(pattern_sample_hashes(changed, 31)), {SAMPLE_A, SAMPLE_B})
                    self.assertEqual(set(int(e['Hash']) for e in target.working_manifest()['Samples']),
                                     {SAMPLE_A, SAMPLE_B, TARGET_SAMPLE})
                target.apply()
                reopened = ProjectSession(target_path)
                self.assertEqual(reopened.base_raw, changed)
                for entry in reopened.manifest['Samples']:
                    self.assertEqual(archive_data(reopened)[entry['FileName']], AUDIO[int(entry['Hash'])])

    def test_empty_project_snapshot_restores_patterns_songs_mutes_and_added_audio(self):
        source_path = write_fixture(self.root, 'DT2')
        source = ProjectSession(source_path)
        draft = ProjectSession.empty_draft_from(source)
        self.assertEqual(draft.working_manifest()['Samples'], [])
        self.assertFalse(any(info.filename.startswith('Samples/') for info, _ in draft.working_members()))
        draft.stage_song_bundle_import(source_path, 0, 0, [{'src_idx': 0, 'dst_idx': 0}, {'src_idx': 1, 'dst_idx': 1}])
        expected = draft.working_raw()
        snapshot = json.loads(json.dumps(draft.export_snapshot()))
        restored = ProjectSession.empty_draft_from(source)
        restored.stage_snapshot(snapshot)
        self.assertEqual(restored.working_raw(), expected)
        self.assertEqual(archive_data(restored), archive_data(draft))
        output = self.root / 'ARCHIVE.dt2prj'
        restored.save_as(output)
        reopened = ProjectSession(output)
        expected_named = bytearray(expected)
        expected_named[8:21] = encode_project_name_field('ARCHIVE')
        self.assertEqual(reopened.base_raw, bytes(expected_named))
        self.assertEqual(set(int(e['Hash']) for e in reopened.manifest['Samples']), {SAMPLE_A, SAMPLE_B})
        for entry in reopened.manifest['Samples']:
            self.assertEqual(archive_data(reopened)[entry['FileName']], AUDIO[int(entry['Hash'])])
        self.assertEqual(ProjectSession(source_path).base_raw, source.base_raw)

    def test_song_cut_keeps_shared_patterns_samples_and_undo_restores_removed_audio(self):
        path = write_fixture(self.root, 'DT2')
        session = ProjectSession(path)
        original = session.base_raw
        original_members = archive_data(session)
        session.stage_song_bundle_cut(0)
        cut = session.working_raw()
        self.assertEqual(get_song_rows(get_song_slots(cut)[0]), [])
        self.assertEqual(pattern_bytes(cut, 1), pattern_bytes(original, 1))
        self.assertEqual(pattern_bytes(cut, 0), bytes(PATTERN_STRIDE))
        self.assertEqual(set(int(e['Hash']) for e in session.working_manifest()['Samples']), {SAMPLE_A, UNUSED_SAMPLE})
        self.assertNotIn(NAMES[SAMPLE_B], archive_data(session))
        self.assertTrue(session.undo())
        self.assertEqual(session.working_raw(), original)
        self.assertEqual(archive_data(session), original_members)
        self.assertTrue(session.redo())
        session.apply()
        reopened = ProjectSession(path)
        self.assertEqual(reopened.base_raw, cut)
        self.assertEqual(set(int(e['Hash']) for e in reopened.manifest['Samples']), {SAMPLE_A, UNUSED_SAMPLE})

    def test_invalid_import_or_snapshot_preserves_existing_draft_and_redo(self):
        path = write_fixture(self.root, 'DT2')
        target_path = write_fixture(self.root, 'DT2', False)
        session = ProjectSession(target_path)
        session.stage({'type': 'update_rows', 'slot': 0, 'rows': [0], 'updates': {'repeat': 8}})
        session.stage({'type': 'rename_song', 'slot': 1, 'name': 'RENAMED'})
        session.undo()
        original_raw, original_members = session.working_raw(), archive_data(session)
        original_ops, original_redo = copy.deepcopy(session.operations), copy.deepcopy(session.redo_operations)
        source = ProjectSession(path)
        # Deterministic failure: deliberately absent audio, with no local-library fallback.
        with patch.object(ProjectSession, '_nearby_digitakt_asset_additions', return_value=([], set())):
            with self.assertRaisesRegex(ValueError, 'audio is missing'):
                session.stage_pattern_import(path, [{'src_idx': 0, 'dst_idx': 31}], source.base_raw,
                                             {'Samples': []}, [])
        snapshot = session.export_snapshot()
        snapshot['image_sha256'] = '0' * 64
        with self.assertRaisesRegex(ValueError, 'checksum'):
            session.stage_snapshot(snapshot)
        self.assertEqual(session.operations, original_ops)
        self.assertEqual(session.redo_operations, original_redo)
        self.assertEqual(session.working_raw(), original_raw)
        self.assertEqual(archive_data(session), original_members)

    def test_save_as_overwrite_backs_up_destination_and_preserves_source(self):
        for device in ('DN2', 'DT2'):
            with self.subTest(device=device):
                source_path = write_fixture(self.root, device)
                target_path = write_fixture(self.root, device, False)
                source_bytes, target_bytes = source_path.read_bytes(), target_path.read_bytes()
                session = ProjectSession(source_path)
                session.stage({'type': 'update_rows', 'slot': 0, 'rows': [0], 'updates': {'repeat': 7}})
                expected = bytearray(session.working_raw())
                expected[8:21] = encode_project_name_field('TARGET')
                session.save_as(target_path)
                reopened = ProjectSession(target_path)
                self.assertEqual(reopened.base_raw, bytes(expected))
                self.assertEqual(reopened.name, 'TARGET')
                self.assertEqual(reopened.manifest['Payload'], 'TARGET')
                self.assertEqual(source_path.read_bytes(), source_bytes)
                self.assertEqual(target_path.with_suffix(target_path.suffix + '.bak').read_bytes(), target_bytes)

    def test_cross_device_import_and_incomplete_song_mapping_are_rejected(self):
        source_path = write_fixture(self.root, 'DN2')
        target_path = write_fixture(self.root, 'DT2', False)
        session = ProjectSession(target_path)
        original_file, original = target_path.read_bytes(), session.base_raw
        with self.assertRaises(ValueError):
            session.stage_song_bundle_import(source_path, 0, 15, [{'src_idx': 0, 'dst_idx': 31}, {'src_idx': 1, 'dst_idx': 48}])
        matching_source = write_fixture(self.root, 'DT2')
        with self.assertRaisesRegex(ValueError, 'exactly once'):
            session.stage_song_bundle_import(matching_source, 0, 15, [{'src_idx': 0, 'dst_idx': 31}])
        self.assertFalse(session.operations)
        self.assertEqual(session.working_raw(), original)
        self.assertEqual(target_path.read_bytes(), original_file)

    def test_failed_write_keeps_original_file_and_staged_changes(self):
        path = write_fixture(self.root, 'DN2')
        original_file = path.read_bytes()
        session = ProjectSession(path)
        session.stage({'type': 'rename_song', 'slot': 0, 'name': 'EDITED'})
        expected = session.working_raw()
        with patch('dt_song_mgmt.session.write_project', side_effect=OSError('disk full')):
            with self.assertRaisesRegex(OSError, 'disk full'):
                session.apply()
        self.assertEqual(path.read_bytes(), original_file)
        self.assertEqual(session.working_raw(), expected)
        self.assertTrue(session.operations)

    def test_external_file_change_blocks_save_without_losing_draft(self):
        path = write_fixture(self.root, 'DN2')
        session = ProjectSession(path)
        session.stage({'type': 'rename_song', 'slot': 0, 'name': 'EDITED'})
        draft = session.working_raw()
        # Another application/session changed the archive after opening it.
        with path.open('ab') as archive:
            archive.write(b'external edit')
        external_bytes = path.read_bytes()
        with self.assertRaisesRegex(RuntimeError, 'changed on disk'):
            session.apply()
        self.assertEqual(path.read_bytes(), external_bytes)
        self.assertEqual(session.working_raw(), draft)
        self.assertFalse(path.with_suffix(path.suffix + '.bak').exists())
