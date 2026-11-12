"""Read the trig markers used by the optional pattern preview."""

from .constants import PATTERN_BASE, PATTERN_SLOTS, PATTERN_STRIDE

TRACK_COUNT = 16
STEPS_PER_TRACK = 128
TRACK_STRIDE = {"DT2": 0x4A0, "DN2": 0x4A3}


def pattern_trigs(raw: bytes, pattern_index: int, device: str) -> list[list[bool]]:
    """Return trig markers for 16 tracks, with 128 steps each.

    The low bit of each big-endian step mask is set for note trigs. Other
    bits may be set on empty steps, so a nonzero mask alone is insufficient.
    """
    if device not in TRACK_STRIDE:
        raise ValueError("trig preview supports Digitakt II and Digitone II projects")
    if not 0 <= pattern_index < PATTERN_SLOTS:
        raise ValueError("invalid pattern slot")
    base = PATTERN_BASE + pattern_index * PATTERN_STRIDE + 4
    stride = TRACK_STRIDE[device]
    if base + (TRACK_COUNT - 1) * stride + STEPS_PER_TRACK * 2 > len(raw):
        raise ValueError("project image is too short to read the pattern")
    result = []
    for track in range(TRACK_COUNT):
        start = base + track * stride
        masks = (int.from_bytes(raw[start + step * 2:start + step * 2 + 2], "big") for step in range(STEPS_PER_TRACK))
        result.append([mask != 0xFFFF and bool(mask & 1) for mask in masks])
    return result
