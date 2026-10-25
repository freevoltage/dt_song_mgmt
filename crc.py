"""CRC32 for payload."""
from __future__ import annotations

import zlib


def payload_crc32(data: bytes) -> int:
    return zlib.crc32(data, 0xFFFFFFFF) & 0xFFFFFFFF
