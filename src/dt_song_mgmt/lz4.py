"""LZ4 (raw blocks, 32 KiB, linked on decompress)"""
from __future__ import annotations

import ctypes
import ctypes.util

_LZ4 = None
_LZ4_TRIED = False


def _lz4_lib():
    global _LZ4, _LZ4_TRIED
    if _LZ4_TRIED:
        return _LZ4
    _LZ4_TRIED = True
    path = ctypes.util.find_library("lz4")
    if not path:
        return None
    try:
        lib = ctypes.CDLL(path)
        lib.LZ4_compressBound.argtypes = [ctypes.c_int]
        lib.LZ4_compressBound.restype = ctypes.c_int
        lib.LZ4_compress_default.argtypes = [ctypes.c_char_p, ctypes.c_char_p, ctypes.c_int, ctypes.c_int]
        lib.LZ4_compress_default.restype = ctypes.c_int
        _LZ4 = lib
        return lib
    except Exception:
        return None


def lz4_decompress_block(src: bytes, out: bytearray) -> None:
    i = 0
    n = len(src)
    while i < n:
        token = src[i]
        i += 1
        lit = token >> 4
        if lit == 15:
            while True:
                if i >= n:
                    raise ValueError("truncated LZ4 literal length")
                extra = src[i]
                i += 1
                lit += extra
                if extra != 255:
                    break
        if i + lit > n:
            raise ValueError("truncated LZ4 literals")
        out.extend(src[i : i + lit])
        i += lit
        if i >= n:
            break
        if i + 2 > n:
            raise ValueError("truncated LZ4 match offset")
        offset = src[i] | (src[i + 1] << 8)
        i += 2
        if offset == 0 or offset > len(out):
            raise ValueError(f"bad LZ4 offset {offset} (out {len(out)})")
        mlen = (token & 15) + 4
        if (token & 15) == 15:
            while True:
                if i >= n:
                    raise ValueError("truncated LZ4 match length")
                extra = src[i]
                i += 1
                mlen += extra
                if extra != 255:
                    break
        start = len(out) - offset
        for _ in range(mlen):
            out.append(out[start])
            start += 1


def _lz4_compress_py(src: bytes) -> bytes:
    n = len(src)
    if n == 0:
        return b"\x00"
    HASH_LOG = 12
    HASH_SIZE = 1 << HASH_LOG
    table = [-1] * HASH_SIZE
    out = bytearray()
    i = 0
    anchor = 0

    def hash4(p: int) -> int:
        v = int.from_bytes(src[p : p + 4], "little")
        return ((v * 2654435761) & 0xFFFFFFFF) >> (32 - HASH_LOG)

    def emit(lit_from: int, lit_to: int, match_off: int | None, match_len: int) -> None:
        literals = src[lit_from:lit_to]
        nlit = len(literals)
        token_lit = 15 if nlit >= 15 else nlit
        if match_off is None:
            out.append(token_lit << 4)
            if nlit >= 15:
                rest = nlit - 15
                while rest >= 255:
                    out.append(255)
                    rest -= 255
                out.append(rest)
            out.extend(literals)
            return
        nml = match_len - 4
        token_ml = 15 if nml >= 15 else nml
        out.append((token_lit << 4) | token_ml)
        if nlit >= 15:
            rest = nlit - 15
            while rest >= 255:
                out.append(255)
                rest -= 255
            out.append(rest)
        out.extend(literals)
        out.append(match_off & 0xFF)
        out.append((match_off >> 8) & 0xFF)
        if nml >= 15:
            rest = nml - 15
            while rest >= 255:
                out.append(255)
                rest -= 255
            out.append(rest)

    last_match = n - 12
    while i < last_match:
        h = hash4(i)
        ref = table[h]
        table[h] = i
        if ref < 0 or i - ref >= 65536 or src[ref : ref + 4] != src[i : i + 4]:
            i += 1
            continue
        ml = 4
        while i + ml < n - 5 and src[ref + ml] == src[i + ml]:
            ml += 1
        emit(anchor, i, i - ref, ml)
        i += ml
        anchor = i
        if i < last_match:
            table[hash4(i - 2)] = i - 2
    emit(anchor, n, None, 0)
    return bytes(out)


def lz4_compress_block(src: bytes) -> bytes:
    lib = _lz4_lib()
    if lib is not None:
        bound = lib.LZ4_compressBound(len(src))
        buf = ctypes.create_string_buffer(bound)
        n = lib.LZ4_compress_default(src, buf, len(src), bound)
        if n <= 0:
            raise RuntimeError("lz4 compress failed")
        return buf.raw[:n]
    return _lz4_compress_py(src)
