"""Generated Elektron archives and tiny WAVs shared by integration tests."""
import io
import json
import struct
import wave
import zipfile
from functools import lru_cache

from dt_song_mgmt.constants import (
    DN2_IMAGE_SIZE, DT2_IMAGE_SIZE, KIT_BASE, MAGIC_HEAD, MAGIC_TAIL,
    PATTERN_BASE, PATTERN_STRIDE, PAYLOAD_HEAD_LEN, PAYLOAD_HEAD_MAGIC,
    kit_stride, pattern_name_offset,
)
from dt_song_mgmt.dt2_samples import (
    EMPTY_POOL_ROW, SAMPLE_LOCKS_OFFSET, SAMPLE_LOCK_PARAM_ID,
    SAMPLE_POOL_OFFSET, SAMPLE_POOL_ROW_COUNT, SOUND_BASE, SOUND_SAMPLE_SLOT_OFFSET,
)
from dt_song_mgmt.project import encode_project_name_field, pack_project
from dt_song_mgmt.songs import get_song_slots, rename_song, set_song_rows, set_song_slots

SAMPLE_A, SAMPLE_B, UNUSED_SAMPLE, TARGET_SAMPLE = 0x12345678, 0xA0D9C475, 0x34567890, 0x45678901


def wav_bytes(seed):
    output = io.BytesIO()
    with wave.open(output, 'wb') as audio:
        audio.setparams((1, 2, 48000, 0, 'NONE', 'not compressed'))
        audio.writeframes(struct.pack('<32h', *[seed * i for i in range(32)]))
    return output.getvalue()


AUDIO = {value: wav_bytes(index) for index, value in enumerate((SAMPLE_A, SAMPLE_B, UNUSED_SAMPLE, TARGET_SAMPLE), 1)}
NAMES = {SAMPLE_A: 'Samples/shared.wav', SAMPLE_B: 'Samples/locked.wav',
         UNUSED_SAMPLE: 'Samples/unused.wav', TARGET_SAMPLE: 'Samples/shared.wav'}


def song_row(pattern, repeat, label, mute):
    # Unknown bytes must survive all editing and copying.
    return struct.pack('>BBBIBBH', pattern, repeat - 1, label, 14400, mute & 255, mute >> 8, 64) + bytes(range(160, 178))


@lru_cache(maxsize=4)
def fixture_image(device, source=True):
    raw = bytearray(DN2_IMAGE_SIZE if device == 'DN2' else DT2_IMAGE_SIZE)
    raw[:4], raw[-4:] = MAGIC_HEAD, MAGIC_TAIL
    raw[8:21] = encode_project_name_field('SOURCE' if source else 'TARGET')
    if device == 'DT2':
        raw[SAMPLE_POOL_OFFSET:SAMPLE_POOL_OFFSET + SAMPLE_POOL_ROW_COUNT * 16] = EMPTY_POOL_ROW * SAMPLE_POOL_ROW_COUNT
        hashes = (SAMPLE_A, SAMPLE_B, UNUSED_SAMPLE) if source else (TARGET_SAMPLE, SAMPLE_B)
        for index, value in enumerate(hashes):
            offset = SAMPLE_POOL_OFFSET + index * 16
            raw[offset:offset + 16] = struct.pack('>II', value, 80) + bytes(8)
    stride = kit_stride(raw)
    for index in (0, 1, 2):
        start = PATTERN_BASE + index * PATTERN_STRIDE
        raw[start:start + 4] = (3 if device == 'DN2' else 4).to_bytes(4, 'big')
        raw[start + 4:start + 100] = bytes([index + (1 if source else 51)]) * 96
        name_start = start + pattern_name_offset(raw)
        raw[name_start:name_start + 16] = f'PATTERN {index}'.encode().ljust(16, b'\0')
        kit = KIT_BASE + index * stride
        raw[kit + 8:kit + 40] = bytes([index + (17 if source else 71)]) * 32
        if device == 'DT2':
            selector = kit + SOUND_BASE + SOUND_SAMPLE_SLOT_OFFSET
            raw[selector:selector + 2] = (2).to_bytes(2, 'big')
    if source and device == 'DT2':
        # Only pattern 0 needs B, through sample locks; A is shared by all three.
        lock = PATTERN_BASE + SAMPLE_LOCKS_OFFSET
        raw[lock:lock + 258] = bytes([SAMPLE_LOCK_PARAM_ID, 0]) + b'\xff' * 256
        raw[lock + 2:lock + 6] = b'\x00\x02\x00\x03'
    slots = get_song_slots(bytes(raw))
    rows = [song_row(0, 1, 2, 0x0001), song_row(1, 16, 5, 0x8102), song_row(0, 3, 20, 0xFFFF)]
    slots[0] = rename_song(set_song_rows(slots[0], rows), 'SOURCE SONG' if source else 'TARGET SONG')
    slots[1] = rename_song(set_song_rows(slots[1], [song_row(1, 2, 3, 0)]), 'SHARED SONG')
    return set_song_slots(bytes(raw), slots)


@lru_cache(maxsize=4)
def fixture_payload(device, source=True):
    head = PAYLOAD_HEAD_MAGIC + bytes(PAYLOAD_HEAD_LEN - 4)
    return pack_project(head, fixture_image(device, source))


def write_fixture(folder, device, source=True):
    name = 'SOURCE' if source else 'TARGET'
    target = folder / f'{name}.{device.lower()}prj'
    hashes = ((SAMPLE_A, SAMPLE_B, UNUSED_SAMPLE) if source else (TARGET_SAMPLE, SAMPLE_B)) if device == 'DT2' else ()
    manifest = {'Payload': name, 'Samples': [
        {'FileName': NAMES[value], 'FileSize': 64, 'Hash': str(value)} for value in hashes
    ], 'UnknownMetadata': {'preserve': [1, 2, 3]}}
    with zipfile.ZipFile(target, 'w') as archive:
        archive.writestr('manifest.json', json.dumps(manifest))
        archive.writestr(name, fixture_payload(device, source))
        archive.writestr('extras/keep.bin', b'unknown archive member\x00\xff')
        for value in hashes:
            archive.writestr(NAMES[value], AUDIO[value])
    return target


def archive_data(session):
    return {info.filename: data for info, data in session.working_members()}


def pattern_bytes(raw, index):
    start = PATTERN_BASE + index * PATTERN_STRIDE
    return raw[start:start + PATTERN_STRIDE]


def kit_bytes(raw, index):
    start = KIT_BASE + index * kit_stride(raw)
    return raw[start:start + kit_stride(raw)]


