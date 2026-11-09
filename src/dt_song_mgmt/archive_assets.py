"""Apply reversible sample-file changes to an Elektron project archive."""

from __future__ import annotations

import base64
import copy
import json
import zipfile
from pathlib import PurePosixPath


def _sample_hash(value) -> int | None:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return None
    return parsed if parsed >= 0 else None


def _decode_addition(addition: dict) -> tuple[dict, bytes, zipfile.ZipInfo | None]:
    entry = addition.get("entry", addition.get("manifest_entry"))
    if not isinstance(entry, dict):
        raise ValueError("sample addition must include a manifest entry")
    if "data" in addition:
        data = addition["data"]
        if not isinstance(data, bytes):
            raise ValueError("sample addition data must be bytes")
    elif "data_base64" in addition:
        try:
            data = base64.b64decode(addition["data_base64"], validate=True)
        except (ValueError, TypeError):
            raise ValueError("sample addition base64 data is invalid") from None
    else:
        raise ValueError("sample addition is missing file data")
    try:
        expected_size = int(entry["FileSize"])
    except (KeyError, TypeError, ValueError):
        raise ValueError("sample addition has a missing or invalid FileSize") from None
    # Elektron FileSize is sample payload metadata, not the archive WAV's
    # byte length. WAV headers/chunks make the actual member larger.
    if expected_size < 0 or not data:
        raise ValueError("sample addition has invalid size metadata or empty file data")
    info = addition.get("zipinfo")
    if info is not None and not isinstance(info, zipfile.ZipInfo):
        raise ValueError("sample addition zipinfo must be a ZipInfo")
    return dict(entry), data, info


def _unique_name(original: str, occupied: set[str]) -> str:
    path = PurePosixPath(original)
    parent = "" if str(path.parent) == "." else f"{path.parent}/"
    suffix = "".join(path.suffixes)
    stem = path.name[:-len(suffix)] if suffix else path.name
    candidate = original
    counter = 2
    while candidate in occupied:
        candidate = f"{parent}{stem} ({counter}){suffix}"
        counter += 1
    return candidate


def apply_asset_delta(
    members: list[tuple[zipfile.ZipInfo, bytes]],
    additions: list[dict] | None = None,
    removals: set[int] | list[int] | tuple[int, ...] | None = None,
) -> list[tuple[zipfile.ZipInfo, bytes]]:
    """Return archive members after adding/removing manifest-backed samples.

    Additions accept ``{"entry": manifest_sample, "data": bytes}`` or
    ``{"manifest_entry": ..., "data_base64": ...}``. An optional ``zipinfo``
    carries the source member's compression and timestamp metadata.

    Removing a hash also removes its WAV member only when no remaining sample
    manifest entry references that member name. Unrelated files are retained.
    """
    additions = additions or []
    removal_hashes = {_sample_hash(value) for value in (removals or [])}
    removal_hashes.discard(None)

    manifest_rows = [(index, info, data) for index, (info, data) in enumerate(members)
                     if info.filename == "manifest.json"]
    if len(manifest_rows) != 1:
        raise ValueError("project archive must contain exactly one manifest.json")
    manifest_index, manifest_info, manifest_data = manifest_rows[0]
    try:
        manifest = json.loads(manifest_data)
    except (UnicodeDecodeError, json.JSONDecodeError):
        raise ValueError("project manifest is not valid JSON") from None
    if not isinstance(manifest, dict):
        raise ValueError("project manifest must be a JSON object")
    samples = manifest.get("Samples", [])
    if not isinstance(samples, list):
        raise ValueError("project manifest Samples field must be a list")

    removed_names: set[str] = set()
    kept_samples = []
    for sample in samples:
        if not isinstance(sample, dict):
            kept_samples.append(sample)
            continue
        if _sample_hash(sample.get("Hash")) in removal_hashes:
            name = sample.get("FileName")
            if isinstance(name, str) and name:
                removed_names.add(name)
        else:
            kept_samples.append(sample)
    manifest["Samples"] = kept_samples

    # Do not remove a file still referenced by another sample record.
    referenced_names = {
        sample.get("FileName") for sample in kept_samples
        if isinstance(sample, dict) and isinstance(sample.get("FileName"), str)
    }
    output = [
        (copy.copy(info), data)
        for index, (info, data) in enumerate(members)
        if index != manifest_index
        and not (info.filename in removed_names and info.filename not in referenced_names)
    ]

    occupied = {info.filename for info, _ in output}
    existing_hashes = {
        value for value in (_sample_hash(sample.get("Hash")) for sample in kept_samples if isinstance(sample, dict))
        if value is not None
    }
    for addition in additions:
        entry, data, source_info = _decode_addition(addition)
        sample_hash = _sample_hash(entry.get("Hash"))
        if sample_hash is None:
            raise ValueError("sample addition has a missing or invalid Hash")
        if sample_hash in existing_hashes:
            continue
        original_name = entry.get("FileName")
        if not isinstance(original_name, str) or not original_name:
            raise ValueError("sample addition has a missing FileName")
        filename = _unique_name(original_name, occupied)
        entry["FileName"] = filename
        manifest["Samples"].append(entry)

        if source_info is not None:
            new_info = copy.copy(source_info)
            new_info.filename = filename
        else:
            new_info = zipfile.ZipInfo(filename)
            new_info.compress_type = zipfile.ZIP_DEFLATED
        output.append((new_info, data))
        occupied.add(filename)
        existing_hashes.add(sample_hash)

    updated_manifest = (json.dumps(manifest, indent=2, ensure_ascii=False) + "\n").encode("utf-8")
    output.insert(min(manifest_index, len(output)), (copy.copy(manifest_info), updated_manifest))
    return output


__all__ = ["apply_asset_delta"]
