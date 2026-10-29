# Elektron Digi Song Mode Manager

Dump and restore song slots from Elektron Transfer Digitakt II (`.dt2prj`) and Digitone II (`.dn2prj`) projects.

Transfer stores the project as LZ4-compressed 32 KiB blocks, not raw song bytes. This script decompresses the project, copies the 16 uncompressed song slots (3072 bytes each), and recompresses on restore so the device can import the file. Pattern names are read and written using the device-specific layout.

Python 3.10 or newer. The terminal interface uses Textual.

## Install for development

From the project root, install the command in editable mode:

```bash
uv tool uninstall dt-song-mgmt  # only if replacing the earlier package
uv tool install --editable .
```

The `dsm` command then uses this working tree, so source changes are available without reinstalling. Re-run `uv tool install --editable .` after changing project dependencies. Restart a running web server after changing Python code.

## Dump

```bash
dsm project.dt2prj
```

Writes 16 files to `SONGS_<stem>/` beside the source project, plus a setlist page. The project archive is read in memory; the app does not extract its samples or create an unpacked project directory.

```
00_<name>.bin ... 15_<name>.bin
songs.html
```

## Restore

Overwrites the `.dt2prj` (writes a `.bak` first for backup):

```bash
dsm project.dt2prj restore ./SONGS_<stem> NEW_NAME
```

`NEW_NAME` is the project name stored in the `.dt2prj` payload, not just the file or folder name.

Files are matched by the `NN_` slot prefix (`00`–`15`). Missing slots are cleared to empty songs — the folder is treated as the full 16-slot setlist.

## Web editor

Open a project in the browser:

```bash
dsm project.dt2prj web
```

DSM prefers port 8080 and automatically tries the next available port if another project is already open. To require a specific port, pass `--port`:

```bash
dsm project.dn2prj web --port 8090
```

If that port is occupied, DSM reports the conflict and exits. Each running project has its own browser address and can be opened beside another project.

## Terminal interface

Open a project in the Textual terminal interface:

```bash
dsm "DN2 YEAR 2026 2.dn2prj" tui
```

Run that from the directory containing the project file. For a project elsewhere, pass its full path:

```bash
dsm "/path/to/DN2 YEAR 2026 2.dn2prj" tui
```

The final `tui` selects the terminal interface; use `web` in the same position to open the browser editor.

It shows the project's 16 song slots and the selected song's rows. Use the arrow keys to navigate and `Tab` to switch tables. On a selected row, `p` changes pattern, `d` deletes it, `Alt+Up/Down` reorders it, `c` copies it to another song, and `m` moves it to another song. `r` edits repeat, `b` edits BPM, `l` edits length, and `t` toggles a track mute. Press `n` to rename the song. `w` swaps song slots, `k` clears a song's rows while keeping its name, and `e` empties the slot. `u` undoes and `Ctrl+Y` redoes staged edits.

Changes remain in the draft until you press `s` (or `Ctrl+S`) and choose a new project path. Save As creates a new `.dn2prj` or `.dt2prj`, taking the device project name from the filename; the opened source file stays unchanged. The internal device project name is limited to 16 characters. If the destination already exists, the TUI asks before replacing it and keeps a `.bak` copy. Save each open project tab separately. Quitting with drafts offers to return or discard them.

Use `Ctrl+O` to open another project in a workspace tab. `Ctrl+Tab` and `Ctrl+Shift+Tab` switch projects; each tab keeps its own pending changes and shows whether it is clean or has a draft. Pattern import can use another open tab as its source, including that tab's staged changes.

Press `F2` to open Pattern Manager. On Digitakt II projects, press `F3` to inspect sample reference sizes per pattern, including samples shared across patterns. These are reference totals from each pattern's kit sounds, not a prediction of RAM freed by removing a pattern. Keys `1`–`8` filter to banks A–H, and `0` shows all banks. Pressing one of those numbers from the main view opens Pattern Manager filtered to that bank. Use `/` to search, then copy (`c`), move (`m`), clear (`d`), rename (`r`), or import (`i`) a pattern from another open tab or project path. Press `x` to export the selected song as a `.bin`, `v` to stage a `.bin` restore, or `g` to import a song slot from another project. `Ctrl+E` exports a full project JSON snapshot; `Ctrl+I` stages a full snapshot or older arrangement-only JSON restore. The latter warns that it contains no patterns and keeps the current project's patterns. Imported or restored data stays in the draft until you press `s` to save.

### macOS launcher

Open `macos/DSM Launcher.app` from Finder to choose a project and open it in the browser without leaving a Terminal window running. Open the launcher again to start another project in its own browser window. Choose **Stop app-launched servers** from the launcher menu when you are finished.

The same launcher is available from Terminal with `dsm launch`. To stop its servers from Terminal, run `dsm stop`. These stop only servers started by the launcher; a server started with `dsm <project> web` remains under that Terminal session's control.

### Full JSON project snapshots

**Export Full JSON** stores the complete uncompressed project image in a JSON envelope with readable song/pattern details and a checksum. It includes all pattern data and all song slots, including row mutes, and includes currently staged changes. **Restore JSON** stages the snapshot for the open project; it must match the current device type and project image size. Clicking **Apply Changes** creates the normal `.bak` first. External archive assets (such as sample files stored outside the project image) remain from the open project.

Older arrangement-only JSON exports can still restore all songs and their row mutes, but they do not contain pattern data. Those files leave the current project patterns in place.

## TODO

- **Song row labels** — Digitakt LABEL (`INTRO`, `VERSE`, pattern name, …) is still not mapped correctly from the 29-byte row. Hidden in `songs.html` until the tag/byte mapping matches the device.
