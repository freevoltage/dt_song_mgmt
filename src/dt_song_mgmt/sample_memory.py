"""Digitakt II sample reference and memory analysis."""

from __future__ import annotations

from collections import defaultdict

from .constants import KIT_BASE, KIT_STRIDE_DT2, PATTERN_BASE, PATTERN_STRIDE, device_name

DT2_TRACKS = 16
DT2_SOUND_BASE = 0x3C
DT2_SOUND_STRIDE = 1109
# The sound preset stores the manifest sample hash at this offset.
DT2_SAMPLE_HASH_OFFSET = 301
DT2_SAMPLE_POOL_OFFSET = 0xDC871F
DT2_SAMPLE_POOL_ROW_SIZE = 16
DT2_SAMPLE_POOL_ROWS = 1024
DT2_PATTERN_SAMPLE_LOCKS_OFFSET = 0x10A04
DT2_SAMPLE_LOCK_PARAM_ID = 0x24
DT2_SAMPLE_LOCK_RECORD_SIZE = 258
DT2_SAMPLE_LOCK_RECORDS = 80


def analyze_sample_memory(raw: bytes, manifest: dict) -> dict:
    """Return sample references grouped by pattern, matched by archive hash.

    Per-pattern values count each unique sample once, even if several tracks
    use it. A sample referenced by multiple patterns is marked as shared.
    """
    if device_name(raw) != "DT2":
        raise ValueError("Sample memory analysis is available for Digitakt II projects")

    # The raw project image has a sample pool table even when the Transfer
    # archive omits WAV members (for example, factory or +Drive samples).
    # Prefer manifest names and sizes when available, and use pool metadata as
    # the fallback so sample-locked references remain visible.
    samples: dict[int, dict] = {}
    for item in manifest.get("Samples", []):
        try:
            sample_hash = int(item["Hash"])
            size = int(item["FileSize"])
            name = str(item["FileName"]).rsplit("/", 1)[-1]
        except (KeyError, TypeError, ValueError):
            continue
        if sample_hash >= 0 and size >= 0:
            samples[sample_hash] = {"hash": sample_hash, "name": name, "size": size}

    pool: list[dict | None] = []
    for row in range(DT2_SAMPLE_POOL_ROWS):
        offset = DT2_SAMPLE_POOL_OFFSET + row * DT2_SAMPLE_POOL_ROW_SIZE
        if offset + DT2_SAMPLE_POOL_ROW_SIZE > len(raw):
            break
        sample_hash = int.from_bytes(raw[offset:offset + 4], "big")
        size = int.from_bytes(raw[offset + 4:offset + 8], "big")
        if sample_hash == 0 or size == 0:
            pool.append(None)
            continue
        pool.append({"hash": sample_hash, "size": size, "slot": row + 1})
        current = samples.get(sample_hash)
        manifest_entry = current or {}
        samples[sample_hash] = {
            "hash": sample_hash,
            "name": manifest_entry.get("name", f"POOL {row + 1:03} · {sample_hash:08X}"),
            "size": manifest_entry.get("size", size),
        }

    pattern_samples: dict[int, set[int]] = defaultdict(set)
    pattern_tracks: dict[int, dict[int, list[int]]] = defaultdict(lambda: defaultdict(list))
    pattern_locked: dict[int, set[int]] = defaultdict(set)
    for pattern_index in range(128):
        kit = KIT_BASE + pattern_index * KIT_STRIDE_DT2
        for track in range(DT2_TRACKS):
            offset = kit + DT2_SOUND_BASE + track * DT2_SOUND_STRIDE + DT2_SAMPLE_HASH_OFFSET
            sample_hash = int.from_bytes(raw[offset:offset + 4], "big")
            if sample_hash in samples:
                pattern_samples[pattern_index].add(sample_hash)
                pattern_tracks[pattern_index][sample_hash].append(track)

        # DT2 sample-select parameter locks store 1-based pool slot values in
        # big-endian u16 step fields. Slot zero means no sample selection.
        lock_base = PATTERN_BASE + pattern_index * PATTERN_STRIDE + DT2_PATTERN_SAMPLE_LOCKS_OFFSET
        for record_index in range(DT2_SAMPLE_LOCK_RECORDS):
            record = lock_base + record_index * DT2_SAMPLE_LOCK_RECORD_SIZE
            if record + DT2_SAMPLE_LOCK_RECORD_SIZE > len(raw):
                break
            if raw[record] != DT2_SAMPLE_LOCK_PARAM_ID:
                continue
            track = raw[record + 1]
            if track >= DT2_TRACKS:
                continue
            for step in range(128):
                slot = int.from_bytes(raw[record + 2 + step * 2:record + 4 + step * 2], "big")
                if slot == 0 or slot > len(pool):
                    continue
                sample = pool[slot - 1]
                if sample is None:
                    continue
                sample_hash = sample["hash"]
                pattern_samples[pattern_index].add(sample_hash)
                pattern_locked[pattern_index].add(sample_hash)
                pattern_tracks[pattern_index][sample_hash].append(track)

    used_by: dict[int, set[int]] = defaultdict(set)
    for pattern_index, hashes in pattern_samples.items():
        for sample_hash in hashes:
            used_by[sample_hash].add(pattern_index)

    patterns = []
    for index in range(128):
        hashes = pattern_samples.get(index, set())
        exclusive = {sample_hash for sample_hash in hashes if len(used_by[sample_hash]) == 1}
        patterns.append({
            "index": index,
            "samples": [
                {
                    **samples[sample_hash],
                    "tracks": sorted(set(pattern_tracks[index][sample_hash])),
                    "pattern_count": len(used_by[sample_hash]),
                    "shared": len(used_by[sample_hash]) > 1,
                    "sample_locked": sample_hash in pattern_locked[index],
                }
                for sample_hash in sorted(hashes, key=lambda value: samples[value]["name"].casefold())
            ],
            "sample_count": len(hashes),
            "referenced_bytes": sum(samples[sample_hash]["size"] for sample_hash in hashes),
            "exclusive_bytes": sum(samples[sample_hash]["size"] for sample_hash in exclusive),
        })

    return {
        "samples": samples,
        "patterns": patterns,
        "project_sample_count": len(samples),
        "project_sample_bytes": sum(sample["size"] for sample in samples.values()),
        "referenced_sample_count": len(used_by),
        "referenced_sample_bytes": sum(samples[sample_hash]["size"] for sample_hash in used_by),
        "unreferenced_sample_count": len(set(samples) - set(used_by)),
        "unreferenced_sample_bytes": sum(samples[sample_hash]["size"] for sample_hash in set(samples) - set(used_by)),
        "shared_sample_count": sum(len(patterns_for_sample) > 1 for patterns_for_sample in used_by.values()),
        "sample_pool_count": sum(entry is not None for entry in pool),
    }


def format_bytes(size: int) -> str:
    """Format byte values in MiB for a readable TUI table."""
    return f"{size / (1024 * 1024):.2f} MiB"
