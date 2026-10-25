"""Payload and block stream handling."""
from __future__ import annotations

import struct
import zlib

from .constants import PAYLOAD_HEAD_LEN, PAYLOAD_TAIL_LEN, PAYLOAD_TAIL_MAGIC, PAYLOAD_HEAD_MAGIC, UNCOMP_SIZE_OFF
from .lz4 import lz4_compress_block, lz4_decompress_block


def payload_crc32(data: bytes) -> int:
    """CRC-32 of the compressed stream (chunk lengths, LZ4 blocks, null terminator)."""
    return zlib.crc32(data, 0xFFFFFFFF) & 0xFFFFFFFF


def unwrap_payload(payload: bytes) -> tuple[bytes, list[bytes]]:
    if len(payload) < PAYLOAD_HEAD_LEN + PAYLOAD_TAIL_LEN:
        raise ValueError("payload too short for Transfer wrapper")
    if payload[:4] != PAYLOAD_HEAD_MAGIC:
        raise ValueError("payload missing Transfer head magic (ac11d303)")
    if payload[-4:] != PAYLOAD_TAIL_MAGIC:
        raise ValueError("payload missing Transfer tail magic (aaa1daaa)")
    i = PAYLOAD_HEAD_LEN
    blocks: list[bytes] = []
    end = len(payload) - PAYLOAD_TAIL_LEN
    while i + 4 <= end:
        n = struct.unpack_from(">I", payload, i)[0]
        i += 4
        if n == 0:
            return payload[:PAYLOAD_HEAD_LEN], blocks
        if n < 0 or i + n > end:
            raise ValueError("payload chunk list is corrupt")
        blocks.append(payload[i : i + n])
        i += n
    raise ValueError("payload chunk list is corrupt (no terminating 0-length chunk)")


def decompress_blocks(blocks: list[bytes]) -> bytes:
    out = bytearray()
    for b in blocks:
        lz4_decompress_block(b, out)
    return bytes(out)


def compress_raw(raw: bytes) -> list[bytes]:
    from .constants import LZ4_BLOCK
    blocks = []
    for i in range(0, len(raw), LZ4_BLOCK):
        blocks.append(lz4_compress_block(raw[i : i + LZ4_BLOCK]))
    return blocks


def wrap_payload(head: bytes, blocks: list[bytes]) -> bytes:
    if len(head) < PAYLOAD_HEAD_LEN:
        raise ValueError("Transfer head too short")
    body = b"".join(struct.pack(">I", len(c)) + c for c in blocks) + struct.pack(">I", 0)
    crc = payload_crc32(body)
    return head[:PAYLOAD_HEAD_LEN] + body + struct.pack(">I", crc) + struct.pack(">I", len(body)) + PAYLOAD_TAIL_MAGIC


def set_uncompressed_size(head: bytes, size: int) -> bytes:
    h = bytearray(head[:PAYLOAD_HEAD_LEN])
    if len(h) < UNCOMP_SIZE_OFF + 4:
        raise ValueError("Transfer head too short for uncompressed size")
    struct.pack_into(">I", h, UNCOMP_SIZE_OFF, size)
    return bytes(h)
