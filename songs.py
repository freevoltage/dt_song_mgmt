"""Song parsing and editing."""
from __future__ import annotations

import struct

from .constants import (
    BPM_SCALE,
    PATTERN_BASE,
    PATTERN_NAME_LEN,
    PATTERN_NAME_OFF_DT2,
    PATTERN_NAME_OFF_DN2,
    PATTERN_SLOTS,
    PATTERN_STRIDE,
    SONG_NAME_LEN,
    SONG_NAME_OFF,
    SONG_ROW_COUNT_OFF,
    SONG_ROW_MAX,
    SONG_ROW_OFF,
    SONG_ROW_SIZE,
    SONG_SIZE,
    SONG_SLOTS,
    SONG_TABLE_LEN,
    SONG_TEMPO_OFF,
    SONG_TRACKS,
    SONG_ROW_LABELS,
    pattern_name_offset,
)


def song_table_off(raw: bytes) -> int:
    if len(raw) < SONG_TABLE_LEN + 4:
        from .project import die
        die("uncompressed project too short to hold 16 songs")
    if raw[-4:] != b"\xba\xce\xf0\x0c":
        from .project import die
        die("uncompressed project does not end with bacef00c")
    return len(raw) - SONG_TABLE_LEN - 4


def decode_name_field(field: bytes) -> str:
    n = field.find(b"\x00")
    rawf = field if n < 0 else field[:n]
    return rawf.decode("cp1252", errors="replace").strip()


def song_name(rec: bytes) -> str:
    field = rec[SONG_NAME_OFF : SONG_NAME_OFF + SONG_NAME_LEN]
    return decode_name_field(field) or "EMPTY"


def pattern_label(idx: int) -> str:
    if not 0 <= idx <= 127:
        return f"?{idx}"
    return f"{chr(ord('A') + idx // 16)}{(idx % 16) + 1:02d}"


def pattern_name_at(raw: bytes, idx: int) -> str:
    if not 0 <= idx < PATTERN_SLOTS:
        return ""
    off = PATTERN_BASE + idx * PATTERN_STRIDE + pattern_name_offset(raw)
    if off + PATTERN_NAME_LEN > len(raw):
        return ""
    return decode_name_field(raw[off : off + PATTERN_NAME_LEN])


def collect_pattern_names(raw: bytes) -> list[str]:
    return [pattern_name_at(raw, i) for i in range(PATTERN_SLOTS)]


def row_label(tag_id: int, pattern_idx: int, saved_pattern_name: str) -> str:
    if tag_id == 1:
        return saved_pattern_name or pattern_label(pattern_idx)
    if 0 <= tag_id < len(SONG_ROW_LABELS):
        name = SONG_ROW_LABELS[tag_id]
        if name:
            return name
    if tag_id == 0:
        return ""
    return f"T{tag_id}"


def format_length(length: int) -> str:
    if 1000 <= length <= 1024:
        return f"K{length - 1000:02d}"
    return str(length)


def format_bpm(raw: int) -> str:
    if raw == 0:
        return "inherit"
    bpm = raw / BPM_SCALE
    if abs(bpm - round(bpm)) < 1e-6:
        return str(int(round(bpm)))
    return f"{bpm:.2f}"


def song_row_count(rec: bytes) -> int:
    n = 0
    if len(rec) >= SONG_ROW_COUNT_OFF + 2:
        n = struct.unpack_from(">H", rec, SONG_ROW_COUNT_OFF)[0]
        if n > SONG_ROW_MAX:
            n = 0
    if n:
        return n
    for i in range(SONG_ROW_MAX):
        off = SONG_ROW_OFF + i * SONG_ROW_SIZE
        if off + SONG_ROW_SIZE > len(rec):
            return i
        if rec[off : off + SONG_ROW_SIZE] == bytes(SONG_ROW_SIZE):
            return i
    return SONG_ROW_MAX


def parse_song_row(row: bytes, pattern_names: list[str] | None = None) -> dict:
    mute = row[7] | (row[8] << 8)
    length = struct.unpack_from(">H", row, 9)[0]
    if length > 1024:
        swapped = struct.unpack_from("<H", row, 9)[0]
        if 1 <= swapped <= 1024:
            length = swapped
    pat = row[0]
    slot = pattern_label(pat)
    saved = ""
    if pattern_names and 0 <= pat < len(pattern_names):
        saved = pattern_names[pat]
    tag_id = row[1]
    return {
        "pattern": pat,
        "pattern_name": slot,
        "label_idx": tag_id,
        "label": row_label(tag_id, pat, saved),
        "repeat": row[2],
        "bpm_raw": struct.unpack_from(">I", row, 3)[0],
        "mute": mute,
        "mute_mask": mute,
        "length": length,
    }


def parse_song(rec: bytes, pattern_names: list[str] | None = None) -> dict:
    n = song_row_count(rec)
    rows = []
    for i in range(n):
        off = SONG_ROW_OFF + i * SONG_ROW_SIZE
        if off + SONG_ROW_SIZE > len(rec):
            break
        rows.append(parse_song_row(rec[off : off + SONG_ROW_SIZE], pattern_names))
    default_bpm = None
    if len(rec) >= SONG_TEMPO_OFF + 2:
        rawb = struct.unpack_from(">H", rec, SONG_TEMPO_OFF)[0]
        if rawb % BPM_SCALE == 0:
            bpm = rawb // BPM_SCALE
            if 30 <= bpm <= 300:
                default_bpm = bpm
    return {"name": song_name(rec), "rows": rows, "default_bpm": default_bpm}


def mute_pads_html(mute: int) -> str:
    def pad(t: int) -> str:
        muted = bool(mute & (1 << (t - 1)))
        state = "muted" if muted else "live"
        label = "muted" if muted else "live"
        return f'<span class="pad {state}" title="T{t} {label}">{t}</span>'

    upper = "".join(pad(t) for t in range(9, 17))
    lower = "".join(pad(t) for t in range(1, 9))
    return '<td class="mutes"><div class="pads">' f'<div class="pad-row">{upper}</div>' f'<div class="pad-row">{lower}</div>' "</div></td>"


def render_songs_html(title: str, slots: list[bytes], pattern_names: list[str] | None = None) -> str:
    from html import escape

    parsed = [parse_song(rec, pattern_names) for rec in slots]
    toc = []
    sections = []
    for i, song in enumerate(parsed):
        name = song["name"]
        empty = name == "EMPTY" and not song["rows"]
        n_rows = len(song["rows"])
        cls = " empty" if empty else ""
        toc.append(
            f'<a href="#s{i:02d}" class="toc-item{cls}">'
            f"<span class='slot'>{i:02d}</span>"
            f"<span class='nm'>{escape(name)}</span>"
            f"<span class='n'>{n_rows}</span></a>"
        )
        meta = [f"{n_rows} row{'s' if n_rows != 1 else ''}"]
        if song["default_bpm"] is not None:
            meta.append(f"{song['default_bpm']} BPM")
        body = []
        if not song["rows"]:
            body.append('<p class="empty-msg">No rows</p>')
        else:
            body.append(
                "<table><thead><tr>"
                "<th>#</th><th>Pattern</th><th>Repeat</th>"
                "<th>BPM</th><th>Length</th>"
                "<th class='m-label'>Mute</th></tr></thead><tbody>"
            )
            for r_i, row in enumerate(song["rows"], start=1):
                body.append(
                    "<tr>"
                    f"<td class='idx'>{r_i}</td>"
                    f"<td class='pat'>{escape(row['pattern_name'])}</td>"
                    f"<td class='rep'>×{row['repeat']}</td>"
                    f"<td class='bpm'>{escape(format_bpm(row['bpm_raw']))}</td>"
                    f"<td class='len'>{escape(format_length(row['length']))}</td>"
                    f"{mute_pads_html(row['mute'])}</tr>"
                )
            body.append("</tbody></table>")
        sections.append(
            f'<section id="s{i:02d}" class="song{cls}">'
            f"<h2><span class='slot'>{i:02d}</span> {escape(name)} "
            f"<span class='meta'>{escape(' · '.join(meta))}</span></h2>"
            f"{''.join(body)}</section>"
        )

    css = """
:root { color-scheme: dark; }
* { box-sizing: border-box; }
body {
  margin: 0; padding: 24px 28px 48px;
  font: 13px/1.4 ui-monospace, SFMono-Regular, Menlo, Consolas, monospace;
  background: #141414; color: #e6e6e6;
}
h1 { font-size: 16px; font-weight: 650; margin: 0 0 6px; }
.sub { color: #8c8c8c; margin: 0 0 18px; }
nav.toc {
  display: grid; grid-template-columns: repeat(auto-fill, minmax(140px, 1fr));
  gap: 6px; margin: 0 0 28px;
}
.toc-item {
  display: flex; gap: 8px; align-items: baseline;
  padding: 6px 8px; border: 1px solid #2c2c2c; border-radius: 4px;
  color: inherit; text-decoration: none; background: #1a1a1a;
}
.toc-item:hover { border-color: #4a4a4a; }
.toc-item.empty { opacity: 0.45; }
.toc-item .slot, h2 .slot {
  color: #8c8c8c; font-variant-numeric: tabular-nums;
}
.toc-item .nm { flex: 1; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.toc-item .n { color: #6e6e6e; }
section.song {
  margin: 0 0 22px; padding: 14px 16px 16px;
  background: #1b1b1b; border: 1px solid #2a2a2a; border-radius: 6px;
}
section.song.empty { opacity: 0.55; }
h2 { font-size: 14px; font-weight: 650; margin: 0 0 10px; }
h2 .meta { color: #8c8c8c; font-weight: 500; font-size: 12px; }
.empty-msg { color: #8c8c8c; margin: 0; }
table { border-collapse: collapse; width: max-content; max-width: 100%; }
th, td { padding: 3px 8px; text-align: left; white-space: nowrap; }
th { color: #8c8c8c; font-weight: 500; font-size: 11px; }
td.idx { color: #6e6e6e; font-variant-numeric: tabular-nums; vertical-align: middle; }
td.pat { font-weight: 650; vertical-align: middle; }
td.rep, td.bpm, td.len { vertical-align: middle; }
td.mutes { padding: 6px 8px; }
.pads { display: flex; flex-direction: column; gap: 3px; }
.pad-row { display: flex; gap: 3px; }
.pad {
  width: 22px; height: 22px; border-radius: 3px;
  display: flex; align-items: center; justify-content: center;
  font-size: 10px; font-weight: 650; font-variant-numeric: tabular-nums;
}
.pad.live { background: #d4652f; color: #1a0c06; }
.pad.muted { background: #2a2a2a; color: #5a5a5a; }
th.m-label { color: #8c8c8c; font-weight: 500; }
tbody tr:hover td:not(.mutes) { background: #222; }
""".strip()

    return (
        "<!DOCTYPE html>\n<html lang='en'><head><meta charset='utf-8'>"
        f"<title>{escape(title)} songs</title>"
        f"<style>{css}</style></head><body>"
        f"<h1>{escape(title)}</h1>"
        "<p class='sub'>16 song slots — pattern, repeats, BPM, length, mute pads "
        "(9–16 over 1–8; lit = playing, dark = muted).</p>"
        f"<nav class='toc'>{''.join(toc)}</nav>"
        f"{''.join(sections)}</body></html>\n"
    )


def empty_song_template(raw: bytes, start: int) -> bytes:
    for i in range(SONG_SLOTS):
        rec = raw[start + i * SONG_SIZE : start + (i + 1) * SONG_SIZE]
        if song_name(rec) == "EMPTY":
            return rec
    rec = bytearray(SONG_SIZE)
    rec[SONG_TEMPO_OFF : SONG_TEMPO_OFF + 2] = b"\x38\x40"
    return bytes(rec)


def get_song_slots(raw: bytes) -> list[bytes]:
    start = song_table_off(raw)
    slots = []
    for i in range(SONG_SLOTS):
        slots.append(bytes(raw[start + i * SONG_SIZE : start + (i + 1) * SONG_SIZE]))
    return slots


def set_song_slot(raw: bytes, slot_idx: int, slot_rec: bytes) -> bytes:
    patched = bytearray(raw)
    start = song_table_off(raw)
    patched[start + slot_idx * SONG_SIZE : start + (slot_idx + 1) * SONG_SIZE] = slot_rec[:SONG_SIZE].ljust(SONG_SIZE, b"\x00")
    return bytes(patched)


def set_song_slots(raw: bytes, slots: list[bytes]) -> bytes:
    patched = bytearray(raw)
    start = song_table_off(raw)
    for i in range(min(len(slots), SONG_SLOTS)):
        patched[start + i * SONG_SIZE : start + (i + 1) * SONG_SIZE] = slots[i][:SONG_SIZE].ljust(SONG_SIZE, b"\x00")
    return bytes(patched)


def get_song_rows(rec: bytes) -> list[bytearray]:
    count = song_row_count(rec)
    rows = []
    base = SONG_ROW_OFF
    for i in range(min(count, SONG_ROW_MAX)):
        row = bytearray(rec[base + i * SONG_ROW_SIZE : base + (i + 1) * SONG_ROW_SIZE])
        rows.append(row)
    return rows


def set_song_rows(rec: bytes, rows: list[bytes | bytearray]) -> bytes:
    patched = bytearray(rec)
    base = SONG_ROW_OFF
    for i in range(SONG_ROW_MAX):
        start = base + i * SONG_ROW_SIZE
        patched[start : start + SONG_ROW_SIZE] = bytes(SONG_ROW_SIZE)
    count = min(len(rows), SONG_ROW_MAX)
    for i in range(count):
        start = base + i * SONG_ROW_SIZE
        r = bytes(rows[i])
        patched[start : start + min(len(r), SONG_ROW_SIZE)] = r[:SONG_ROW_SIZE]
    patched[SONG_ROW_COUNT_OFF : SONG_ROW_COUNT_OFF + 2] = count.to_bytes(2, "big")
    return bytes(patched)


def rename_song(rec: bytes, name: str) -> bytes:
    patched = bytearray(rec)
    s = name.upper()
    out = []
    for c in s:
        if c.isalnum() or c in "~ -#$":
            out.append(c)
        else:
            out.append("_")
    enc = ("".join(out))[:SONG_NAME_LEN].ljust(SONG_NAME_LEN, "\x00")
    patched[SONG_NAME_OFF : SONG_NAME_OFF + SONG_NAME_LEN] = enc.encode("ascii")
    return bytes(patched)


def retarget_rows(rec: bytes, from_pattern: int | None = None, to_pattern: int | None = None, row_indices: list[int] | None = None) -> bytes:
    rows = get_song_rows(rec)
    for i, row in enumerate(rows):
        if row_indices is not None and i not in row_indices:
            continue
        if from_pattern is not None and row[0] != from_pattern:
            continue
        if to_pattern is not None:
            row[0] = to_pattern & 0x7F
    return set_song_rows(rec, rows)


def copy_rows(src_rec: bytes, dst_rec: bytes, src_indices: list[int] | None = None, dst_position: int = -1, mode: str = "append") -> bytes:
    src_rows = get_song_rows(src_rec)
    dst_rows = get_song_rows(dst_rec)
    if src_indices is None:
        src_indices = list(range(len(src_rows)))
    to_copy = [bytes(src_rows[i]) for i in src_indices if 0 <= i < len(src_rows)]
    if mode == "replace":
        new_rows = list(to_copy)
    elif mode == "insert":
        pos = dst_position if dst_position >= 0 else len(dst_rows)
        new_rows = list(dst_rows)
        for j, r in enumerate(to_copy):
            new_rows.insert(pos + j, bytearray(r))
    else:
        new_rows = list(dst_rows) + [bytearray(r) for r in to_copy]
    return set_song_rows(dst_rec, new_rows)


def move_rows(src_rec: bytes, dst_rec: bytes, src_indices: list[int], dst_position: int = -1, mode: str = "insert") -> tuple[bytes, bytes]:
    src_rows = get_song_rows(src_rec)
    to_move = []
    for i in sorted(set(src_indices), reverse=True):
        if 0 <= i < len(src_rows):
            to_move.insert(0, bytes(src_rows[i]))
            del src_rows[i]
    src_new = set_song_rows(src_rec, src_rows)
    dst_rows = get_song_rows(dst_rec)
    pos = dst_position if dst_position >= 0 else len(dst_rows)
    new_dst = list(dst_rows)
    for j, r in enumerate(to_move):
        new_dst.insert(pos + j, bytearray(r))
    dst_new = set_song_rows(dst_rec, new_dst)
    return src_new, dst_new


def reorder_rows(rec: bytes, new_order: list[int]) -> bytes:
    rows = get_song_rows(rec)
    new_rows = []
    for idx in new_order:
        if 0 <= idx < len(rows):
            new_rows.append(bytes(rows[idx]))
    return set_song_rows(rec, new_rows)


def delete_rows(rec: bytes, indices: list[int]) -> bytes:
    rows = get_song_rows(rec)
    to_del = set(indices)
    new_rows = [bytes(r) for i, r in enumerate(rows) if i not in to_del]
    return set_song_rows(rec, new_rows)


def clear_song(rec: bytes, raw_project: bytes | None = None, start_offset: int | None = None) -> bytes:
    patched = bytearray(rec)
    name = song_name(rec)
    base = SONG_ROW_OFF
    for i in range(SONG_ROW_MAX):
        start = base + i * SONG_ROW_SIZE
        patched[start : start + SONG_ROW_SIZE] = bytes(SONG_ROW_SIZE)
    patched[SONG_ROW_COUNT_OFF : SONG_ROW_COUNT_OFF + 2] = (0).to_bytes(2, "big")
    if name:
        patched = bytearray(rename_song(bytes(patched), name))
    return bytes(patched)


def swap_songs(raw: bytes, slot_a: int, slot_b: int) -> bytes:
    slots = get_song_slots(raw)
    if slot_a < 0 or slot_a >= SONG_SLOTS or slot_b < 0 or slot_b >= SONG_SLOTS:
        return raw
    slots[slot_a], slots[slot_b] = slots[slot_b], slots[slot_a]
    return set_song_slots(raw, slots)


def copy_song_slot(raw: bytes, src_slot: int, dst_slot: int) -> bytes:
    slots = get_song_slots(raw)
    if src_slot < 0 or src_slot >= SONG_SLOTS or dst_slot < 0 or dst_slot >= SONG_SLOTS:
        return raw
    slots[dst_slot] = bytes(slots[src_slot])
    return set_song_slots(raw, slots)


def get_song_info(rec: bytes, pattern_names: list[str] | None = None) -> dict:
    p = parse_song(rec, pattern_names)
    return {"name": p["name"], "row_count": len(p["rows"]), "rows": p["rows"], "default_bpm": p.get("default_bpm")}


def get_all_songs_info(raw: bytes) -> list[dict]:
    pattern_names = collect_pattern_names(raw)
    slots = get_song_slots(raw)
    result = []
    for i, rec in enumerate(slots):
        info = get_song_info(rec, pattern_names)
        info["slot"] = i
        result.append(info)
    return result


def update_row_fields(rec: bytes, row_indices: list[int], updates: dict) -> bytes:
    rows = get_song_rows(rec)
    for idx in row_indices:
        if 0 <= idx < len(rows):
            row = rows[idx]
            if "repeat" in updates and updates["repeat"] is not None:
                row[2] = int(updates["repeat"]) & 0xFF
            if "bpm_raw" in updates and updates["bpm_raw"] is not None:
                struct.pack_into(">I", row, 3, int(updates["bpm_raw"]) & 0xFFFFFFFF)
            if "mute_mask" in updates and updates["mute_mask"] is not None:
                m = int(updates["mute_mask"]) & 0xFFFF
                row[7] = (m >> 8) & 0xFF
                row[8] = m & 0xFF
            if "length" in updates and updates["length"] is not None:
                struct.pack_into(">H", row, 9, int(updates["length"]) & 0xFFFF)
            if "pattern" in updates and updates["pattern"] is not None:
                row[0] = int(updates["pattern"]) & 0x7F
    return set_song_rows(rec, rows)
