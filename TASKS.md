# Tasks and wishes

## Export the full Digitakt II +Drive sample structure

**Status:** Open; current project-archive export is not sufficient

Export paths, directory hierarchy, sizes, and hashes for the full user sample library on the Digitakt II +Drive. The JSON is consumed by the user's separate library-management app. DSM only reads the Digitakt; it must not copy persistent audio files or perform any synchronization.

### Acceptance criteria

- Inventory all user sample directories/files on the Digitakt +Drive, including items unused by the current project.
- Preserve full relative paths and available file sizes and device hashes.
- Do not persist or extract audio files.
- Report missing/unavailable metadata clearly.
- Read only; do not move, rename, delete, or modify device content.
- Scope to Digitakt II; no other device integration or library-sync behavior.

### Feasibility gate

Validate Elektroid's read-only CLI against the connected Digitakt II. It documents sample directory listings with file sizes and an internal checksum, and supports Digitakt II. Check that the installed build exposes the device's sample filesystem, walk nested directories, and determine whether its checksum is suitable as the export hash. If SHA-256 must be computed from content, every sample byte must be read; streaming avoids saving a second copy but does not avoid reading/transferring those bytes. Confirm whether factory sample paths are exposed too.

The existing `.dt2prj` export only describes samples included in that project. It is not a full +Drive inventory.

Elektroid 3.3.2 is installed on the development Mac. Its first live CLI probe could not initialize a MIDI client while Elektron Transfer was connected, so repeat the read-only probe after Transfer releases the device.
