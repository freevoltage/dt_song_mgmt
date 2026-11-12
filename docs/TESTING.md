# Testing DSM

Run from the repository root after installing the project and its dependencies:

```sh
python -m pip install -e .
python -m unittest discover -s tests -v
```

The tests generate their own temporary project archives and short WAV files.
They do not require personal projects, connected hardware, sample libraries, or
an emulator. They never modify files in `projects/`.

## What is covered

- Hardware-verified song repeat and label encoding, including reserved label IDs.
- Staged row edits, mutes, undo/redo, save, and reopening on both device formats.
- Exact project-image preservation outside the intended changed bytes.
- Pattern moves, song references, and complete pattern and sound-kit transfers.
- Digitakt default samples and sample locks, pool-slot remapping, WAV transfer,
  duplicate sample reuse, and filename collisions.
- Empty-project drafts and full JSON snapshot restoration with staged WAV assets.
- Song cuts that preserve patterns and samples still used elsewhere, plus undo
  restoring removed audio.
- Rejection of incomplete transfers, invalid snapshots, and device mismatches.
- Save As overwrite backups, external file changes, and write failures.
- Headless Textual interactions: navigation, picker, sequencer, row selection,
  paste dialogs, and deletion confirmation.

Run only the archive integrity checks with:

```sh
python -m unittest discover -s tests -p 'test_project_integrity.py' -v
```

GitHub Actions runs the full suite for pushes and pull requests on macOS and
Linux, with Python 3.10 (the declared minimum) and 3.14. The workflow must be
pushed to GitHub before those checks run there.

## What still needs a device

Generated fixtures prove that DSM preserves and transforms the bytes and assets
we expect. They cannot prove that every firmware version interprets those bytes
as intended, or that copied patterns sound identical. Hardware-created debug
projects remain the evidence for interpreting new fields. Repeat and label edits
have been confirmed on Digitone II hardware; the same song-row layout is used
for Digitakt II under the shared-format assumption.

When investigating a new field, record its raw bytes and the device-displayed
values before changing the parser. Keep regression fixtures minimal and generated
where possible; do not commit personal projects or sample libraries.
