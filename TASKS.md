# Tasks and wishes

## Export the full Digitakt II +Drive sample structure

**Status:** Open; current project-archive export is not sufficient

Export paths, directory hierarchy, sizes, and hashes for the entire sample library on the Digitakt II +Drive, including user and factory folders. The JSON is consumed by the user's separate library-management app. DSM only reads the Digitakt; it must not copy persistent audio files or perform any synchronization.

### Acceptance criteria

- Inventory all sample directories/files on the Digitakt +Drive, including factory folders and items unused by the current project.
- Preserve full relative paths and available file sizes and device hashes.
- Do not persist or extract audio files.
- Report missing/unavailable metadata clearly.
- Read only; do not move, rename, delete, or modify device content.
- Scope to Digitakt II; no other device integration or library-sync behavior.

### Feasibility gate

Elektroid 3.3.2's GUI has connected to the attached Digitakt II (OS 1.16) and browsed the root, nested user folders, sample names/sizes, and `/factory` subfolders. No transfers or device changes were made. This confirms the full hierarchy, including factory folders, is visible. Elektroid's documentation says the CLI sample listing also returns an internal checksum. Still verify the recursive CLI output and checksum on this device. If SHA-256 must be computed from content, every sample byte must be read; streaming avoids saving a second copy but does not avoid reading/transferring those bytes.

The existing `.dt2prj` export only describes samples included in that project. It is not a full +Drive inventory.

Elektroid 3.3.2 is installed on the development Mac. The CLI probe fails to initialize its macOS MIDI client even while Transfer is disconnected, although the Elektroid GUI connects. Investigate this CLI issue before implementing the exporter.
