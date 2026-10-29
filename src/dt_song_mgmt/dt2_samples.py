"""DT2 sample-pool helpers used when moving patterns between projects.

The pool and sample-lock offsets are reverse-engineered from DT2 project
images. In particular, sample-lock slot numbers are treated as 1-based; the
DEV fixture aligns slots 2–4 with pool rows 1–3 and matching kit references.
"""

from __future__ import annotations

from dataclasses import dataclass

from .constants import KIT_BASE, KIT_STRIDE_DT2, PATTERN_BASE, PATTERN_SLOTS, PATTERN_STRIDE

DT2_IMAGE_MIN_SIZE = 0xDD9604
SAMPLE_POOL_OFFSET = 0xDC871F
SAMPLE_POOL_ROW_SIZE = 16
SAMPLE_POOL_ROW_COUNT = 1024
# Confirmed empty sentinel from DEV.dt2prj. Other zero-hash rows are retained
# as occupied because their trailing metadata may be meaningful.
EMPTY_POOL_ROW = bytes(12) + b"\xff" * 4

SOUND_BASE = 0x3C
SOUND_STRIDE = 1109
SOUND_SAMPLE_HASH_OFFSET = 301

SAMPLE_LOCKS_OFFSET = 0x10A04
SAMPLE_LOCK_PARAM_ID = 0x24
SAMPLE_LOCK_RECORD_SIZE = 258
SAMPLE_LOCK_RECORD_COUNT = 80
SAMPLE_LOCK_STEP_COUNT = 128
SAMPLE_LOCK_VALUE_OFFSET = 2


@dataclass(frozen=True)
class SamplePoolRow:
    """A pool row, retaining all original bytes for safe transfers."""

    slot: int  # 1-based slot value stored by a sample lock
    sample_hash: int
    size: int
    data: bytes


def _check_dt2(raw: bytes) -> None:
    if len(raw) < DT2_IMAGE_MIN_SIZE:
        raise ValueError("sample-pool operations require a complete Digitakt II project image")


def sample_pool_rows(raw: bytes) -> list[SamplePoolRow | None]:
    """Read all 1024 sample-pool slots; empty rows are represented by None."""
    _check_dt2(raw)
    rows: list[SamplePoolRow | None] = []
    for index in range(SAMPLE_POOL_ROW_COUNT):
        start = SAMPLE_POOL_OFFSET + index * SAMPLE_POOL_ROW_SIZE
        data = raw[start:start + SAMPLE_POOL_ROW_SIZE]
        if data == EMPTY_POOL_ROW:
            rows.append(None)
            continue
        sample_hash = int.from_bytes(data[:4], "big")
        size = int.from_bytes(data[4:8], "big")
        rows.append(SamplePoolRow(index + 1, sample_hash, size, data))
    return rows


def pattern_sample_lock_slots(raw: bytes, pattern_index: int) -> dict[int, set[int]]:
    """Return sample-lock slot values grouped by track, ignoring empty steps.

    A value of 0 or 0xFFFF is treated as an unset step. Other values are
    validated against the actual pool length by the caller.
    """
    _check_dt2(raw)
    _check_pattern(pattern_index)
    base = PATTERN_BASE + pattern_index * PATTERN_STRIDE + SAMPLE_LOCKS_OFFSET
    refs: dict[int, set[int]] = {}
    for record_index in range(SAMPLE_LOCK_RECORD_COUNT):
        record = base + record_index * SAMPLE_LOCK_RECORD_SIZE
        if raw[record] != SAMPLE_LOCK_PARAM_ID:
            continue
        track = raw[record + 1]
        if track >= 16:
            continue
        for step in range(SAMPLE_LOCK_STEP_COUNT):
            value_offset = record + SAMPLE_LOCK_VALUE_OFFSET + step * 2
            slot = int.from_bytes(raw[value_offset:value_offset + 2], "big")
            if slot in (0, 0xFFFF):
                continue
            refs.setdefault(track, set()).add(slot)
    return refs


def pattern_sample_hashes(raw: bytes, pattern_index: int) -> dict[int, dict]:
    """Enumerate kit-default and sample-lock sample references for a pattern.

    Hashes can appear without a pool row (for example factory samples); such
    references are returned with ``pool_slots=[]`` and ``size=None``. A sample
    lock that points to an empty or out-of-range pool slot fails closed.
    """
    _check_dt2(raw)
    _check_pattern(pattern_index)
    pool = sample_pool_rows(raw)
    result: dict[int, dict] = {}

    kit = KIT_BASE + pattern_index * KIT_STRIDE_DT2
    for track in range(16):
        offset = kit + SOUND_BASE + track * SOUND_STRIDE + SOUND_SAMPLE_HASH_OFFSET
        sample_hash = int.from_bytes(raw[offset:offset + 4], "big")
        if sample_hash == 0:
            continue
        item = result.setdefault(sample_hash, {
            "hash": sample_hash,
            "size": None,
            "default_tracks": set(),
            "locked_tracks": set(),
            "pool_slots": set(),
        })
        item["default_tracks"].add(track)

    for track, slots in pattern_sample_lock_slots(raw, pattern_index).items():
        for slot in slots:
            if slot > len(pool) or pool[slot - 1] is None:
                raise ValueError(
                    f"sample lock in pattern {pattern_index} track {track + 1} "
                    f"references unresolved pool slot {slot}"
                )
            row = pool[slot - 1]
            assert row is not None
            item = result.setdefault(row.sample_hash, {
                "hash": row.sample_hash,
                "size": row.size,
                "default_tracks": set(),
                "locked_tracks": set(),
                "pool_slots": set(),
            })
            if item["size"] is not None and item["size"] != row.size:
                raise ValueError(f"sample hash {row.sample_hash:08X} has conflicting pool sizes")
            item["size"] = row.size
            item["locked_tracks"].add(track)
            item["pool_slots"].add(slot)

    # Add pool metadata for default kit hashes when the hash has an unambiguous
    # single pool row. If duplicate rows disagree, do not guess which one owns
    # the sound's reference.
    for sample_hash, item in result.items():
        matching = [row for row in pool if row is not None and row.sample_hash == sample_hash]
        if not matching:
            continue
        sizes = {row.size for row in matching}
        if len(sizes) > 1:
            raise ValueError(f"default sample hash {sample_hash:08X} has ambiguous pool rows")
        item["size"] = matching[0].size
        item["pool_slots"].update(row.slot for row in matching)
    return result


def remap_pattern_sample_pool(
    source_raw: bytes,
    target_raw: bytes,
    source_pattern: int,
    target_pattern: int,
) -> tuple[bytes, dict[int, int], list[int]]:
    """Ensure target pool rows exist and remap copied locks to target slots.

    The caller should first copy the pattern and kit blocks. This function
    allocates only rows matching the confirmed empty sentinel and copies the entire source row,
    preserving unknown row metadata. Returns updated target bytes, a 1-based
    source-slot to destination-slot mapping, and newly allocated slots.
    """
    _check_dt2(source_raw)
    _check_dt2(target_raw)
    _check_pattern(source_pattern)
    _check_pattern(target_pattern)
    source_pool = sample_pool_rows(source_raw)
    target_pool = sample_pool_rows(target_raw)
    refs_by_track = pattern_sample_lock_slots(source_raw, source_pattern)

    required_slots = sorted({slot for slots in refs_by_track.values() for slot in slots})
    for slot in required_slots:
        if slot > len(source_pool) or source_pool[slot - 1] is None:
            raise ValueError(f"source pattern references unresolved sample-pool slot {slot}")

    # A kit sound names its default sample by hash only. If the source has a
    # pool record for that hash, require one unambiguous row. Lock references
    # identify their source row directly by slot and can preserve duplicates.
    kit = KIT_BASE + source_pattern * KIT_STRIDE_DT2
    default_hashes = set()
    for track in range(16):
        offset = kit + SOUND_BASE + track * SOUND_STRIDE + SOUND_SAMPLE_HASH_OFFSET
        sample_hash = int.from_bytes(source_raw[offset:offset + 4], "big")
        if sample_hash:
            default_hashes.add(sample_hash)

    source_slots_to_copy = set(required_slots)
    for sample_hash in default_hashes:
        candidates = [
            row for row in source_pool
            if row is not None and row.sample_hash == sample_hash
        ]
        if len(candidates) > 1:
            raise ValueError(
                f"default sample hash {sample_hash:08X} has ambiguous source pool rows"
            )
        if candidates:
            source_slots_to_copy.add(candidates[0].slot)

    patched = bytearray(target_raw)
    slot_mapping: dict[int, int] = {}
    allocated: list[int] = []

    for source_slot in sorted(source_slots_to_copy):
        source_row = source_pool[source_slot - 1]
        assert source_row is not None
        # Reuse only an exact full-row match. Equal hashes and sizes can still
        # carry different unknown metadata and must remain separate records.
        exact_matches = [row for row in target_pool if row is not None and row.data == source_row.data]
        if exact_matches:
            destination_slot = exact_matches[0].slot
        else:
            free_index = next(
                (index for index, row in enumerate(target_pool) if row is None),
                None,
            )
            if free_index is None:
                raise ValueError("target sample pool has no confirmed empty slot")
            destination_slot = free_index + 1
            row_offset = SAMPLE_POOL_OFFSET + free_index * SAMPLE_POOL_ROW_SIZE
            patched[row_offset:row_offset + SAMPLE_POOL_ROW_SIZE] = source_row.data
            target_pool[free_index] = SamplePoolRow(
                destination_slot,
                source_row.sample_hash,
                source_row.size,
                source_row.data,
            )
            allocated.append(destination_slot)
        if source_slot in required_slots:
            slot_mapping[source_slot] = destination_slot

    # Rewrite only SAMP lock values in the already copied target pattern.
    source_base = PATTERN_BASE + source_pattern * PATTERN_STRIDE + SAMPLE_LOCKS_OFFSET
    target_base = PATTERN_BASE + target_pattern * PATTERN_STRIDE + SAMPLE_LOCKS_OFFSET
    for record_index in range(SAMPLE_LOCK_RECORD_COUNT):
        source_record = source_base + record_index * SAMPLE_LOCK_RECORD_SIZE
        target_record = target_base + record_index * SAMPLE_LOCK_RECORD_SIZE
        if source_raw[source_record] != SAMPLE_LOCK_PARAM_ID:
            continue
        for step in range(SAMPLE_LOCK_STEP_COUNT):
            value_offset = SAMPLE_LOCK_VALUE_OFFSET + step * 2
            value = int.from_bytes(source_raw[source_record + value_offset:source_record + value_offset + 2], "big")
            mapped = slot_mapping.get(value)
            if mapped is not None:
                patched[target_record + value_offset:target_record + value_offset + 2] = mapped.to_bytes(2, "big")

    return bytes(patched), slot_mapping, allocated


def clear_sample_pool_hashes(raw: bytes, sample_hashes: set[int]) -> bytes:
    """Release confirmed pool rows whose sample hashes are no longer in use.

    A row remains allocated if any pattern's sample lock still points to its
    1-based slot. Callers must derive ``sample_hashes`` from complete pattern
    references so kit-default sample hashes in retained patterns are excluded.
    """
    _check_dt2(raw)
    if not sample_hashes:
        return raw
    pool = sample_pool_rows(raw)
    used_slots: set[int] = set()
    for pattern_index in range(PATTERN_SLOTS):
        for slots in pattern_sample_lock_slots(raw, pattern_index).values():
            for slot in slots:
                if slot > len(pool) or pool[slot - 1] is None:
                    raise ValueError(
                        f"pattern {pattern_index} references unresolved sample-pool slot {slot}; "
                        "cannot safely clean the sample pool"
                    )
                used_slots.add(slot)
    patched = bytearray(raw)
    for row in pool:
        if row is None or row.sample_hash not in sample_hashes or row.slot in used_slots:
            continue
        offset = SAMPLE_POOL_OFFSET + (row.slot - 1) * SAMPLE_POOL_ROW_SIZE
        patched[offset:offset + SAMPLE_POOL_ROW_SIZE] = EMPTY_POOL_ROW
    return bytes(patched)


def _check_pattern(pattern_index: int) -> None:
    if isinstance(pattern_index, bool) or not isinstance(pattern_index, int) or not 0 <= pattern_index < PATTERN_SLOTS:
        raise ValueError("pattern index must be between 0 and 127")


__all__ = [
    "SamplePoolRow",
    "clear_sample_pool_hashes",
    "pattern_sample_hashes",
    "pattern_sample_lock_slots",
    "remap_pattern_sample_pool",
    "sample_pool_rows",
]
