# Plan: export the full Digitakt II sample library structure

## Goal

Export the hierarchy and metadata for the complete Digitakt II +Drive sample library, including user and factory folders. The JSON inventory is for the user's separate library-management app. DSM must not access any other device or synchronize/move files.

The requested output is metadata only: folder paths, filenames, sizes, and hashes. Do not persist audio samples in the export or create an extracted copy.

## Important distinction

The current `dsm samples export <project.dt2prj>` command indexes samples contained in one project archive. It does **not** enumerate the full +Drive library, so it does not meet the full-library request.

Elektroid is an open source Elektron Transfer alternative with a CLI and a documented sample-list operation. Its `elektron:sample:ls` output includes item type, size, and an internal checksum; listings are requested for a directory path. Elektroid documents Digitakt II support. On the attached Digitakt II (OS 1.16), Elektroid 3.3.2's GUI connected and exposed the +Drive root, nested folders, sample names and sizes. The `/factory` directory and its nested sample folders were also browsable. No files were transferred or changed. This confirms that the full hierarchy, including factory folders, is accessible through Elektroid. The live CLI checksum output is still unverified. See the [Elektroid repository and CLI documentation](https://github.com/dagargo/elektroid).

## Feasibility gate

Before building the full-library exporter, finish validating Elektroid's metadata interface against the connected Digitakt II:

1. Use the documented read-only CLI to enumerate each directory recursively without downloads.
2. Confirm whether the CLI's internal checksum is available on this Digitakt II and whether it is suitable as the exported hash field.

If Elektroid exposes the required fields, export them directly without downloading audio. If its internal checksum is not a stable content hash, export it clearly as a device checksum or compute a separate SHA-256 by streaming sample bytes. Computing SHA-256 necessarily reads every sample byte; streaming avoids saving a duplicate but still transfers/reads the full audio data.

## Implementation steps

1. Resolve why `elektroid-cli ld` cannot initialize its macOS MIDI client, although the Elektroid GUI connects successfully. Then use only read-only device-info and sample-list commands; do not run upload, delete, move, or download commands.
2. Verify recursive path, size, and checksum behavior on a nested folder and on a sample, without reading sample contents.
3. If metadata-only enumeration is supported, implement a Digitakt-only exporter with a versioned JSON schema: directories, relative paths, filenames, sizes, device hashes, export timestamp, and any unreadable-entry errors.
4. Keep the existing project-archive exporter clearly labeled as project-only; it may remain a separate export mode but must not be presented as the full library inventory.
5. Validate the full inventory against the Digitakt's displayed +Drive hierarchy, including nested directories and user samples not referenced by the current project.

## What is needed

- A Digitakt II connected by USB, with Elektroid installed. This is available now.
- Device observed: Digitakt II OS 1.16; Elektroid 3.3.2.
- The remaining blocker is CLI MIDI-client initialization; the GUI can browse the complete hierarchy.
- If no hash is exposed by the device, a decision on whether SHA-256 may be computed by streaming every sample without saving the bytes.

## Completion criteria

- Export represents the full sample hierarchy on the Digitakt II +Drive, including factory folders, not one project's sample manifest.
- The export contains full relative paths, sizes, and hashes when the device exposes them.
- No sample audio is persisted or copied as part of the inventory export.
- Source files are only read; nothing is moved, renamed, deleted, or written to the Digitakt.
- Output is JSON that the external library-management app can consume; DSM provides no sync feature.
