"""Pattern operations."""

from .constants import PATTERN_BASE, PATTERN_NAME_LEN, PATTERN_SLOTS, PATTERN_STRIDE, pattern_name_offset
from .songs import get_song_rows, get_song_slots, pattern_label, retarget_rows, set_song_slots


def get_all_patterns_info(raw: bytes) -> list[dict]:
    from .songs import pattern_name_at, collect_pattern_names
    pattern_names = collect_pattern_names(raw)
    slots = get_song_slots(raw)
    # count refs
    ref_counts = [0] * PATTERN_SLOTS
    for s in slots:
        for r in get_song_rows(s):
            if 0 <= r[0] < PATTERN_SLOTS:
                ref_counts[r[0]] += 1
    patterns = []
    for i in range(PATTERN_SLOTS):
        name = pattern_names[i]
        patterns.append({
            "index": i,
            "label": pattern_label(i),
            "name": name,
            "has_custom_name": bool(name.strip()),
            "ref_count": ref_counts[i],
        })
    return patterns


def rename_pattern(raw: bytes, pat_idx: int, name: str) -> bytes:
    if not 0 <= pat_idx < PATTERN_SLOTS:
        raise ValueError("bad pattern index")
    patched = bytearray(raw)
    base = PATTERN_BASE + pat_idx * PATTERN_STRIDE
    cfg_off = base + pattern_name_offset(raw)
    s = name.upper()
    out = []
    for c in s:
        if c.isalnum() or c in "~ -#$":
            out.append(c)
        else:
            out.append("_")
    enc = ("".join(out))[:PATTERN_NAME_LEN].ljust(PATTERN_NAME_LEN, "\x00")
    patched[cfg_off : cfg_off + PATTERN_NAME_LEN] = enc.encode("ascii")
    return bytes(patched)


def copy_pattern_block(raw: bytes, src_idx: int, dst_idx: int) -> bytes:
    if not (0 <= src_idx < PATTERN_SLOTS and 0 <= dst_idx < PATTERN_SLOTS):
        raise ValueError("bad pattern index")
    patched = bytearray(raw)
    base_src = PATTERN_BASE + src_idx * PATTERN_STRIDE
    base_dst = PATTERN_BASE + dst_idx * PATTERN_STRIDE
    patched[base_dst : base_dst + PATTERN_STRIDE] = raw[base_src : base_src + PATTERN_STRIDE]
    return bytes(patched)


def validate_pattern_mapping(mappings: list[dict]) -> list[tuple[int, int]]:
    """Validate source/destination pattern slot pairs and return normalized indices."""
    if not isinstance(mappings, list) or not mappings:
        raise ValueError("select at least one source pattern")
    pairs = []
    destinations = set()
    for item in mappings:
        if not isinstance(item, dict):
            raise ValueError("each pattern mapping must include source and destination slots")
        src_idx, dst_idx = item.get("src_idx"), item.get("dst_idx")
        if isinstance(src_idx, bool) or isinstance(dst_idx, bool):
            raise ValueError("pattern slots must be integers")
        try:
            src_idx, dst_idx = int(src_idx), int(dst_idx)
        except (TypeError, ValueError):
            raise ValueError("pattern slots must be integers") from None
        if not (0 <= src_idx < PATTERN_SLOTS and 0 <= dst_idx < PATTERN_SLOTS):
            raise ValueError("pattern slots must be between 0 and 127")
        if dst_idx in destinations:
            raise ValueError(f"destination pattern {pattern_label(dst_idx)} is mapped more than once")
        destinations.add(dst_idx)
        pairs.append((src_idx, dst_idx))
    return pairs


def copy_pattern_blocks(source_raw: bytes, target_raw: bytes, mappings: list[dict]) -> bytes:
    """Copy complete pattern containers between compatible project images."""
    pairs = validate_pattern_mapping(mappings)
    patched = bytearray(target_raw)
    for src_idx, dst_idx in pairs:
        src_start = PATTERN_BASE + src_idx * PATTERN_STRIDE
        dst_start = PATTERN_BASE + dst_idx * PATTERN_STRIDE
        src_end = src_start + PATTERN_STRIDE
        dst_end = dst_start + PATTERN_STRIDE
        if src_end > len(source_raw) or dst_end > len(patched):
            raise ValueError("project image is too short to contain the selected pattern")
        patched[dst_start:dst_end] = source_raw[src_start:src_end]
    return bytes(patched)


def clear_pattern(raw: bytes, pat_idx: int) -> bytes:
    if not 0 <= pat_idx < PATTERN_SLOTS:
        raise ValueError("bad pattern index")
    patched = bytearray(raw)
    base = PATTERN_BASE + pat_idx * PATTERN_STRIDE
    # keep first few bytes? just zero block
    patched[base : base + PATTERN_STRIDE] = bytes(PATTERN_STRIDE)
    return bytes(patched)


def retarget_all_pattern_refs(raw: bytes, from_pat: int, to_pat: int) -> bytes:
    slots = get_song_slots(raw)
    for i in range(len(slots)):
        slots[i] = retarget_rows(slots[i], from_pattern=from_pat, to_pattern=to_pat)
    return set_song_slots(raw, slots)


def swap_patterns(raw: bytes, pat_a: int, pat_b: int) -> bytes:
    if not (0 <= pat_a < PATTERN_SLOTS and 0 <= pat_b < PATTERN_SLOTS):
        raise ValueError("bad pattern index")
    patched = bytearray(raw)
    base_a = PATTERN_BASE + pat_a * PATTERN_STRIDE
    base_b = PATTERN_BASE + pat_b * PATTERN_STRIDE
    tmp = bytes(patched[base_a : base_a + PATTERN_STRIDE])
    patched[base_a : base_a + PATTERN_STRIDE] = patched[base_b : base_b + PATTERN_STRIDE]
    patched[base_b : base_b + PATTERN_STRIDE] = tmp
    return bytes(patched)


def move_pattern(raw: bytes, src_idx: int, dst_idx: int, also_retarget: bool = True) -> bytes:
    if not (0 <= src_idx < PATTERN_SLOTS and 0 <= dst_idx < PATTERN_SLOTS):
        raise ValueError("bad pattern index")
    new_raw = copy_pattern_block(raw, src_idx, dst_idx)
    if also_retarget:
        new_raw = retarget_all_pattern_refs(new_raw, src_idx, dst_idx)
    return new_raw
