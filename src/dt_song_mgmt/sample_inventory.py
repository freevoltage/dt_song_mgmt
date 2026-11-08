"""Read-only, metadata-only inventory export for Elektron sample libraries."""

from __future__ import annotations

import hashlib
import json
import os
import stat
import zipfile
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath
from typing import BinaryIO

INVENTORY_FORMAT = "dsm-sample-inventory"
INVENTORY_VERSION = 1
CHUNK_SIZE = 1024 * 1024


def export_inventory(source: Path | str, label: str | None = None, exclude: set[Path] | None = None) -> dict:
    """Index a local folder or a Digitakt II project archive."""
    path = Path(source).expanduser().resolve()
    if path.is_dir():
        return _index_directory(path, label, exclude or set())
    if path.is_file() and path.suffix.lower() == ".dt2prj":
        return _index_dt2_project(path, label)
    raise ValueError("source must be a folder or a .dt2prj project archive")


def _index_directory(root: Path, label: str | None, exclude: set[Path]) -> dict:
    directories: list[dict] = [{"path": ".", "kind": "directory"}]
    files: list[dict] = []
    errors: list[dict] = []
    exclude_resolved = {item.resolve() for item in exclude}

    def on_walk_error(exc: OSError) -> None:
        failing_path = Path(exc.filename) if exc.filename else root
        errors.append({"path": _relative_path(root, failing_path), "error": _error_text(exc)})

    for current_text, dirnames, filenames in os.walk(root, topdown=True, followlinks=False, onerror=on_walk_error):
        current = Path(current_text)
        dirnames.sort(key=str.casefold)
        filenames.sort(key=str.casefold)

        kept_dirs = []
        for name in dirnames:
            child = current / name
            rel = _relative_path(root, child)
            try:
                info = child.lstat()
            except OSError as exc:
                errors.append({"path": rel, "error": _error_text(exc)})
                continue
            if stat.S_ISLNK(info.st_mode):
                files.append(_symlink_record(root, child, info, errors))
            else:
                directories.append({"path": rel, "kind": "directory"})
                kept_dirs.append(name)
        dirnames[:] = kept_dirs

        for name in filenames:
            item = current / name
            if item.resolve() in exclude_resolved:
                continue
            rel = _relative_path(root, item)
            try:
                info = item.lstat()
            except OSError as exc:
                errors.append({"path": rel, "error": _error_text(exc)})
                files.append({"path": rel, "name": name, "kind": "file", "size_bytes": None,
                              "sha256": None, "status": "unreadable"})
                continue
            if stat.S_ISLNK(info.st_mode):
                files.append(_symlink_record(root, item, info, errors))
            elif stat.S_ISREG(info.st_mode):
                files.append(_hash_path(item, rel, name, info, errors))
            else:
                files.append({
                    "path": rel,
                    "name": name,
                    "extension": item.suffix.lower(),
                    "kind": "special_file",
                    "size_bytes": info.st_size,
                    "sha256": None,
                    "status": "unsupported_file_type",
                })

    directories.sort(key=lambda item: item["path"].casefold())
    files.sort(key=lambda item: (item["path"].casefold(), item["path"]))
    errors.sort(key=lambda item: (item["path"].casefold(), item["path"]))
    return _inventory("folder", label or root.name, directories, files, errors)


def _hash_path(path: Path, relative: str, name: str, before: os.stat_result, errors: list[dict]) -> dict:
    record = {
        "path": relative,
        "name": name,
        "extension": path.suffix.lower(),
        "kind": "file",
        "size_bytes": before.st_size,
        "sha256": None,
        "status": "indexed",
    }
    try:
        with path.open("rb") as stream:
            digest, bytes_read = _hash_stream(stream)
            after = os.fstat(stream.fileno())
        if bytes_read != before.st_size or _stat_identity(before) != _stat_identity(after):
            record["status"] = "changed_during_read"
            errors.append({"path": relative, "error": "file changed while it was being hashed"})
        else:
            record["sha256"] = digest
    except OSError as exc:
        record["status"] = "unreadable"
        errors.append({"path": relative, "error": _error_text(exc)})
    return record


def _symlink_record(root: Path, path: Path, info: os.stat_result, errors: list[dict]) -> dict:
    rel = _relative_path(root, path)
    record = {
        "path": rel,
        "name": path.name,
        "extension": path.suffix.lower(),
        "kind": "symlink",
        "size_bytes": info.st_size,
        "sha256": None,
        "status": "not_followed",
    }
    try:
        record["link_target"] = os.readlink(path)
    except OSError as exc:
        errors.append({"path": rel, "error": _error_text(exc)})
    return record


def _index_dt2_project(project_path: Path, label: str | None) -> dict:
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
                    if not info.filename.startswith("Samples/"):
                        continue
                    name = _archive_path(info.filename.rstrip("/"))
                    _add_directory_and_parents(directories, name)
                elif info.filename.startswith("Samples/") or info.filename in manifest_by_path:
                    infos_by_path.setdefault(_archive_path(info.filename), []).append(info)
                    _add_parent_directories(directories, _archive_path(info.filename))

            all_sample_paths = set(manifest_by_path) | set(infos_by_path)
            for member_path in sorted(all_sample_paths, key=lambda value: (value.casefold(), value)):
                manifest_entries = manifest_by_path.get(member_path, [])
                matching_infos = infos_by_path.get(member_path, [])
                record = _archive_file_record(member_path, manifest_entries)
                if not matching_infos:
                    record["status"] = "missing_member"
                    record["sha256"] = None
                    errors.append({"path": member_path, "error": "listed in manifest but absent from project archive"})
                elif len(matching_infos) > 1:
                    record["status"] = "ambiguous_member"
                    record["sha256"] = None
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
        raise ValueError(f"not a readable .dt2prj ZIP archive: {project_path}") from None

    directories_out = [{"path": value, "kind": "directory"} for value in directories]
    directories_out.sort(key=lambda item: (item["path"].casefold(), item["path"]))
    files = sorted(files_by_path.values(), key=lambda item: (item["path"].casefold(), item["path"]))
    errors.sort(key=lambda item: (item["path"].casefold(), item["path"]))
    return _inventory("dt2prj", label or project_path.name, directories_out, files, errors)


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
        # Preserve the familiar single-entry fields for simple consumers.
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


def _inventory(source_kind: str, label: str, directories: list[dict], files: list[dict], errors: list[dict]) -> dict:
    return {
        "format": INVENTORY_FORMAT,
        "version": INVENTORY_VERSION,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "source": {"kind": source_kind, "label": label},
        "directories": directories,
        "files": files,
        "errors": errors,
        "summary": {
            "directory_count": len(directories),
            "file_count": len(files),
            "hashed_file_count": sum(item.get("sha256") is not None for item in files),
            "error_count": len(errors),
        },
    }


def write_inventory(inventory: dict, destination: Path | str) -> Path:
    """Write an inventory JSON file atomically."""
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


def _relative_path(root: Path, path: Path) -> str:
    try:
        return path.relative_to(root).as_posix() or "."
    except ValueError:
        return path.name


def _stat_identity(info: os.stat_result) -> tuple[int, int, int, int, int]:
    return info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns, info.st_ctime_ns


def _optional_int(value) -> int | None:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _error_text(exc: BaseException) -> str:
    return str(exc) or exc.__class__.__name__


__all__ = ["export_inventory", "write_inventory"]
