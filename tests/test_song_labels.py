"""Label IDs match the Digitone II hardware-created debug song."""
import unittest

from dt_song_mgmt.songs import parse_song_row, row_label, set_song_rows, update_row_fields, get_song_rows
from dt_song_mgmt.constants import SONG_SIZE
from dt_song_mgmt.tui import ProjectBrowser


class SongLabelTests(unittest.TestCase):
    def test_hardware_labels_and_reserved_id(self):
        labels = ('INTRO', 'OUTRO', 'BRIDGE', 'CHORUS', 'VERSE', 'SOLO', 'FILL',
                  'RISE', 'PEAK', 'DROP', 'BREAK', 'JAM', 'NOISE', 'FX',
                  'FADE', 'MISC', 'PAUSE', 'OTHER')
        ids = [*range(2, 18), 19, 20]
        self.assertEqual([row_label(i, 0, '') for i in ids], list(labels))
        self.assertEqual(row_label(0, 0, 'BEAT'), '')
        self.assertEqual(row_label(1, 0, 'BEAT'), 'BEAT')
        self.assertEqual(row_label(1, 0, ''), 'A01')
        self.assertEqual(row_label(18, 0, ''), 'T18')
        self.assertEqual(ProjectBrowser.ROW_LABEL_OPTIONS, [(0, '(none)'), (1, 'Pattern name'), *zip(ids, labels)])

    def test_each_label_round_trips_without_changing_repeat(self):
        row = bytes.fromhex('00 0f 03 00 00 38 40 00 00 00 10' + ' 00' * 18)
        song = set_song_rows(bytes(SONG_SIZE), [row])
        for label_id in [0, 1, *range(2, 18), 19, 20]:
            with self.subTest(label_id=label_id):
                updated = update_row_fields(song, [0], {'label_idx': label_id})
                result = get_song_rows(updated)[0]
                self.assertEqual(result[2], label_id)
                self.assertEqual(result[:2] + result[3:], row[:2] + row[3:])
                self.assertEqual(parse_song_row(result)['label_idx'], label_id)
