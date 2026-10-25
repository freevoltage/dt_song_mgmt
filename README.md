# Elektron Digi Song Mode Manager

Dump and restore song slots from Elektron Transfer Digitakt II (`.dt2prj`) and Digitone II (`.dn2prj`) projects.

Transfer stores the project as LZ4-compressed 32 KiB blocks, not raw song bytes. This script decompresses the project, copies the 16 uncompressed song slots (3072 bytes each), and recompresses on restore so the device can import the file. Pattern names are read and written using the device-specific layout.

Python 3.10 or newer. No runtime dependencies are required.

## Install for development

From the project root, install the command in editable mode:

```bash
uv tool install --editable .
```

The `dsm` command then uses this working tree, so source changes are available without reinstalling. Restart a running web server after changing Python code.

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

## TODO

- **Song row labels** — Digitakt LABEL (`INTRO`, `VERSE`, pattern name, …) is still not mapped correctly from the 29-byte row. Hidden in `songs.html` until the tag/byte mapping matches the device.
