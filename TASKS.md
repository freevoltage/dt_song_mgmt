# Tasks and wishes

## Sample library inventory for Digitakt II and Tonverk

**Status:** Wish / not implemented

Create a metadata-only export of the sample library hierarchy so the Digitakt II and Tonverk libraries can be compared and synchronized without copying audio files to the computer.

The inventory should retain each file's relative path and directory hierarchy, filename, size, and content hash. Use an existing Elektron hash when a project manifest provides one, and compute a stable SHA-256 hash by streaming the file when needed. The export should contain metadata only; it must not embed or duplicate audio data.

The intended use is to identify the same sample across the two libraries even when its path differs, and to show files that are missing or located in different folders. The first version should be read-only: it reports path differences and does not move files or rewrite Tonverk references, since moving Tonverk samples may leave references pointing to the old paths.

### Acceptance criteria

- Export the complete folder hierarchy and metadata as JSON, with an optional CSV view.
- Support scanning folders available on the computer, including a Tonverk SD card mounted through USB Disk Mode.
- Support sample entries listed in Digitakt II project manifests, retaining their Elektron hashes and paths.
- Compare two exported inventories by content hash and report matching files, missing files, and path differences.
- Stream file contents while hashing; never copy audio contents into the inventory export.
- Do not modify source folders or device projects during inventory or comparison.

### Feasibility notes

This is feasible as a read-only indexer. File paths and hierarchy come from directory traversal or project manifests. A stable content hash such as SHA-256 requires reading the file bytes, but only in a stream; the audio does not need to be copied or retained. Existing manifest hashes can be exported without recomputing them, although SHA-256 may still be useful for matching libraries that use different device-specific hashes.

Tonverk's manual describes browsing the SD-card directory hierarchy and accessing the SD card through USB Disk Mode. This makes scanning a mounted Tonverk card a practical source for the inventory.

### Later decision

Decide whether Digitakt input should be a mounted device/library folder, `.dt2prj` archives, or both. Project archives describe project sample members and may not represent every sample stored on the Digitakt's +Drive.
