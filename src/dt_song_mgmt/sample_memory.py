"""Digitakt II sample reference and memory analysis."""

from __future__ import annotations

from collections import defaultdict

from .constants import device_name
from .dt2_samples import pattern_sample_hashes

DT2_SAMPLE_POOL_OFFSET = 0xDC871F
DT2_SAMPLE_POOL_ROW_SIZE = 16
DT2_SAMPLE_POOL_ROWS = 1024
DT2_SAMPLE_RAM_LIMIT_BYTES = 400_000_000
DT2_SAMPLE_SLOT_LIMIT = 1016


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
            path = str(item["FileName"])
            name = path.rsplit("/", 1)[-1]
        except (KeyError, TypeError, ValueError):
            continue
        if sample_hash >= 0 and size >= 0:
            samples[sample_hash] = {"hash": sample_hash, "name": name, "path": path, "size": size, "size_known": True}

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
            "path": manifest_entry.get("path"),
            "size": manifest_entry.get("size", size),
            "size_known": True,
        }

    pattern_samples: dict[int, set[int]] = defaultdict(set)
    pattern_tracks: dict[int, dict[int, list[int]]] = defaultdict(lambda: defaultdict(list))
    pattern_locked: dict[int, set[int]] = defaultdict(set)
    pattern_errors: dict[int, str] = {}
    for pattern_index in range(128):
        try:
            details = pattern_sample_hashes(raw, pattern_index)
        except ValueError as exc:
            pattern_errors[pattern_index] = str(exc)
            continue
        for sample_hash, detail in details.items():
            if sample_hash not in samples:
                samples[sample_hash] = {
                    "hash": sample_hash, "name": f"REFERENCE · {sample_hash:08X}",
                    "path": None, "size": 0, "size_known": False,
                }
            pattern_samples[pattern_index].add(sample_hash)
            pattern_tracks[pattern_index][sample_hash].extend(detail["default_tracks"] | detail["locked_tracks"])
            if detail["locked_tracks"]:
                pattern_locked[pattern_index].add(sample_hash)

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
            "error": pattern_errors.get(index),
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
        "sample_pool_bytes": sum(entry["size"] for entry in pool if entry is not None),
        "pattern_error_count": len(pattern_errors),
    }


def format_bytes(size: int) -> str:
    """Format byte values in MiB for a readable TUI table."""
    return f"{size / (1024 * 1024):.2f} MiB"


def format_project_ram(analysis: dict) -> str:
    """Summarize pool-row sizes using decimal MB; device accounting is unverified."""
    used = analysis["sample_pool_bytes"]
    remaining = max(0, DT2_SAMPLE_RAM_LIMIT_BYTES - used)
    return (
        f"Estimated pool RAM: {used / 1_000_000:.1f} / 400 MB · "
        f"~{remaining / 1_000_000:.1f} MB free · "
        f"slots {analysis['sample_pool_count']} / {DT2_SAMPLE_SLOT_LIMIT:,}"
    )
