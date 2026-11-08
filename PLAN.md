# Plan: export the full Digitakt II sample library structure

## Goal

Export the hierarchy and metadata for all user samples stored on the Digitakt II +Drive. The JSON inventory is for the user's separate library-management app. DSM must not access any other device or synchronize/move files.

The requested output is metadata only: folder paths, filenames, sizes, and hashes. Do not persist audio samples in the export or create an extracted copy.

## Important distinction

The current `dsm samples export <project.dt2prj>` command indexes samples contained in one project archive. It does **not** enumerate the full +Drive library, so it does not meet the full-library request.

Elektroid is an open source Elektron Transfer alternative with a CLI and a documented sample-list operation. Its `elektron:sample:ls` output includes item type, size, and an internal checksum; listings are requested for a directory path. Elektroid documents Digitakt II support. This looks like a practical read-only source for the inventory, subject to verifying that the installed version exposes the Digitakt II sample filesystem and that we can recursively walk the complete +Drive tree. See the [Elektroid repository and CLI documentation](https://github.com/dagargo/elektroid).

## Feasibility gate

Before building the full-library exporter, validate Elektroid against the connected Digitakt II:

1. The Digitakt II's supported Elektroid filesystems using its read-only device-info command.
2. Whether `elektron:sample:ls` can enumerate directories recursively without downloads.
3. Whether the reported size and internal checksum are useful as the exported size/hash fields.

If Elektroid exposes the required fields, export them directly without downloading audio. If its internal checksum is not a stable content hash, decide whether to export it as a device checksum, omit a cryptographic hash, or stream sample bytes for SHA-256. Computing SHA-256 necessarily reads every sample byte; streaming avoids saving a duplicate but still transfers/reads the full audio data.

## Implementation steps

1. Ensure Elektron Transfer is disconnected so it does not hold the MIDI interface, then use Elektroid's read-only device-info and sample-list commands against the attached Digitakt II. Do not run upload, delete, move, or download commands.
2. Verify recursive path, size, and checksum behavior on a nested folder and on a sample, without reading sample contents.
3. If metadata-only enumeration is supported, implement a Digitakt-only exporter with a versioned JSON schema: directories, relative paths, filenames, sizes, device hashes, export timestamp, and any unreadable-entry errors.
4. Keep the existing project-archive exporter clearly labeled as project-only; it may remain a separate export mode but must not be presented as the full library inventory.
5. Validate the full inventory against the Digitakt's displayed +Drive hierarchy, including nested directories and user samples not referenced by the current project.

## What is needed

- A Digitakt II connected by USB, with Elektroid installed.
- The Digitakt OS version and Elektroid version for reproducing the listing behavior.
- Clarification whether “whole library” includes the factory folder as well as user samples.
- If no hash is exposed by the device, a decision on whether SHA-256 may be computed by streaming every sample without saving the bytes.

## Completion criteria

- Export represents the full user sample hierarchy on the Digitakt II +Drive, not one project's sample manifest.
- The export contains full relative paths, sizes, and hashes when the device exposes them.
- No sample audio is persisted or copied as part of the inventory export.
- Source files are only read; nothing is moved, renamed, deleted, or written to the Digitakt.
- Output is JSON that the external library-management app can consume; DSM provides no sync feature.
