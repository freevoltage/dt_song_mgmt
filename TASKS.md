# Tasks and wishes

## Sample library structure export

**Status:** Implemented; awaiting validation against a mounted Tonverk card

Export a metadata-only inventory of sample library files for use by the user's separate library-management app. DSM only exports the structure. It does not compare libraries, synchronize files, or modify device files or references.

The export preserves relative paths, directory hierarchy, filenames, sizes, and hashes. Retain Elektron's hash where a `.dt2prj` manifest provides one, and compute SHA-256 by streaming file contents. Do not include or retain audio data.

### Acceptance criteria

- Export folder hierarchy and file metadata as versioned JSON.
- Scan selected folders, including a Tonverk SD card mounted through USB Disk Mode.
- Read sample entries from Digitakt II project manifests and preserve their paths and Elektron hashes.
- Include all files under a selected folder, including non-audio files, with SHA-256 content hashes.
- Report unreadable or changing files in the export rather than silently omitting them.
- Do not compare inventories, synchronize libraries, move files, or modify source projects.

### Feasibility notes

This is feasible as a read-only exporter. Hashing requires reading file bytes, but a streaming implementation can discard each chunk immediately without copying or storing audio. Tonverk's manual documents its SD-card folder browser and USB Disk Mode, providing a way to scan the mounted hierarchy.

Digitakt `.dt2prj` manifests describe project sample entries, which may not represent every sample on the device's +Drive. Support scanning local Digitakt library folders as well as project archives.
