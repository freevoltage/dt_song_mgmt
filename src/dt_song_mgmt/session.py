"""In-memory editing session shared by terminal and web user interfaces."""

from __future__ import annotations

import base64
import hashlib
import shutil
from datetime import datetime, timezone
from pathlib import Path

from .constants import device_name
from .patterns import (
    copy_pattern_blocks,
    get_all_patterns_info,
    validate_pattern_mapping,
)
from .project import pack_project, payload_name, read_project, unpack_project, write_project
from .songs import (
    collect_pattern_names,
    get_all_songs_info,
    get_song_info,
    get_song_slots,
    restore_song_arrangement,
)
from .state import apply_operations


class ProjectSession:
    """A project's staged changes, preview, snapshot, and apply lifecycle."""

    def __init__(self, project_path: Path | str):
        self.path = Path(project_path).expanduser().resolve()
        if not self.path.is_file():
            raise FileNotFoundError(f"not a file: {self.path}")
        self.operations: list[dict] = []
        self._load()

    def _file_fingerprint(self) -> str:
        digest = hashlib.sha256()
        with self.path.open("rb") as source:
            for chunk in iter(lambda: source.read(1024 * 1024), b""):
                digest.update(chunk)
        return digest.hexdigest()

    def _load(self) -> None:
        self.manifest, self.payload, self.members = read_project(self.path)
        self.head, self.base_raw = unpack_project(self.payload)
        self.name = payload_name(self.manifest)
        self.device = device_name(self.base_raw, self.path.suffix)
        self._fingerprint = self._file_fingerprint()

    def stage(self, operation: dict) -> None:
        """Append one operation after validating the resulting working image."""
        candidate = [*self.operations, operation]
        self._apply_staged_operations(self.base_raw, candidate)
        self.operations = candidate

    def replace_operations(self, operations: list[dict]) -> None:
        """Replace the draft atomically, retaining it only if replay succeeds."""
        candidate = list(operations)
        self._apply_staged_operations(self.base_raw, candidate)
        self.operations = candidate

    def discard(self) -> None:
        self.operations.clear()

    def _apply_staged_operations(self, raw: bytes, operations: list[dict]) -> bytes:
        for operation in operations:
            op_type = operation.get("type")
            if op_type == "project_restore":
                if operation.get("backup_format") != "dsm-project-state" or operation.get("version") != 1:
                    raise ValueError("unsupported DSM project backup format")
                if operation.get("device") != device_name(raw, self.path.suffix):
                    raise ValueError("project backup must match the current device type")
                try:
                    restored = base64.b64decode(operation["image_base64"], validate=True)
                except (KeyError, ValueError, TypeError):
                    raise ValueError("project backup image is missing or invalid") from None
                if len(restored) != len(raw) or operation.get("image_length") != len(restored):
                    raise ValueError("project backup image size does not match this project")
                if hashlib.sha256(restored).hexdigest() != operation.get("image_sha256"):
                    raise ValueError("project backup image checksum does not match")
                if device_name(restored, self.path.suffix) != device_name(raw, self.path.suffix):
                    raise ValueError("project backup image is not for the current device type")
                get_song_slots(restored)
                get_all_patterns_info(restored)
                raw = restored
            elif op_type == "arrangement_restore":
                raw = restore_song_arrangement(raw, operation.get("songs"))
            elif op_type == "pattern_import":
                source_path = Path(operation["src_path"]).expanduser().resolve()
                if source_path == self.path:
                    raise ValueError("choose a different source project")
                _manifest, source_payload, _members = read_project(source_path)
                _source_head, source_raw = unpack_project(source_payload)
                if device_name(source_raw, source_path.suffix) != device_name(raw, self.path.suffix):
                    raise ValueError("patterns can only be imported between matching devices")
                raw = copy_pattern_blocks(source_raw, raw, operation.get("mappings"))
            else:
                raw = apply_operations(raw, [operation])
        return raw

    def working_raw(self) -> bytes:
        return self._apply_staged_operations(self.base_raw, self.operations)

    def state(self) -> dict:
        raw = self.working_raw()
        return {
            "project_name": self.name,
            "project_file": self.path.name,
            "device": self.device,
            "songs": get_all_songs_info(raw),
            "patterns": get_all_patterns_info(raw),
            "pending_changes": len(self.operations),
        }

    def preview(self) -> dict:
        new_raw = self.working_raw()
        old_songs = get_all_songs_info(self.base_raw)
        pattern_names = collect_pattern_names(new_raw)
        songs = []
        for index, record in enumerate(get_song_slots(new_raw)):
            info = get_song_info(record, pattern_names)
            info["slot"] = index
            songs.append(info)

        changes = []
        for old, new in zip(old_songs, songs):
            if old == new:
                continue
            changes.append({
                "slot": old["slot"],
                "name_old": old["name"],
                "name_new": new["name"],
                "rows_old": old["row_count"],
                "rows_new": new["row_count"],
                "rows": [
                    {
                        "index": index,
                        "before": old["rows"][index] if index < len(old["rows"]) else None,
                        "after": new["rows"][index] if index < len(new["rows"]) else None,
                    }
                    for index in range(max(len(old["rows"]), len(new["rows"])))
                    if index >= len(old["rows"])
                    or index >= len(new["rows"])
                    or old["rows"][index] != new["rows"][index]
                ],
            })
        return {"ok": True, "changes": changes, "songs": songs, "patterns": get_all_patterns_info(new_raw)}

    def export_snapshot(self) -> dict:
        raw = self.working_raw()
        return {
            "backup_format": "dsm-project-state",
            "version": 1,
            "project_file": self.path.name,
            "project_name": self.name,
            "device": self.device,
            "exported_at": datetime.now(timezone.utc).isoformat(),
            "image_encoding": "base64",
            "image_length": len(raw),
            "image_sha256": hashlib.sha256(raw).hexdigest(),
            "image_base64": base64.b64encode(raw).decode("ascii"),
            "songs": get_all_songs_info(raw),
            "patterns": get_all_patterns_info(raw),
        }

    def stage_snapshot(self, snapshot: dict) -> None:
        """Replace the draft with a validated full project snapshot."""
        operation = {
            "type": "project_restore",
            "backup_format": snapshot.get("backup_format"),
            "version": snapshot.get("version"),
            "project_file": snapshot.get("project_file"),
            "project_name": snapshot.get("project_name"),
            "device": snapshot.get("device"),
            "image_length": snapshot.get("image_length"),
            "image_sha256": snapshot.get("image_sha256"),
            "image_base64": snapshot.get("image_base64"),
        }
        self.replace_operations([operation])

    def stage_pattern_import(self, source_path: Path | str, mappings: list[dict]) -> None:
        source = Path(source_path).expanduser().resolve()
        if source == self.path:
            raise ValueError("choose a different source project")
        pairs = validate_pattern_mapping(mappings)
        self.stage({
            "type": "pattern_import",
            "src_path": str(source),
            "mappings": [{"src_idx": src, "dst_idx": dst} for src, dst in pairs],
        })

    def apply(self) -> Path:
        """Back up and atomically write the current draft to its project file."""
        if not self.operations:
            raise ValueError("there are no staged changes to apply")
        if self._file_fingerprint() != self._fingerprint:
            raise RuntimeError("project file changed on disk since this session started; reload before applying")
        raw = self.working_raw()
        new_payload = pack_project(self.head, raw)
        backup = self.path.with_suffix(self.path.suffix + ".bak")
        shutil.copy2(self.path, backup)
        write_project(self.path, self.members, self.name, new_payload)
        self.operations.clear()
        self._load()
        return backup


__all__ = ["ProjectSession"]
