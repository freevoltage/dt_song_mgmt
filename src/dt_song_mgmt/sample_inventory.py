"""Export sample metadata from Digitakt II project archives only."""

from __future__ import annotations

import hashlib
import json
import zipfile
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath
from typing import BinaryIO

INVENTORY_FORMAT = "dsm-digitakt-sample-inventory"
INVENTORY_VERSION = 1
CHUNK_SIZE = 1024 * 1024


def export_inventory(source: Path | str, label: str | None = None) -> dict:
    """Export paths and hashes from a Digitakt II ``.dt2prj`` archive.

    This function intentionally rejects folders and other device/archive types.
    It never scans a mounted device or extracts sample audio.
    """
    project_path = Path(source).expanduser().resolve()
    if project_path.suffix.lower() != ".dt2prj":
        raise ValueError("sample inventory accepts Digitakt II .dt2prj project files only")
    if not project_path.is_file():
        raise ValueError(f"not a Digitakt II project file: {project_path}")
    return _index_dt2_project(project_path, label or project_path.name)


def _index_dt2_project(project_path: Path, label: str) -> dict:
    directories: set[str] = {"."}
    files_by_path: dict[str, dict] = {}
    errors: list[dict] = []
    try:
        with zipfile.ZipFile(project_path, "r") as archive:
            try:
                manifest = json.loads(archive.read("manifest.json"))
            except KeyError:
                raise ValueError("project archive has no manifest.json") from None
            except (UnicodeDecodeError, json.JSONDecodeError):
                raise ValueError("project manifest is not valid JSON") from None
            samples = manifest.get("Samples", []) if isinstance(manifest, dict) else None
            if not isinstance(samples, list):
                raise ValueError("project manifest Samples field must be a list")

            manifest_by_path: dict[str, list[dict]] = {}
            for index, sample in enumerate(samples):
                if not isinstance(sample, dict) or not isinstance(sample.get("FileName"), str):
                    errors.append({"path": f"manifest.json:Samples[{index}]", "error": "invalid sample entry or missing FileName"})
                    continue
                member_path = _archive_path(sample["FileName"])
                manifest_by_path.setdefault(member_path, []).append(sample)
                _add_parent_directories(directories, member_path)

            infos_by_path: dict[str, list[zipfile.ZipInfo]] = {}
            for info in archive.infolist():
                if info.is_dir():
                    if info.filename.startswith("Samples/"):
                        _add_directory_and_parents(directories, _archive_path(info.filename.rstrip("/")))
                elif info.filename.startswith("Samples/") or info.filename in manifest_by_path:
                    member_path = _archive_path(info.filename)
                    infos_by_path.setdefault(member_path, []).append(info)
                    _add_parent_directories(directories, member_path)

            for member_path in sorted(set(manifest_by_path) | set(infos_by_path), key=_path_key):
                manifest_entries = manifest_by_path.get(member_path, [])
                matching_infos = infos_by_path.get(member_path, [])
                record = _archive_file_record(member_path, manifest_entries)
                if not matching_infos:
                    record["status"] = "missing_member"
                    errors.append({"path": member_path, "error": "listed in manifest but absent from project archive"})
                elif len(matching_infos) > 1:
                    record["status"] = "ambiguous_member"
                    record["size_bytes"] = matching_infos[0].file_size
                    errors.append({"path": member_path, "error": "duplicate archive member names; hash not assigned"})
                else:
                    info = matching_infos[0]
                    record["size_bytes"] = info.file_size
                    try:
                        with archive.open(info, "r") as stream:
                            digest, bytes_read = _hash_stream(stream)
                        if bytes_read != info.file_size:
                            record["status"] = "size_mismatch"
                            errors.append({"path": member_path, "error": "archive member size changed while streaming"})
                        else:
                            record["sha256"] = digest
                            expected_sizes = {
                                size for size in (_optional_int(entry.get("FileSize")) for entry in manifest_entries)
                                if size is not None
                            }
                            if expected_sizes and expected_sizes != {info.file_size}:
                                record["status"] = "manifest_size_mismatch"
                                errors.append({"path": member_path, "error": "archive size differs from manifest FileSize"})
                    except (OSError, RuntimeError, zipfile.BadZipFile) as exc:
                        record["status"] = "unreadable"
                        errors.append({"path": member_path, "error": _error_text(exc)})
                files_by_path[member_path] = record
    except zipfile.BadZipFile:
        raise ValueError(f"not a readable Digitakt II .dt2prj ZIP archive: {project_path}") from None

    directories_out = [{"path": value, "kind": "directory"} for value in directories]
    directories_out.sort(key=lambda item: _path_key(item["path"]))
    files = sorted(files_by_path.values(), key=lambda item: _path_key(item["path"]))
    errors.sort(key=lambda item: _path_key(item["path"]))
    return {
        "format": INVENTORY_FORMAT,
        "version": INVENTORY_VERSION,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "source": {"kind": "digitakt_ii_project", "label": label},
        "directories": directories_out,
        "files": files,
        "errors": errors,
        "summary": {
            "directory_count": len(directories_out),
            "file_count": len(files),
            "hashed_file_count": sum(item.get("sha256") is not None for item in files),
            "error_count": len(errors),
        },
    }


def _archive_file_record(path: str, entries: list[dict]) -> dict:
    posix_path = PurePosixPath(path)
    record = {
        "path": path,
        "name": posix_path.name,
        "extension": posix_path.suffix.lower(),
        "kind": "file",
        "size_bytes": None,
        "sha256": None,
        "status": "indexed",
    }
    if entries:
        record["manifest_entries"] = [
            {
                "elektron_hash": str(item.get("Hash")) if item.get("Hash") is not None else None,
                "manifest_size_bytes": _optional_int(item.get("FileSize")),
            }
            for item in entries
        ]
        if len(entries) == 1:
            record["elektron_hash"] = record["manifest_entries"][0]["elektron_hash"]
            record["manifest_size_bytes"] = record["manifest_entries"][0]["manifest_size_bytes"]
    return record


def _hash_stream(stream: BinaryIO) -> tuple[str, int]:
    digest = hashlib.sha256()
    size = 0
    while chunk := stream.read(CHUNK_SIZE):
        digest.update(chunk)
        size += len(chunk)
    return digest.hexdigest(), size


def write_inventory(inventory: dict, destination: Path | str) -> Path:
    """Write inventory JSON atomically."""
    path = Path(destination).expanduser().resolve()
    if not path.parent.is_dir():
        raise ValueError(f"output folder does not exist: {path.parent}")
    temporary = path.with_suffix(path.suffix + ".tmp")
    data = (json.dumps(inventory, indent=2, ensure_ascii=False) + "\n").encode("utf-8")
    try:
        temporary.write_bytes(data)
        temporary.replace(path)
    except OSError:
        temporary.unlink(missing_ok=True)
        raise
    return path


def _archive_path(value: str) -> str:
    return value.replace("\\", "/").lstrip("/")


def _add_parent_directories(directories: set[str], file_path: str) -> None:
    parent = PurePosixPath(file_path).parent
    while str(parent) not in {"", "."}:
        directories.add(str(parent))
        parent = parent.parent
    directories.add(".")


def _add_directory_and_parents(directories: set[str], directory_path: str) -> None:
    if directory_path not in {"", "."}:
        directories.add(directory_path)
        _add_parent_directories(directories, directory_path + "/_entry")
    else:
        directories.add(".")


def _path_key(path: str) -> tuple[str, str]:
    return path.casefold(), path


def _optional_int(value) -> int | None:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _error_text(exc: BaseException) -> str:
    if isinstance(exc, OSError) and exc.strerror:
        return exc.strerror
    return str(exc) or exc.__class__.__name__


__all__ = ["export_inventory", "write_inventory"]
