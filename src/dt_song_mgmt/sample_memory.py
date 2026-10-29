"""Digitakt II sample reference and memory analysis."""

from __future__ import annotations

from collections import defaultdict

from .constants import KIT_BASE, KIT_STRIDE_DT2, device_name

DT2_TRACKS = 16
DT2_SOUND_BASE = 0x3C
DT2_SOUND_STRIDE = 1109
# The sound preset stores the manifest sample hash at this offset.
DT2_SAMPLE_HASH_OFFSET = 301


def analyze_sample_memory(raw: bytes, manifest: dict) -> dict:
    """Return sample references grouped by pattern, matched by archive hash.

    Per-pattern values count each unique sample once, even if several tracks
    use it. A sample referenced by multiple patterns is marked as shared.
    """
    if device_name(raw) != "DT2":
        raise ValueError("Sample memory analysis is available for Digitakt II projects")

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

    pattern_samples: dict[int, set[int]] = defaultdict(set)
    pattern_tracks: dict[int, dict[int, list[int]]] = defaultdict(lambda: defaultdict(list))
    for pattern_index in range(128):
        kit = KIT_BASE + pattern_index * KIT_STRIDE_DT2
        for track in range(DT2_TRACKS):
            offset = kit + DT2_SOUND_BASE + track * DT2_SOUND_STRIDE + DT2_SAMPLE_HASH_OFFSET
            sample_hash = int.from_bytes(raw[offset:offset + 4], "big")
            if sample_hash in samples:
                pattern_samples[pattern_index].add(sample_hash)
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
                    "tracks": sorted(pattern_tracks[index][sample_hash]),
                    "pattern_count": len(used_by[sample_hash]),
                    "shared": len(used_by[sample_hash]) > 1,
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
    }


def format_bytes(size: int) -> str:
    """Format byte values in MiB for a readable TUI table."""
    return f"{size / (1024 * 1024):.2f} MiB"
