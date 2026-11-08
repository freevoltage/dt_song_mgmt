# Plan: export the full Digitakt II sample library structure

## Goal

Export the hierarchy and metadata for all user samples stored on the Digitakt II +Drive. The JSON inventory is for the user's separate library-management app. DSM must not access any other device or synchronize/move files.

The requested output is metadata only: folder paths, filenames, sizes, and hashes. Do not persist audio samples in the export or create an extracted copy.

## Important distinction

The current `dsm samples export <project.dt2prj>` command indexes samples contained in one project archive. It does **not** enumerate the full +Drive library, so it does not meet the full-library request.

Elektron's Digitakt II manual describes the +Drive sample hierarchy and transferring samples from the device through Elektron Transfer. Elektron's Transfer manual says its Explore page can browse and transfer files/folders, but the public documentation does not describe a metadata-only API for exporting the complete folder index and hashes. It also says the device's FACTORY folder is not accessible in Transfer. See the [Digitakt II manual](https://www.elektron.se/wp-content/uploads/2025/06/Digitakt-2-User-Manual_ENG_OS1.15_250625.pdf) and [Elektron Transfer manual](https://www.elektron.se/wp-content/uploads/2026/03/Transfer-User-Manual_ENG_OS1.10_260304.pdf).

## Feasibility gate

Before building the full-library exporter, determine whether the Digitakt/Transfer USB protocol exposes:

1. A recursive listing of user sample paths and directories.
2. File sizes.
3. A device-stored hash or checksum for each sample.

If the device exposes these fields, export them directly without downloading audio. If it exposes paths and sizes but no hash, decide whether the inventory may omit hashes or whether a streaming read of sample bytes is acceptable. Computing SHA-256 necessarily reads every sample byte; streaming avoids saving a duplicate but still transfers/reads the full audio data.

## Implementation steps

1. Use an attached Digitakt II and Elektron Transfer to inspect the read-only device listing and determine what metadata is available. Do not move or alter device files.
2. Inspect the official Transfer interface/protocol or run a small read-only protocol probe to verify recursive path, size, and hash availability. Avoid implementing a guessed protocol.
3. If metadata-only enumeration is supported, implement a Digitakt-only exporter with a versioned JSON schema: directories, relative paths, filenames, sizes, device hashes, export timestamp, and any unreadable-entry errors.
4. Keep the existing project-archive exporter clearly labeled as project-only; it may remain a separate export mode but must not be presented as the full library inventory.
5. Validate the full inventory against the Digitakt's displayed +Drive hierarchy, including nested directories and user samples not referenced by the current project.

## What is needed

- A Digitakt II connected by USB with Elektron Transfer installed and connected.
- The Digitakt OS version and Elektron Transfer version for reproducing the protocol behavior.
- Clarification whether “whole library” means user samples only or whether factory samples must also appear. Transfer's manual says its Explore view cannot access the FACTORY folder.
- If no hash is exposed by the device, a decision on whether SHA-256 may be computed by streaming every sample without saving the bytes.

## Completion criteria

- Export represents the full user sample hierarchy on the Digitakt II +Drive, not one project's sample manifest.
- The export contains full relative paths, sizes, and hashes when the device exposes them.
- No sample audio is persisted or copied as part of the inventory export.
- Source files are only read; nothing is moved, renamed, deleted, or written to the Digitakt.
- Output is JSON that the external library-management app can consume; DSM provides no sync feature.
