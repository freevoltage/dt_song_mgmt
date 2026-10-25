"""Constants for Digitakt II / Digitone II project format."""
from __future__ import annotations

MAGIC_TAIL = bytes.fromhex("bacef00c")
MAGIC_HEAD = bytes.fromhex("beefbace")

SONG_SLOTS = 16
SONG_SIZE = 3072
SONG_TABLE_LEN = SONG_SLOTS * SONG_SIZE
LZ4_BLOCK = 32768

PAYLOAD_HEAD_LEN = 31
PAYLOAD_TAIL_LEN = 12
PAYLOAD_WRAP_LEN = PAYLOAD_HEAD_LEN + PAYLOAD_TAIL_LEN
UNCOMP_SIZE_OFF = 25

PROJECT_NAME_LEN = 13
SONG_NAME_LEN = 16
SONG_NAME_OFF = 4
SONG_ROW_OFF = 0x14
SONG_ROW_SIZE = 0x1D  # 29
SONG_ROW_MAX = 99
SONG_ROW_COUNT_OFF = 0x0B4B
SONG_TEMPO_OFF = 0x0B50
SONG_TRACKS = 16
BPM_SCALE = 120

SONG_ROW_LABELS: tuple[str | None, ...] = (
    None,
    None,
    "INTRO",
    "OUTRO",
    "CHORUS",
    "SOLO",
    "FILL",
    "PEAK",
    "JAM",
    "NOISE",
    "MISC",
    "PAUSE",
)

PATTERN_SLOTS = 128
PATTERN_BASE = 0x200
PATTERN_STRIDE = 0x15C00
PATTERN_NAME_OFF_DT2 = 0x15AA4
PATTERN_NAME_OFF_DN2 = 0x15AD4
# Backwards-compatible default for callers that do not have project context.
PATTERN_NAME_OFF = PATTERN_NAME_OFF_DT2
PATTERN_NAME_LEN = 16

def device_name(raw: bytes) -> str:
    """Identify the project family from the first pattern container version."""
    if len(raw) >= PATTERN_BASE + 4:
        version = int.from_bytes(raw[PATTERN_BASE:PATTERN_BASE + 4], "big")
        if version == 3:
            return "DN2"
        if version == 4:
            return "DT2"
    # Older or unusual images: preserve historical Digitakt behavior.
    return "DT2"

def pattern_name_offset(raw: bytes) -> int:
    return PATTERN_NAME_OFF_DN2 if device_name(raw) == "DN2" else PATTERN_NAME_OFF_DT2

PAYLOAD_HEAD_MAGIC = bytes.fromhex("ac11d303")
PAYLOAD_TAIL_MAGIC = bytes.fromhex("aaa1daaa")

NAME_CHAR = set("ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_~ -#$")
