"""In-memory editing session shared by terminal and web user interfaces."""

from __future__ import annotations

import base64
import hashlib
import json
import shutil
from datetime import datetime, timezone
from pathlib import Path

from .constants import (
    DT2_IMAGE_SIZE,
    DN2_IMAGE_SIZE,
    KIT_BASE,
    PATTERN_BASE,
    PATTERN_SLOTS,
    PATTERN_STRIDE,
    PROJECT_NAME_LEN,
    SONG_SIZE,
    SONG_ROW_OFF,
    SONG_ROW_SIZE,
    SONG_SLOTS,
    device_name,
    kit_stride,
)
from .patterns import (
    copy_pattern_blocks,
    get_all_patterns_info,
    validate_pattern_mapping,
)
from .dt2_samples import pattern_sample_hashes, remap_pattern_sample_pool
from .archive_assets import apply_asset_delta
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
    empty_song_template,
    get_all_songs_info,
    get_song_info,
    get_song_rows,
    get_song_slots,
    restore_song_arrangement,
    set_song_slots,
    song_table_off,
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
        self._members_for_operations(candidate)
        self.operations = candidate
        self.redo_operations.clear()

    def replace_operations(self, operations: list[dict]) -> None:
        """Replace the draft atomically, retaining it only if replay succeeds."""
        candidate = list(operations)
        self._apply_staged_operations(self.base_raw, candidate)
        self._members_for_operations(candidate)
        self.operations = candidate
        self.redo_operations.clear()

    def undo(self) -> bool:
        """Undo the most recently staged operation, if one exists."""
        if not self.operations:
            return False
        candidate = self.operations[:-1]
        self._apply_staged_operations(self.base_raw, candidate)
        self._members_for_operations(candidate)
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
        self._members_for_operations(candidate)
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
                mappings = operation.get("mappings")
                raw = copy_pattern_blocks(source_raw, raw, mappings)
                if self.device == "DT2":
                    for item in mappings:
                        raw, _slot_map, _allocated = remap_pattern_sample_pool(
                            source_raw, raw, int(item["src_idx"]), int(item["dst_idx"])
                        )
            elif op_type == "song_bundle_import":
                source_path = Path(operation["src_path"]).expanduser().resolve()
                source_raw = self._source_image(operation, source_path)
                if device_name(source_raw, source_path.suffix) != device_name(raw, self.path.suffix):
                    raise ValueError("song bundles can only be imported between matching devices")
                mappings = operation.get("mappings", [])
                raw = copy_pattern_blocks(source_raw, raw, mappings)
                if self.device == "DT2":
                    for item in mappings:
                        raw, _slot_map, _allocated = remap_pattern_sample_pool(
                            source_raw, raw, int(item["src_idx"]), int(item["dst_idx"])
                        )
                src_slot = self._song_slot(operation.get("src_slot"), "source")
                dst_slot = self._song_slot(operation.get("dst_slot"), "destination")
                source_record = get_song_slots(source_raw)[src_slot]
                rows = get_song_rows(source_record)
                mapping = {int(item["src_idx"]): int(item["dst_idx"]) for item in mappings}
                if any(row[0] not in mapping for row in rows):
                    raise ValueError("every pattern used by this song must have a destination slot")
                remapped_record = bytearray(source_record)
                for row_index, row in enumerate(rows):
                    remapped_record[SONG_ROW_OFF + row_index * SONG_ROW_SIZE] = mapping[row[0]]
                slots = get_song_slots(raw)
                slots[dst_slot] = bytes(remapped_record)
                raw = set_song_slots(raw, slots)
            elif op_type == "song_bundle_cut":
                raw = self._apply_song_bundle_cut(raw, operation)
            elif op_type == "pattern_bundle_cut":
                from .patterns import clear_pattern
                raw = clear_pattern(raw, int(operation["src_idx"]))
                if operation.get("release_hashes"):
                    from .dt2_samples import clear_sample_pool_hashes
                    raw = clear_sample_pool_hashes(raw, set(operation["release_hashes"]))
            else:
                raw = apply_operations(raw, [operation])
                if op_type == "pattern_move" and self.device == "DT2" and operation.get("release_hashes"):
                    from .dt2_samples import clear_sample_pool_hashes
                    raw = clear_sample_pool_hashes(raw, set(operation["release_hashes"]))
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

    def working_members(self) -> list[tuple]:
        """Return archive members after replaying staged sample asset deltas."""
        return self._members_for_operations(self.operations)

    def _members_for_operations(self, operations: list[dict]) -> list[tuple]:
        members = self.members
        for operation in operations:
            additions = operation.get("asset_additions", [])
            removals = operation.get("asset_removals", [])
            if additions or removals:
                members = apply_asset_delta(members, additions, removals)
        return members

    def working_manifest(self) -> dict:
        """Return the manifest corresponding to the current staged archive."""
        for info, data in self.working_members():
            if info.filename == "manifest.json":
                try:
                    return json.loads(data)
                except (UnicodeDecodeError, json.JSONDecodeError):
                    raise ValueError("project manifest is not valid JSON") from None
        raise ValueError("project archive has no manifest.json")

    @staticmethod
    def _apply_song_bundle_cut(raw: bytes, operation: dict) -> bytes:
        from .patterns import clear_pattern
        slots = get_song_slots(raw)
        source_slot = ProjectSession._song_slot(operation.get("src_slot"), "source")
        slots[source_slot] = empty_song_template(raw, song_table_off(raw))
        raw = set_song_slots(raw, slots)
        for pattern_index in operation.get("clear_patterns", []):
            raw = clear_pattern(raw, int(pattern_index))
        if operation.get("release_hashes"):
            from .dt2_samples import clear_sample_pool_hashes
            raw = clear_sample_pool_hashes(raw, set(operation["release_hashes"]))
        return raw

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

    def validate_save_as(self, destination: Path | str) -> list[dict]:
        """Check a staged draft and its proposed Save As destination."""
        target = Path(destination).expanduser().resolve()
        checks: list[dict] = []

        def add(label: str, status: str, detail: str) -> None:
            checks.append({"label": label, "status": status, "detail": detail})

        extension_ok = target.suffix.lower() == self.path.suffix.lower()
        add(
            "Project extension",
            "pass" if extension_ok else "fail",
            f"{target.suffix or '(none)'} matches {self.path.suffix}" if extension_ok else f"Keep the {self.path.suffix} extension for this device.",
        )
        same_path = target == self.path
        add(
            "Save destination",
            "fail" if same_path or not target.parent.is_dir() else "pass",
            "Choose a new path; the source project remains unchanged." if same_path else (
                f"Destination folder does not exist: {target.parent}" if not target.parent.is_dir() else str(target)
            ),
        )
        try:
            unchanged = self._file_fingerprint() == self._fingerprint
        except OSError:
            unchanged = False
        add(
            "Source project",
            "pass" if unchanged else "fail",
            "Source file is unchanged on disk." if unchanged else "Source file changed during this session; reload it before saving.",
        )

        if not extension_ok or same_path or not target.parent.is_dir() or not unchanged:
            return checks

        try:
            raw = self.working_raw()
            actual_device = device_name(raw, target.suffix)
            device_ok = actual_device == self.device
            add(
                "Device type",
                "pass" if device_ok else "fail",
                f"Draft and {target.suffix} both identify as {self.device}." if device_ok else f"Draft identifies as {self.device}; destination identifies as {actual_device}.",
            )
            expected_size = DT2_IMAGE_SIZE if self.device == "DT2" else DN2_IMAGE_SIZE
            size_ok = len(raw) == expected_size
            add(
                "Project image size",
                "pass" if size_ok else "fail",
                f"{len(raw):,} bytes, expected {expected_size:,}." if size_ok else f"Got {len(raw):,} bytes; expected {expected_size:,} for {self.device}.",
            )
            songs = get_all_songs_info(raw)
            song_count_ok = len(songs) == SONG_SLOTS
            bad_rows = [
                (song["slot"], row_index, row["pattern"])
                for song in songs for row_index, row in enumerate(song["rows"])
                if not 0 <= row["pattern"] < PATTERN_SLOTS
            ]
            songs_ok = song_count_ok and not bad_rows
            song_detail = f"{len(songs)} song slots parsed; all row pattern references are in range."
            if not song_count_ok:
                song_detail = f"Expected {SONG_SLOTS} parseable song slots; found {len(songs)}."
            elif bad_rows:
                slot, row_index, pattern = bad_rows[0]
                song_detail = f"Song {slot:02d}, row {row_index + 1} references invalid pattern {pattern}."
            add("Song data", "pass" if songs_ok else "fail", song_detail)

            patterns = get_all_patterns_info(raw)
            pattern_end = PATTERN_BASE + PATTERN_SLOTS * PATTERN_STRIDE
            patterns_ok = len(patterns) == PATTERN_SLOTS and pattern_end <= len(raw)
            add(
                "Pattern data",
                "pass" if patterns_ok else "fail",
                f"{len(patterns)} pattern slots are readable." if patterns_ok else "Pattern blocks extend beyond the project image.",
            )

            renamed_raw, project_name, _old_name = patch_project_name(raw, target.stem)
            packed = pack_project(self.head, renamed_raw)
            _head, decoded = unpack_project(packed)
            roundtrip_ok = decoded == renamed_raw
            add(
                "Payload integrity",
                "pass" if roundtrip_ok else "fail",
                "Packed payload decompresses to the exact draft image." if roundtrip_ok else "Packed payload did not round-trip to the draft image.",
            )
            if len(target.stem) > PROJECT_NAME_LEN:
                add("Device project name", "warning", f"The device name will be limited to {PROJECT_NAME_LEN} characters ({project_name}).")
            else:
                add("Device project name", "pass", f"{project_name} fits the device name limit.")
        except Exception as exc:
            add("Draft structure", "fail", f"Could not validate draft: {exc}")
            return checks

        try:
            draft_members = self.working_members()
            member_names = [info.filename for info, _data in draft_members]
            manifest_entries = [(info, data) for info, data in draft_members if info.filename == "manifest.json"]
            payload_entries = [(info, data) for info, data in draft_members if info.filename == self.name]
            missing_samples = [
                str(sample.get("FileName", ""))
                for sample in json.loads(manifest_entries[0][1]).get("Samples", [])
                if sample.get("FileName") not in member_names
            ]
            unique_names = len(member_names) == len(set(member_names))
            payload_name_collision = project_name in member_names and project_name != self.name
            archive_ok = (
                len(manifest_entries) == 1 and len(payload_entries) == 1
                and not missing_samples and unique_names and not payload_name_collision
            )
            if archive_ok:
                original_manifest = json.loads(manifest_entries[0][1])
                archive_ok = original_manifest.get("Payload") == self.name
            if archive_ok:
                add(
                    "Project archive assets",
                    "pass",
                    f"Manifest and payload are present; all {len(json.loads(manifest_entries[0][1]).get('Samples', []))} sample files will be preserved.",
                )
            else:
                detail = "Archive has duplicate member names or is missing its manifest/payload."
                if missing_samples:
                    detail = f"Manifest sample asset is missing: {missing_samples[0]}"
                elif payload_name_collision:
                    detail = f"Renamed payload would collide with existing archive member: {project_name}"
                add("Project archive assets", "fail", detail)
        except Exception as exc:
            add("Project archive assets", "fail", f"Could not validate archive members: {exc}")

        return checks

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
        working_members = self.working_members()
        base_entries = self._manifest_entries(self.members)
        draft_entries = self._manifest_entries(working_members)
        base_hashes = {self._entry_hash(entry) for entry in base_entries}
        draft_by_hash = {self._entry_hash(entry): entry for entry in draft_entries}
        draft_file_data = {info.filename: data for info, data in working_members}
        asset_additions = []
        for sample_hash, entry in draft_by_hash.items():
            if sample_hash in base_hashes:
                continue
            filename = str(entry.get("FileName", ""))
            if filename not in draft_file_data:
                raise ValueError(f"snapshot sample asset is missing: {filename}")
            asset_additions.append({
                "entry": entry,
                "filename": filename,
                "data_base64": base64.b64encode(draft_file_data[filename]).decode("ascii"),
            })
        asset_removals = sorted(base_hashes - set(draft_by_hash))
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
            "asset_additions": asset_additions,
            "asset_removals": asset_removals,
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
            "asset_additions": snapshot.get("asset_additions", []),
            "asset_removals": snapshot.get("asset_removals", []),
        }
        self.replace_operations([operation])

    @staticmethod
    def _manifest_entries(members: list[tuple]) -> list[dict]:
        row = next((data for info, data in members if info.filename == "manifest.json"), None)
        if row is None:
            raise ValueError("project archive has no manifest.json")
        try:
            manifest = json.loads(row)
        except (UnicodeDecodeError, json.JSONDecodeError):
            raise ValueError("project manifest is not valid JSON") from None
        entries = manifest.get("Samples", [])
        if not isinstance(entries, list):
            raise ValueError("project manifest Samples field must be a list")
        return [entry for entry in entries if isinstance(entry, dict)]

    @staticmethod
    def _entry_hash(entry: dict) -> int:
        try:
            return int(entry["Hash"])
        except (KeyError, TypeError, ValueError):
            raise ValueError("sample manifest entry has an invalid Hash") from None

    def stage_pattern_import(
        self,
        source_path: Path | str,
        mappings: list[dict],
        source_raw: bytes | None = None,
        source_manifest: dict | None = None,
        source_members: list[tuple] | None = None,
    ) -> None:
        source = Path(source_path).expanduser().resolve()
        if source == self.path:
            raise ValueError("choose a different source project")
        pairs = validate_pattern_mapping(mappings)
        if source_raw is None or source_manifest is None or source_members is None:
            loaded_manifest, _source_payload, loaded_members = read_project(source)
            if source_raw is None:
                _source_head, source_raw = unpack_project(_source_payload)
            if source_manifest is None:
                source_manifest = loaded_manifest
            if source_members is None:
                source_members = loaded_members
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
        if self.device == "DT2":
            assert source_raw is not None and source_manifest is not None and source_members is not None
            operation["asset_additions"] = self._sample_asset_additions(
                source_raw,
                source_manifest,
                source_members,
                [src for src, _dst in pairs],
            )
        self.stage(operation)

    def stage_pattern_move(self, src_idx: int, dst_idx: int) -> None:
        """Stage an in-project pattern move and release unreferenced DT2 samples."""
        pairs = validate_pattern_mapping([{"src_idx": src_idx, "dst_idx": dst_idx}])
        source, destination = pairs[0]
        if source == destination:
            raise ValueError("source and destination are the same pattern")
        operation = {"type": "pattern_move", "src_idx": source, "dst_idx": destination}
        if self.device == "DT2":
            raw = self.working_raw()
            removed_hashes = set()
            for index in (source, destination):
                removed_hashes.update(pattern_sample_hashes(raw, index))
            moved_raw = apply_operations(raw, [operation])
            retained_hashes = set()
            for pattern in get_all_patterns_info(moved_raw):
                retained_hashes.update(pattern_sample_hashes(moved_raw, pattern["index"]))
            release_hashes = sorted(removed_hashes - retained_hashes)
            if release_hashes:
                operation["release_hashes"] = release_hashes
                operation["asset_removals"] = release_hashes
        self.stage(operation)

    def stage_song_bundle_import(
        self,
        source_path: Path | str,
        src_slot: int,
        dst_slot: int,
        mappings: list[dict],
        source_raw: bytes | None = None,
        source_manifest: dict | None = None,
        source_members: list[tuple] | None = None,
    ) -> None:
        source = Path(source_path).expanduser().resolve()
        if source == self.path and source_raw is None:
            raise ValueError("choose a different source project")
        source_slot = self._song_slot(src_slot, "source")
        destination = self._song_slot(dst_slot, "destination")
        pairs = validate_pattern_mapping(mappings)
        if source_manifest is None or source_members is None:
            source_manifest, _source_payload, source_members = read_project(source)
            if source_raw is None:
                _source_head, source_raw = unpack_project(_source_payload)
        if source_raw is None:
            raise ValueError("source project snapshot is required for a song bundle")
        source_patterns = {row[0] for row in get_song_rows(get_song_slots(source_raw)[source_slot])}
        if source_patterns != {src for src, _dst in pairs}:
            raise ValueError("map each distinct pattern used by the song exactly once")
        operation = {
            "type": "song_bundle_import",
            "src_path": str(source),
            "src_slot": source_slot,
            "dst_slot": destination,
            "mappings": [{"src_idx": src, "dst_idx": dst} for src, dst in pairs],
            "source_image_base64": base64.b64encode(source_raw).decode("ascii"),
            "source_image_length": len(source_raw),
            "source_image_sha256": hashlib.sha256(source_raw).hexdigest(),
        }
        if self.device == "DT2":
            operation["asset_additions"] = self._sample_asset_additions(
                source_raw, source_manifest, source_members, [src for src, _dst in pairs]
            )
        self.stage(operation)

    def stage_song_bundle_cut(self, src_slot: int) -> None:
        """Stage source-side cleanup after a song bundle has been copied."""
        source_slot = self._song_slot(src_slot, "source")
        slots = get_song_slots(self.working_raw())
        song_patterns = {row[0] for row in get_song_rows(slots[source_slot])}
        remaining_patterns = {
            row[0]
            for index, record in enumerate(slots) if index != source_slot
            for row in get_song_rows(record)
        }
        clear_patterns = sorted(song_patterns - remaining_patterns)
        release_hashes: set[int] = set()
        if self.device == "DT2" and clear_patterns:
            raw = self.working_raw()
            removed_hashes = set()
            for pattern_index in clear_patterns:
                removed_hashes.update(pattern_sample_hashes(raw, pattern_index))
            remaining_hashes = set()
            for pattern_index in range(PATTERN_SLOTS):
                if pattern_index not in clear_patterns:
                    remaining_hashes.update(pattern_sample_hashes(raw, pattern_index))
            release_hashes = removed_hashes - remaining_hashes
        self.stage({
            "type": "song_bundle_cut",
            "src_slot": source_slot,
            "clear_patterns": clear_patterns,
            "release_hashes": sorted(release_hashes),
            "asset_removals": sorted(release_hashes),
        })

    def stage_pattern_bundle_cut(self, pattern_index: int) -> None:
        if isinstance(pattern_index, bool) or not isinstance(pattern_index, int) or not 0 <= pattern_index < PATTERN_SLOTS:
            raise ValueError("pattern index must be between 0 and 127")
        raw = self.working_raw()
        pattern_info = get_all_patterns_info(raw)[pattern_index]
        if pattern_info["ref_count"]:
            raise ValueError("pattern is used by a song; cut the song bundle to move it safely")
        release_hashes: set[int] = set()
        if self.device == "DT2":
            removed_hashes = set(pattern_sample_hashes(raw, pattern_index))
            remaining_hashes = set()
            for other in range(PATTERN_SLOTS):
                if other != pattern_index:
                    remaining_hashes.update(pattern_sample_hashes(raw, other))
            release_hashes = removed_hashes - remaining_hashes
        self.stage({
            "type": "pattern_bundle_cut",
            "src_idx": pattern_index,
            "release_hashes": sorted(release_hashes),
            "asset_removals": sorted(release_hashes),
        })

    @staticmethod
    def _sample_asset_additions(
        source_raw: bytes,
        source_manifest: dict,
        source_members: list[tuple],
        pattern_indices: list[int],
    ) -> list[dict]:
        """Capture only manifest-backed WAV assets needed by copied patterns."""
        needed_hashes: set[int] = set()
        sample_details: dict[int, dict] = {}
        for pattern_index in set(pattern_indices):
            details = pattern_sample_hashes(source_raw, pattern_index)
            needed_hashes.update(details)
            for sample_hash, detail in details.items():
                existing = sample_details.setdefault(sample_hash, {
                    "default_tracks": set(),
                    "locked_tracks": set(),
                    "pool_slots": set(),
                })
                existing["default_tracks"].update(detail["default_tracks"])
                existing["locked_tracks"].update(detail["locked_tracks"])
                existing["pool_slots"].update(detail["pool_slots"])
        manifest_by_hash: dict[int, dict] = {}
        for entry in source_manifest.get("Samples", []):
            try:
                manifest_by_hash.setdefault(int(entry["Hash"]), entry)
            except (KeyError, TypeError, ValueError):
                continue
        member_data = {info.filename: data for info, data in source_members}
        additions = []
        missing_assets = []
        for sample_hash in sorted(needed_hashes):
            if sample_hash not in manifest_by_hash:
                detail = sample_details[sample_hash]
                # Pool-backed rows represent user assets whose bytes must travel
                # with the pattern. Pool-less default hashes can be built-in
                # device samples and remain valid device references.
                if detail["pool_slots"]:
                    tracks = sorted(detail["default_tracks"] | detail["locked_tracks"])
                    track_names = ", ".join(f"T{track + 1}" for track in tracks) or "unknown tracks"
                    missing_assets.append(f"{sample_hash:08X} ({track_names})")
                continue
            entry = manifest_by_hash[sample_hash]
            filename = str(entry.get("FileName", ""))
            if not filename or filename not in member_data:
                raise ValueError(f"source project is missing sample asset for hash {sample_hash:08X}")
            additions.append({
                "entry": entry,
                "filename": filename,
                "data_base64": base64.b64encode(member_data[filename]).decode("ascii"),
            })
        if missing_assets:
            missing = ", ".join(missing_assets)
            raise ValueError(
                "cannot copy this Digitakt pattern because its sample-pool audio is not present "
                f"in the source project archive: {missing}. Add the missing WAV asset to the "
                "source project and retry."
            )
        return additions

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
        members = self.working_members()
        new_payload = pack_project(self.head, raw)
        backup = self.path.with_suffix(self.path.suffix + ".bak")
        shutil.copy2(self.path, backup)
        write_project(self.path, members, self.name, new_payload)
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
        members = self.working_members()
        new_payload = pack_project(self.head, raw)
        out_payload_name = project_name
        if target.exists():
            shutil.copy2(target, target.with_suffix(target.suffix + ".bak"))
        write_project(target, members, self.name, new_payload, out_payload_name)

        self.path = target
        self.operations.clear()
        self.redo_operations.clear()
        self._load()
        return target


__all__ = ["ProjectSession"]
