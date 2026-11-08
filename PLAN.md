# Plan: Digitakt II sample structure export

## Goal

Export a metadata-only inventory of samples inside a Digitakt II `.dt2prj` archive. The JSON is intended for use by the user's separate library-management app. DSM does not read Tonverk media, scan mounted devices or arbitrary folders, compare inventories, or synchronize files.

## Export content

- Include archive members under `Samples/` and sample entries listed in `manifest.json`.
- Preserve archive-relative paths and directory hierarchy, including empty directories.
- Record filename, extension, archive byte size, SHA-256, and Elektron hash / manifest size where available.
- Stream ZIP members to hash them. Do not extract them or retain audio bytes.
- Report manifest entries with missing members, duplicate archive names, read errors, and manifest-size mismatches.
- Emit versioned JSON without an absolute source path by default.

## Implementation steps

1. Add an archive-only inventory backend that accepts `.dt2prj` files and rejects directories and all other file types.
2. Add `dsm samples export <project.dt2prj> --output inventory.json`.
3. Document that the export represents one project archive, not every sample stored on the Digitakt +Drive.
4. Validate on a representative Digitakt II archive and review the exported paths and hashes.

## Completion criteria

- Only Digitakt II `.dt2prj` inputs are accepted by the sample export command.
- The output preserves archive sample paths and manifest Elektron hashes, and computes SHA-256 from existing archive members.
- No audio files are extracted or saved; the source archive is never modified.
- No Tonverk access, arbitrary folder scanning, comparison, or syncing features exist.

## Validation still needed

The code can be checked using a Digitakt II project archive. Confirm that its `Samples/` hierarchy is the structure needed by the separate library-management app. DSM will not access a Tonverk card or folder for validation.
