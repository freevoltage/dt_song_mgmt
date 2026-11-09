"""CLI."""

from __future__ import annotations

import sys
from pathlib import Path

from .project import read_project, write_project, unpack_project, pack_project, payload_name, patch_project_name
from .songs import get_song_slots, song_name, collect_pattern_names, get_song_info, get_all_songs_info
from .web.server import run_web_server
from . import dump_songs, restore_songs
def main(argv: list[str] | None = None) -> None:
    if argv is None:
        argv = sys.argv[1:]
    if not argv or argv == ["tui"]:
        from .tui import run_tui
        run_tui()
        return
    if argv[0] in ("-h", "--help"):
        print("Elektron Digi Song Mode Manager (dsm)", file=sys.stderr)
        print("Usage: dsm [tui] | dsm <project> [tui|info|rows|restore|web] ... | dsm launch | dsm stop", file=sys.stderr)
        raise SystemExit(0)

    if argv[0] == "launch":
        from .launcher import launch
        launch()
        return
    if argv[0] == "stop":
        from .launcher import stop_servers
        stopped = stop_servers()
        print(f"Stopped {stopped} DSM server{'s' if stopped != 1 else ''} launched by the app.")
        return
    prj = Path(argv[0]).expanduser().resolve()
    if not prj.is_file():
        raise SystemExit(f"not a file: {prj}")

    cmd = argv[1] if len(argv) > 1 else None
    if cmd is None:
        dump_songs(prj)
        return
    elif cmd == "restore" and len(argv) >= 3:
        folder = Path(argv[2]).expanduser().resolve()
        new_name = argv[3] if len(argv) >= 4 else None
        restore_songs(prj, folder, new_name)
        return
    elif cmd == "info":
        manifest, payload, _ = read_project(prj)
        head, raw = unpack_project(payload)
        info = get_all_songs_info(raw)
        pattern_names = collect_pattern_names(raw)
        print(f"Project: {payload_name(manifest)}")
        for s in info:
            pats = []
            seen = set()
            for r in s["rows"]:
                if r["pattern"] not in seen:
                    seen.add(r["pattern"])
                    p = pattern_names[r["pattern"]] if 0 <= r["pattern"] < len(pattern_names) else ""
                    pats.append(f"{r['pattern_name']}{'('+p+')' if p else ''}")
            print(f"  {s['slot']:02d} {s['name']:<16} rows={len(s['rows'])} pats={','.join(pats)}")
        return
    elif cmd == "rows":
        manifest, payload, _ = read_project(prj)
        head, raw = unpack_project(payload)
        pattern_names = collect_pattern_names(raw)
        slots = get_song_slots(raw)
        if len(argv) > 2:
            slots = [slots[int(argv[2])]]
        for i, rec in enumerate(slots):
            info = get_song_info(rec, pattern_names)
            print(f"Song {i:02d} {info['name']} rows={len(info['rows'])}")
            for j, r in enumerate(info["rows"]):
                print(f"  {j:02d}: pat={r['pattern_name']} tag={r['label_idx']} rep={r['repeat']} bpm={r['bpm_raw']} len={r['length']} mute={r['mute']:04X}")
        return
    elif cmd == "web":
        port = 8080
        port_explicit = False
        i = 2
        while i < len(argv):
            if argv[i] == "--port" and i + 1 < len(argv):
                port = int(argv[i + 1])
                port_explicit = True
                i += 2
                continue
            i += 1
        run_web_server(prj, port, auto_port=not port_explicit)
        return
    elif cmd == "tui":
        from .tui import run_tui
        run_tui(prj)
        return
    else:
        raise SystemExit("unknown command")
