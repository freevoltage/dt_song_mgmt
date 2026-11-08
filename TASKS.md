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

Verify whether the Digitakt/Transfer interface exposes a recursive +Drive listing and stored hashes without downloading sample contents. If SHA-256 must be computed from content, it requires reading all sample bytes; streaming can avoid saving a second copy but cannot avoid reading/transferring those bytes. Transfer's published manual also states the FACTORY folder is not accessible in its Explore view.

The existing `.dt2prj` export only describes samples included in that project. It is not a full +Drive inventory.
