"""dt_song_mgmt package."""
from __future__ import annotations

from .project import read_project, write_project, unpack_project, pack_project
from .songs import get_song_slots, get_song_rows, get_all_songs_info, retarget_rows, copy_rows, move_rows, set_song_slots
from .patterns import get_all_patterns_info
from .state import get_project_state, apply_operations

__all__ = [
    "read_project",
    "write_project",
    "unpack_project",
    "pack_project",
    "get_song_slots",
    "get_song_rows",
    "get_all_songs_info",
    "retarget_rows",
    "copy_rows",
    "move_rows",
    "set_song_slots",
    "get_all_patterns_info",
    "get_project_state",
    "apply_operations",
]


# Dump/restore functions (from original)
import json
import re
import shutil
import struct
import zipfile
from html import escape
from pathlib import Path

from .constants import SONG_SLOTS, SONG_SIZE, SONG_NAME_OFF, SONG_NAME_LEN, SONG_ROW_OFF, SONG_ROW_SIZE, SONG_ROW_COUNT_OFF, SONG_ROW_MAX, PATTERN_BASE, PATTERN_STRIDE, PATTERN_NAME_OFF, PATTERN_NAME_OFF_DT2, PATTERN_NAME_OFF_DN2, PATTERN_NAME_LEN, SONG_TEMPO_OFF, BPM_SCALE, device_name
from .project import read_project as _read_project, write_project as _write_project, unpack_project as _unpack_project, pack_project as _pack_project, payload_name as _payload_name, patch_project_name as _patch_project_name
from .songs import get_song_slots as _get_song_slots, set_song_slots as _set_song_slots, song_name, parse_song, pattern_label, parse_song_row, collect_pattern_names, mute_pads_html, song_table_off, empty_song_template as _empty_song_template, render_songs_html


def die(msg: str, code: int = 1) -> None:
    import sys
    print(f"dt_song_mgmt: {msg}", file=sys.stderr)
    raise SystemExit(code)


def sanitize(name: str) -> str:
    out = "".join(ch if ch.isalnum() or ch in "~-._" else "_" for ch in name)
    return out.strip("._") or "song"


def slot_index_from_name(path: Path) -> int | None:
    stem = path.stem
    if len(stem) >= 2 and stem[:2].isdigit() and (len(stem) == 2 or stem[2] in "_-."):
        idx = int(stem[:2])
        if 0 <= idx < SONG_SLOTS:
            return idx
    return None


def dump_songs(prj: Path) -> Path:
    _manifest, payload, _ = _read_project(prj)
    _head, raw = _unpack_project(payload)
    start = song_table_off(raw)
    # Keep the extracted song files beside their source project, not in the
    # directory from which the user happened to launch dsm.
    outdir = prj.parent / f"SONGS_{prj.stem}"
    outdir.mkdir(parents=True, exist_ok=True)
    for p in outdir.glob("*.bin"):
        p.unlink()
    used = 0
    slots = []
    for i in range(SONG_SLOTS):
        rec = raw[start + i * SONG_SIZE : start + (i + 1) * SONG_SIZE]
        slots.append(rec)
        name = song_name(rec)
        if name != "EMPTY":
            used += 1
        path = outdir / f"{i:02d}_{sanitize(name)}.bin"
        path.write_bytes(rec)
        print(f"dump  {path.name:40s}  {len(rec):5d} bytes  {name}")
    html_path = outdir / "songs.html"
    html_path.write_text(render_songs_html(prj.stem, slots, collect_pattern_names(raw)), encoding="utf-8")
    print(f"wrote {SONG_SLOTS} slots ({used} named) to {outdir}")
    print(f"wrote {html_path}")
    print(f"uncompressed project {len(raw)} bytes; each slot is {SONG_SIZE} bytes")
    return outdir


def restore_songs(prj: Path, folder: Path, new_name: str | None = None) -> None:
    if not folder.is_dir():
        die(f"not a directory: {folder}")
    bins = sorted(p for p in folder.iterdir() if p.is_file() and p.suffix.lower() == ".bin" and not p.name.startswith("99_"))
    if not bins:
        die(f"no .bin files in {folder}")
    by_slot = {}
    for p in bins:
        idx = slot_index_from_name(p)
        if idx is None:
            die(f"song file name must start with NN_ slot number (00–15): {p.name}")
        if idx in by_slot:
            die(f"duplicate slot {idx:02d}: {by_slot[idx].name} and {p.name}")
        by_slot[idx] = p
    manifest, payload, members = _read_project(prj)
    pname = _payload_name(manifest)
    head, raw = _unpack_project(payload)
    start = song_table_off(raw)
    patched = bytearray(raw)
    old_len = len(payload)
    empty = _empty_song_template(raw, start)
    for idx in range(SONG_SLOTS):
        path = by_slot.get(idx)
        off = start + idx * SONG_SIZE
        if path is None:
            patched[off : off + SONG_SIZE] = empty
            print(f"  slot {idx:02d}  ←  (empty)")
            continue
        blob = path.read_bytes()
        if len(blob) == 0:
            patched[off : off + SONG_SIZE] = empty
            print(f"  slot {idx:02d}  ←  {path.name}  (empty file)")
            continue
        if len(blob) != SONG_SIZE:
            die(f"{path.name} is {len(blob)} bytes, expected {SONG_SIZE}. Re-dump songs with this script")
        patched[off : off + SONG_SIZE] = blob
        print(f"  slot {idx:02d}  ←  {path.name}  {song_name(blob)}")
    new_raw = bytes(patched)
    out_pname = None
    if new_name is not None:
        new_raw, out_pname, old_internal = _patch_project_name(new_raw, new_name)
        print(f"name   {old_internal!r} → {out_pname!r}")
    new_payload = _pack_project(head, new_raw)
    crc = struct.unpack_from(">I", new_payload, len(new_payload) - 12)[0]
    size = struct.unpack_from(">I", new_payload, len(new_payload) - 8)[0]
    if len(new_payload) != old_len:
        print(f"payload length {old_len} → {len(new_payload)}")
    print(f"footer size={size}  crc32={crc:08x}  uncompressed={len(new_raw)}")
    bak = prj.with_suffix(prj.suffix + ".bak")
    shutil.copy2(prj, bak)
    _write_project(prj, members, pname, new_payload, out_pname)
    print(f"backup {bak}")
    print(f"wrote  {prj}")
    missing = [i for i in range(SONG_SLOTS) if i not in by_slot]
    if missing:
        print(f"cleared {len(missing)} missing slot{'s' if len(missing) != 1 else ''} to empty")
