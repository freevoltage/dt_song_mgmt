"""State and operations."""

from pathlib import Path

from .patterns import get_all_patterns_info, copy_pattern_block, clear_pattern, swap_patterns, rename_pattern
from .constants import device_name
from .project import pack_project, read_project, unpack_project
from .songs import get_all_songs_info, get_song_rows, get_song_slots, retarget_rows, copy_rows, move_rows, rename_song, swap_songs, delete_rows, reorder_rows, update_row_fields


def get_project_state(prj: Path) -> dict:
    manifest, payload, _ = read_project(prj)
    head, raw = unpack_project(payload)
    songs = get_all_songs_info(raw)
    patterns = get_all_patterns_info(raw)
    from .project import payload_name
    return {
        "project_name": payload_name(manifest),
        "project_file": prj.name,
        "device": device_name(raw, prj.suffix),
        "songs": songs,
        "patterns": patterns,
    }


def apply_operations(raw: bytes, operations: list[dict]) -> bytes:
    slots = get_song_slots(raw)
    for op in operations:
        op_type = op.get("type")
        if op_type == "pattern_copy":
            raw = copy_pattern_block(raw, op["src_idx"], op["dst_idx"])
        elif op_type == "pattern_move":
            raw = copy_pattern_block(raw, op["src_idx"], op["dst_idx"])
            for slot_idx, slot_data in enumerate(slots):
                slots[slot_idx] = retarget_rows(slot_data, from_pattern=op["src_idx"], to_pattern=op["dst_idx"])
            raw = clear_pattern(raw, op["src_idx"])
        elif op_type == "pattern_swap":
            raw = swap_patterns(raw, op["pat_a"], op["pat_b"])
        elif op_type == "pattern_clear":
            raw = clear_pattern(raw, op["pat_idx"])
        elif op_type == "pattern_rename":
            raw = rename_pattern(raw, op["pat_idx"], op["name"])
        elif op_type == "retarget":
            slot = op["slot"]
            rows = op.get("rows")
            to_pat = op.get("to_pattern")
            from_pat = op.get("from_pattern")
            if rows is not None:
                slots[slot] = retarget_rows(slots[slot], from_pattern=from_pat, to_pattern=to_pat, row_indices=rows)
            else:
                slots[slot] = retarget_rows(slots[slot], from_pattern=from_pat, to_pattern=to_pat)
        elif op_type == "rename_song":
            slot = op["slot"]
            slots[slot] = rename_song(slots[slot], op.get("name", ""))
        elif op_type == "swap_songs":
            # operate on full raw
            from .songs import set_song_slots
            raw = set_song_slots(raw, slots)
            raw = swap_songs(raw, op["slot_a"], op["slot_b"])
            slots = get_song_slots(raw)
            continue
        elif op_type == "copy_rows":
            from_slot = op["from_slot"]
            to_slot = op["to_slot"]
            rows = op.get("rows")
            dst_pos = op.get("pos", -1)
            mode = op.get("mode", "append")
            slots[to_slot] = copy_rows(slots[from_slot], slots[to_slot], src_indices=rows, dst_position=dst_pos, mode=mode)
        elif op_type == "move_rows":
            from_slot = op["from_slot"]
            to_slot = op["to_slot"]
            rows = op["rows"]
            dst_pos = op.get("pos", -1)
            mode = op.get("mode", "insert")
            src_new, dst_new = move_rows(slots[from_slot], slots[to_slot], rows, dst_pos, mode)
            slots[from_slot] = src_new
            slots[to_slot] = dst_new
        elif op_type == "delete_rows":
            slot = op["slot"]
            rows = op["rows"]
            slots[slot] = delete_rows(slots[slot], rows)
        elif op_type == "reorder":
            slot = op["slot"]
            slots[slot] = reorder_rows(slots[slot], op["new_order"])
        elif op_type == "update_rows":
            slot = op["slot"]
            rows = op["rows"]
            updates = op.get("updates", {})
            slots[slot] = update_row_fields(slots[slot], rows, updates, device=device_name(raw))
        elif op_type == "clear_song":
            slot = op["slot"]
            from .songs import clear_song
            from .songs import set_song_slots
            raw = set_song_slots(raw, slots)
            slots[slot] = clear_song(slots[slot], raw)
        elif op_type == "empty_song":
            slot = op["slot"]
            from .songs import empty_song_template, song_table_off
            slots[slot] = empty_song_template(raw, song_table_off(raw))
    from .songs import set_song_slots
    return set_song_slots(raw, slots)
