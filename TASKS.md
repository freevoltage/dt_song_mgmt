# Tasks and wishes

## Digitakt II sample structure export

**Status:** Implemented; hardware validation pending

Export sample metadata from Digitakt II `.dt2prj` project archives for use by the user's separate library-management app. DSM only reads Digitakt II project files for this feature. It does not scan Tonverk, mounted devices, or arbitrary folders, and it does not compare or synchronize libraries.

The export preserves the sample folder hierarchy, archive-relative paths, file sizes, SHA-256 hashes, and Elektron's manifest hashes. It must not extract or retain sample audio.

### Acceptance criteria

- Accept `.dt2prj` project archives only.
- Export `Samples/` archive members and manifest sample entries as versioned JSON.
- Preserve each sample path, byte size, Elektron hash, and streaming SHA-256 where the archive member exists.
- Report missing, unreadable, duplicate, or size-mismatched archive entries.
- Do not scan device folders, access Tonverk, compare libraries, or modify project/archive data.
