# Plan: sample structure export

## Goal

Export a machine-readable hierarchy of sample-library files for use in another app. DSM only indexes and exports metadata. It does not compare libraries, synchronize them, move files, or update device/project references.

## Input sources

- Local folders recursively, including selected folders on a Tonverk SD card mounted through USB Disk Mode.
- Digitakt II `.dt2prj` archives, indexing their manifest sample entries and streaming archive members for content hashes.

For a `.dt2prj`, the manifest describes samples included in that project and may not represent the entire device +Drive. A local Digitakt library folder is needed for a complete device-library inventory.

## Export format

Use versioned JSON as the canonical format. Include a source label, export timestamp, source kind, explicit directory entries (including empty directories), file entries, and scan errors. Each file entry includes its root-relative POSIX path, name, extension, size, SHA-256, and optional Elektron hash and manifest size. Do not include absolute source paths by default.

Hash folder files and ZIP members in chunks. Never extract archive members or retain audio bytes. Do not follow symlinks outside the selected root; record symlinks and their target as metadata without treating their target contents as indexed files. Exclude the output file if it is inside the scanned folder.

## Implementation steps

1. Add `sample_inventory.py` with folder and `.dt2prj` inventory functions and a stable JSON schema.
2. Add a CLI export command, for example: `dsm samples export <folder-or-dt2prj> --output library.json [--label Tonverk]`.
3. Report read errors, invalid manifest entries, missing archive members, and files that change during hashing. Keep all records that can be read.
4. Document use with two selected library roots and explain that no audio is copied, but bytes are streamed to calculate SHA-256.
5. Check the exporter with local fixtures and inspect its output for hierarchy, empty directories, duplicate names, manifest Elektron hashes, and missing members.
6. When available, scan a mounted Tonverk SD card and confirm the exported relative paths match the device's folder structure. Do not alter its files.

## What the user can provide

Implementation can begin with the Digitakt project archive and any local folder. Hardware-specific validation needs:

- A Tonverk SD card mounted on the computer, or a representative copy of its sample folders that preserves directory structure.
- The local Digitakt sample-library folder used by the existing workflow, if that should be indexed as the device library rather than only indexing project archives.
- The selected sample roots to include. Recommended: choose sample folders, not system folders across the entire Tonverk card.

No audio upload or duplicate copy is needed. SHA-256 requires reading each file once when no shared digest exists; the implementation can stream and discard the bytes.

## Completion criteria

- JSON preserves selected directory hierarchy and records every readable file's root-relative path, size, and SHA-256.
- `.dt2prj` sample paths and Elektron hashes are retained, while SHA-256 is computed from the matching archive member.
- Output reports missing or unreadable source members and scan errors.
- Inventory generation does not extract or save audio files and does not modify source data.
- Output is suitable for another app to consume; DSM contains no library comparison or synchronization actions.
