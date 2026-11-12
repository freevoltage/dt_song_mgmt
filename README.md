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

Start the Textual terminal interface:

```bash
dsm
```

`dsm tui` does the same thing. From the empty workspace, press `Ctrl+O` to browse for a project or `Ctrl+N` to create an empty draft. Creating a draft asks you to select an existing project as a device-format template; it does not open that template as a project tab. The picker starts in the current working directory. Use `q` to quit; `Esc` closes dialogs or cancels the current edit. You can also open a project directly:

```bash
dsm "DN2 YEAR 2026 2.dn2prj" tui
```

Run that from the directory containing the project file. For a project elsewhere, you can pass its full path:

```bash
dsm "/path/to/DN2 YEAR 2026 2.dn2prj" tui
```

The final `tui` selects the terminal interface; use `web` in the same position to open the browser editor.

It shows the project's 16 song slots beside the selected song's rows. Use `↑`/`↓` to navigate; `Enter` or `→` from the song list moves focus to its rows. In the row list, `↑`/`↓` moves between rows and `←`/`→` moves between columns. Press `Enter` on a cell to edit it; on LABEL, press `↑`/`↓` to choose from the fixed labels, `Enter` to apply, or `Esc` to cancel. For other cells, `Enter` opens the corresponding editor. `←` from the first column returns to the song list, and `Tab` switches panes at any time. `Space` toggles a row for multi-row actions; `Shift+Space` clears all marked rows. If your terminal does not distinguish Shift+Space, press `\` instead. `d` asks for confirmation before deleting the selected song when the song list is focused, or the selected row(s) when the row list is focused; patterns are kept. `Alt+Up/Down` reorders a row, `c` copies it to another song, and `m` moves it to another song. The selected row's 16 track states appear below as numbered tiles: white-filled tracks play, outlined tracks are muted. Press `r` to rename the selected song. With the song list focused, `y` copies a song bundle, `x` cuts a song bundle, and `p` pastes it into the selected slot. Paste opens a mapping view where you can copy the referenced patterns and samples or keep the destination patterns and paste only the arrangement. Arrangement-only moves leave source patterns intact. Cross-project transfers require matching device types. `w` swaps song slots, `k` clears a song's rows while keeping its name, and `e` empties the slot; both ask for confirmation. `u` undoes and `Ctrl+Y` redoes staged edits.

Press `v` (or `F6`) to switch the song-row table to a read-only sequencer for the selected row. The song list remains visible; muted tracks are marked `M`. In the sequencer, use `↑` / `↓` to choose a song row, `←` / `→` to change the 16-step page, and `Ctrl+↑` / `Ctrl+↓` to scroll. `Tab` switches between songs and the sequencer; press `v` again to return to the editable row table. Steps are numbered 1–16 on each page.

Changes remain staged until you press `s` or `Ctrl+S`. For an opened project, this saves over that file and keeps a `.bak` copy. For a new project draft, it asks for a path and creates the new `.dn2prj` or `.dt2prj`. Press `Ctrl+Shift+S` to choose a different path with Save As. Before writing, the TUI shows a validation report for the device type, project structure, song pattern references, payload round-trip, and archive assets. Failed checks block saving; warnings can be reviewed before continuing. The internal device project name is limited to 13 characters. Save each open project tab separately. Quitting with drafts offers to return or discard them.

Use `Ctrl+O` to open the project picker, which starts in the active project's folder. Project files appear first, labeled `DT2` or `DN2`; folders are labeled `FOLDER`. Use `↑`/`↓` and `Enter` to browse folders and open `.dt2prj` / `.dn2prj` files; `Backspace` goes to the parent folder, `f` focuses the filename filter, and `Ctrl+L` accepts a typed project path or folder. `Ctrl+N` creates an empty project draft using the active tab's device format; it clears songs, patterns, kits, and Digitakt sample assets without changing the template project. The new file is written only when you press `s` and choose a path. Open Pattern Manager in the source and destination tabs to copy or move patterns between them; Digitakt transfers bring along archive WAV assets and resolve missing sample audio by hash from a nearby `.digitakt-manifest.json` library. Indexed factory samples without local WAV files remain device references; other missing WAVs block the transfer. Sample selectors and sample-lock pool slots are remapped. Song bundles copy their referenced patterns and sample dependencies as well. Use `]` for the next project tab and `[` for the previous one; each tab keeps its own pending changes and shows whether it is clean or has a draft.

Press `F2` to open Pattern Manager. A bank navigator sits beside a plain scrolling list of all 128 slots. Use `1`–`8` to select banks A–H or `0` for all banks; `↑`/`↓` move the cursor, `PgUp`/`PgDn` jump through the list, and `/` filters by slot or name. Press `Enter` to return from search to list navigation. The `SONG` count shows how many song rows reference a pattern (`15r` means 15 rows); the selected pattern shows the song names and row numbers. Clearing with `d` asks for confirmation and warns if song rows still point to that slot. Copy and move notifications identify references affected by the operation. The command line at the bottom shows available actions: copy (`c`), move (`m`), clear (`d`), rename (`r`), and import (`i`). `y` copies the selected pattern to the clipboard, `x` cuts it, and `p` pastes it into the selected slot; these clipboard actions work across open tabs. A cross-project cut is blocked when the source pattern is still used by a song. Pressing `1`–`8` from the main view opens Pattern Manager filtered to that bank; `0` opens all banks.

Press `v` in Pattern Manager to show or hide the read-only sequencer beside the pattern list. It expands with the terminal width and shows trig markers for 16 tracks and 16 steps at a time; use `←`/`→` to change step pages and `Ctrl+↑`/`Ctrl+↓` to scroll the preview when needed. A pattern with no displayed trigs can still contain sounds, locks, or other settings. Song-row mutes are not shown in this view because they depend on the song row.

On Digitakt II projects, press `F3` to inspect per-pattern sample reference sizes, including kit sounds and sample locks, and samples shared across patterns. `F3` and `F5` show estimated project RAM and sample slots against the Digitakt II's 400 MB and 1,016-slot limits. The estimate sums occupied pool-row sizes in decimal MB; device accounting has not yet been verified. Press `F5` to browse project samples by folder and see their size, archive availability, and pattern/track assignments, including assignments in empty pattern slots. In that view, `s` toggles largest-first and `u` shows samples with no known assignments; unresolved patterns can make that list incomplete. Samples without archive paths appear separately by hash. These are reference totals from each pattern, not a prediction of RAM freed by removing a pattern. Press `F4` to see which patterns each song uses and how many rows reference each one. Press `x` from the song list to cut a song bundle; from the row list, `x` exports the selected song as a `.bin`. Use `i` to load an arrangement-only `.bin` file into the song clipboard, then select a destination and press `p`. A `.bin` does not identify its source device or contain patterns; verify the device and slot numbers. `Ctrl+E` exports a full project JSON snapshot; `Ctrl+I` stages a full snapshot or older arrangement-only JSON restore. The latter warns that it contains no patterns and keeps the current project's patterns. Imported or restored data stays in the draft until you press `s` to save.

### macOS launcher

Open `macos/DSM Launcher.app` from Finder to choose a project and open it in the browser without leaving a Terminal window running. Open the launcher again to start another project in its own browser window. Choose **Stop app-launched servers** from the launcher menu when you are finished.

The same launcher is available from Terminal with `dsm launch`. To stop its servers from Terminal, run `dsm stop`. These stop only servers started by the launcher; a server started with `dsm <project> web` remains under that Terminal session's control.

### Full JSON project snapshots

**Export Full JSON** stores the complete uncompressed project image in a JSON envelope with readable song/pattern details and a checksum. It includes all pattern data and all song slots, including row mutes, and includes currently staged changes. Any staged sample-file additions or removals are included as archive deltas. **Restore JSON** stages the snapshot for the open project; it must match the current device type and project image size. Clicking **Apply Changes** creates the normal `.bak` first. Other sample assets from the open project are preserved.

Older arrangement-only JSON exports can still restore all songs and their row mutes, but they do not contain pattern data. Those files leave the current project patterns in place.

## TODO

- **Song row labels** — Verify the complete label mapping against both devices. Digitone II INTRO and OUTRO have been checked on hardware; The same song-row encoding is used for Digitakt II; its hardware behavior remains to be verified.
