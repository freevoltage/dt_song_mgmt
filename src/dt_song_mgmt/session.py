"""In-memory editing session shared by terminal and web user interfaces."""

from __future__ import annotations

import base64
import hashlib
import shutil
from datetime import datetime, timezone
from pathlib import Path

from .constants import (
    KIT_BASE,
    PATTERN_BASE,
    PATTERN_STRIDE,
    SONG_SIZE,
    SONG_SLOTS,
    device_name,
    kit_stride,
)
from .patterns import (
    copy_pattern_blocks,
    get_all_patterns_info,
    validate_pattern_mapping,
)
from .project import (
    pack_project,
    patch_project_name,
    payload_name,
    read_project,
    unpack_project,
    write_project,
)
from .songs import (
    collect_pattern_names,
    get_all_songs_info,
    get_song_info,
    get_song_slots,
    restore_song_arrangement,
    set_song_slots,
)
from .state import apply_operations


class ProjectSession:
    """A project's staged changes, preview, snapshot, and apply lifecycle."""

    def __init__(self, project_path: Path | str):
        self.path = Path(project_path).expanduser().resolve()
        if not self.path.is_file():
            raise FileNotFoundError(f"not a file: {self.path}")
        self.operations: list[dict] = []
        self.redo_operations: list[dict] = []
        self._load()

    def _file_fingerprint(self) -> tuple[int, int, int, int]:
        """Return a cheap signature for detecting edits from another session."""
        stat = self.path.stat()
        return stat.st_dev, stat.st_ino, stat.st_size, stat.st_mtime_ns

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
        self.redo_operations.clear()

    def replace_operations(self, operations: list[dict]) -> None:
        """Replace the draft atomically, retaining it only if replay succeeds."""
        candidate = list(operations)
        self._apply_staged_operations(self.base_raw, candidate)
        self.operations = candidate
        self.redo_operations.clear()

    def undo(self) -> bool:
        """Undo the most recently staged operation, if one exists."""
        if not self.operations:
            return False
        candidate = self.operations[:-1]
        self._apply_staged_operations(self.base_raw, candidate)
        operation = self.operations[-1]
        self.operations = candidate
        self.redo_operations.append(operation)
        return True

    def redo(self) -> bool:
        """Reapply the most recently undone operation, if one exists."""
        if not self.redo_operations:
            return False
        operation = self.redo_operations[-1]
        candidate = [*self.operations, operation]
        self._apply_staged_operations(self.base_raw, candidate)
        self.operations = candidate
        self.redo_operations.pop()
        return True

    def discard(self) -> None:
        self.operations.clear()
        self.redo_operations.clear()

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
            elif op_type == "song_file_restore":
                destination = self._song_slot(operation.get("dst_slot"), "destination")
                try:
                    record = base64.b64decode(operation["song_data"], validate=True)
                except (KeyError, ValueError, TypeError):
                    raise ValueError("song backup data is missing or invalid") from None
                if len(record) != SONG_SIZE:
                    raise ValueError(f"song backup must be exactly {SONG_SIZE} bytes")
                slots = get_song_slots(raw)
                slots[destination] = record
                raw = set_song_slots(raw, slots)
            elif op_type == "song_import":
                source_path = Path(operation["src_path"]).expanduser().resolve()
                if source_path == self.path:
                    raise ValueError("choose a different source project")
                source_raw = self._source_image(operation, source_path)
                if device_name(source_raw, source_path.suffix) != device_name(raw, self.path.suffix):
                    raise ValueError("songs can only be imported between matching devices")
                source_slot = self._song_slot(operation.get("src_slot"), "source")
                destination = self._song_slot(operation.get("dst_slot"), "destination")
                slots = get_song_slots(raw)
                slots[destination] = get_song_slots(source_raw)[source_slot]
                raw = set_song_slots(raw, slots)
            elif op_type == "pattern_import":
                source_path = Path(operation["src_path"]).expanduser().resolve()
                if source_path == self.path:
                    raise ValueError("choose a different source project")
                source_raw = self._source_image(operation, source_path)
                if device_name(source_raw, source_path.suffix) != device_name(raw, self.path.suffix):
                    raise ValueError("patterns can only be imported between matching devices")
                raw = copy_pattern_blocks(source_raw, raw, operation.get("mappings"))
            else:
                raw = apply_operations(raw, [operation])
        return raw

    @staticmethod
    def _song_slot(value, label: str) -> int:
        if isinstance(value, bool) or not isinstance(value, int) or not 0 <= value < SONG_SLOTS:
            raise ValueError(f"{label} song slot must be between 0 and {SONG_SLOTS - 1}")
        return value

    @staticmethod
    def _source_image(operation: dict, source_path: Path) -> bytes:
        if "source_image_base64" in operation:
            try:
                source_raw = base64.b64decode(operation["source_image_base64"], validate=True)
            except (KeyError, ValueError, TypeError):
                raise ValueError("source project snapshot is missing or invalid") from None
            if len(source_raw) != operation.get("source_image_length"):
                raise ValueError("source project snapshot length does not match")
            if hashlib.sha256(source_raw).hexdigest() != operation.get("source_image_sha256"):
                raise ValueError("source project snapshot checksum does not match")
            get_song_slots(source_raw)
            get_all_patterns_info(source_raw)
            return source_raw
        _manifest, source_payload, _members = read_project(source_path)
        _source_head, source_raw = unpack_project(source_payload)
        return source_raw

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
        patterns = get_all_patterns_info(new_raw)
        pattern_stride = kit_stride(new_raw)
        pattern_changes = []
        for index, pattern in enumerate(patterns):
            pat_start = PATTERN_BASE + index * PATTERN_STRIDE
            kit_start = KIT_BASE + index * pattern_stride
            old_pattern = self.base_raw[pat_start : pat_start + PATTERN_STRIDE]
            new_pattern = new_raw[pat_start : pat_start + PATTERN_STRIDE]
            old_kit = self.base_raw[kit_start : kit_start + pattern_stride]
            new_kit = new_raw[kit_start : kit_start + pattern_stride]
            if old_pattern != new_pattern or old_kit != new_kit:
                pattern_changes.append({
                    "index": index,
                    "label": pattern["label"],
                    "name": pattern["name"],
                })
        return {
            "ok": True,
            "changes": changes,
            "songs": songs,
            "patterns": patterns,
            "pattern_changes": pattern_changes,
        }

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

    def stage_pattern_import(
        self,
        source_path: Path | str,
        mappings: list[dict],
        source_raw: bytes | None = None,
    ) -> None:
        source = Path(source_path).expanduser().resolve()
        if source == self.path:
            raise ValueError("choose a different source project")
        pairs = validate_pattern_mapping(mappings)
        operation = {
            "type": "pattern_import",
            "src_path": str(source),
            "mappings": [{"src_idx": src, "dst_idx": dst} for src, dst in pairs],
        }
        if source_raw is not None:
            operation.update({
                "source_image_base64": base64.b64encode(source_raw).decode("ascii"),
                "source_image_length": len(source_raw),
                "source_image_sha256": hashlib.sha256(source_raw).hexdigest(),
            })
        self.stage(operation)

    def stage_song_file_restore(self, dst_slot: int, record: bytes) -> None:
        destination = self._song_slot(dst_slot, "destination")
        if len(record) != SONG_SIZE:
            raise ValueError(f"song backup must be exactly {SONG_SIZE} bytes")
        self.stage({
            "type": "song_file_restore",
            "dst_slot": destination,
            "song_data": base64.b64encode(record).decode("ascii"),
        })

    def stage_song_import(
        self,
        source_path: Path | str,
        src_slot: int,
        dst_slot: int,
        source_raw: bytes | None = None,
    ) -> None:
        source = Path(source_path).expanduser().resolve()
        if source == self.path:
            raise ValueError("choose a different source project")
        source_slot = self._song_slot(src_slot, "source")
        destination = self._song_slot(dst_slot, "destination")
        operation = {
            "type": "song_import",
            "src_path": str(source),
            "src_slot": source_slot,
            "dst_slot": destination,
        }
        if source_raw is not None:
            operation.update({
                "source_image_base64": base64.b64encode(source_raw).decode("ascii"),
                "source_image_length": len(source_raw),
                "source_image_sha256": hashlib.sha256(source_raw).hexdigest(),
            })
        self.stage(operation)

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
        self.redo_operations.clear()
        self._load()
        return backup

    def save_as(self, destination: Path | str) -> Path:
        """Write the staged project image to a new project file and continue there."""
        target = Path(destination).expanduser().resolve()
        if target == self.path:
            raise ValueError("choose a new path; the source project is kept unchanged")
        if target.suffix.lower() != self.path.suffix.lower():
            raise ValueError(f"project must keep its {self.path.suffix} device extension")
        if not target.parent.is_dir():
            raise ValueError(f"destination folder does not exist: {target.parent}")
        if self._file_fingerprint() != self._fingerprint:
            raise RuntimeError("source project changed on disk since this session started; reload before saving")

        raw, project_name, _old_name = patch_project_name(self.working_raw(), target.stem)
        new_payload = pack_project(self.head, raw)
        out_payload_name = project_name
        if target.exists():
            shutil.copy2(target, target.with_suffix(target.suffix + ".bak"))
        write_project(target, self.members, self.name, new_payload, out_payload_name)

        self.path = target
        self.operations.clear()
        self.redo_operations.clear()
        self._load()
        return target


__all__ = ["ProjectSession"]
