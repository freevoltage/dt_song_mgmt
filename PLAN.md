# Plan: shared Digitakt II and Tonverk sample inventory

## Goal

Export the folder hierarchy and metadata for the shared sample library so the Digitakt II and Tonverk libraries can be compared without copying audio into the export. Keep the first version read-only. It can report a Tonverk path change, but it must not move files or rewrite project references.

## Proposed scope

- Scan local folders recursively, including a Tonverk SD card mounted through USB Disk Mode.
- Read `.dt2prj` archives as another Digitakt source. Use their manifests for Elektron hashes and paths, and stream sample contents to compute SHA-256 when cross-device matching needs a common hash.
- Include every file under the selected roots, not only WAV files. Record folders as hierarchy and record each file's relative path, filename, extension, byte size, SHA-256, and any available Elektron hash.
- Export a versioned JSON inventory. Add CSV output if the hierarchy can be represented clearly without losing path information.
- Compare two inventories by SHA-256. Report files present on both devices, files found on only one, identical files at different paths, and same-path files with different content.
- Stream file contents for hashing; do not store audio data in the inventory or create an extracted copy of an archive.
- Keep scanning and comparison read-only. Do not sync, rename, delete, or move files in the first version.

## Implementation steps

1. **Confirm inventory inputs and output schema.** Define source labels, relative-path rules, hash fields, duplicate-file handling, and which root directories to scan.
2. **Build a streaming inventory backend.** Add a folder scanner and a `.dt2prj` reader. The reader should stream archive members rather than load every sample into memory. Preserve Elektron's hash separately from SHA-256.
3. **Add CLI commands.** Suggested shape: `dsm samples index <root> --output library.json` and `dsm samples compare <digitakt.json> <tonverk.json>`. Keep inventory generation independent of opening a song project in the TUI.
4. **Add comparison output.** Show same-content samples, missing samples, path changes, and content changes at the same path. Keep stable machine-readable JSON output for future TUI use.
5. **Validate with local data.** Use the existing Digitakt project/archive and a representative folder copy. Check duplicate filenames, nested folders, non-audio files, unreadable files, and identical content with different names.
6. **Validate with Tonverk storage.** Scan a mounted Tonverk SD card and check that the exported hierarchy matches what the device displays. Do not change device files during this phase.
7. **Consider a TUI view later.** Once the inventory and comparison are reliable, add a screen to browse differences and export reports. Any future sync action needs its own plan because Tonverk references may not follow moved files.

## What I need from you

I can implement the scanner, JSON schema, CLI, and comparison using local folders and the Digitakt project already in the workspace. For hardware-specific validation, please make these available when convenient:

- A Tonverk SD card mounted on the computer, or a representative copy of its sample folders that preserves the folder structure.
- The Digitakt sample-library folder you currently synchronize, or confirmation that the existing `.dt2prj` archive is the Digitakt input you want indexed.
- Whether to scan the entire Tonverk SD card or only selected sample-library folders. **Recommended:** select the sample folders and leave system folders out.

No audio upload or duplicate audio copy is needed. The scanner must read file bytes to compute SHA-256 if no shared hash is already available; it can do that sequentially and discard the bytes immediately.

## Feasibility and limits

This is feasible as a metadata-only inventory. Tonverk's manual documents its SD-card folder browser and USB Disk Mode, which provides a practical way to scan its hierarchy while mounted. A hash identifies identical file contents even when folder paths differ. The inventory can reveal path changes, but it cannot repair Tonverk references without modifying device/project data.

Digitakt project manifests contain project sample entries, but a project archive may not describe every sample on the device's +Drive. Scanning a mounted or copied Digitakt library folder gives a fuller inventory when that source is available.

## Completion criteria

- JSON inventory preserves the selected folder hierarchy and records every file's relative path, size, and SHA-256.
- Digitakt manifest Elektron hashes are preserved as separate metadata when available.
- Inventory generation does not extract or save audio files and does not modify source data.
- Comparison correctly identifies identical content across different paths and reports missing or changed files.
- The user can review/export a report without applying any file moves.
