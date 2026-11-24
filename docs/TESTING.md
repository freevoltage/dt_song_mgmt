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

GitHub Actions is configured to run the full suite for pushes and pull requests
on Linux and macOS 15 Intel, with Python 3.10 (the declared minimum) and 3.14. The workflow
is published in the project fork. A queued job has not yet verified that platform.
The macOS Intel label avoids the arm64 capacity failure observed in the first CI
run; see the [supported runner labels](https://docs.github.com/en/actions/reference/runners/github-hosted-runners).
Local runs also exercise Apple Silicon. Older runs on the same branch are
cancelled when a newer commit is pushed. Markdown-only changes skip the suite;
code, tests, packaging and workflow changes still trigger it.

## Automatic TUI workflows

The UI workflow test starts the real Textual application with its headless test
terminal. It opens a generated project through the picker using keyboard events,
renames a song, edits its repeat and inline label, toggles track 1, uses undo/redo,
saves through the validation dialog, quits, and opens the app again. It checks
the displayed state, saved mute bytes and backup for both device formats.
Project sessions, saving and project data are real; only the picker's starting
folder is supplied as a test environment setting.

Run this workflow alone with:

```sh
python -m unittest discover -s tests -p 'test_tui_workflows.py' -v
```

A second workflow checks cancelling deletion and saving, staying in a dirty
project, and explicitly discarding changes on quit.

Both run automatically with the full suite and in the configured CI jobs.
Use these workflows for routine UI regression checks instead of manually repeating
the same key sequences. They exercise the app in an invisible terminal, so they
cannot validate a particular terminal emulator's font or key encoding.

## Reliable beta acceptance workflows

`tests/test_beta_workflows.py` extends the real TUI journeys with the following
scenarios. Its helpers send keys, clicks, and terminal paste events; project
sessions and file saving are not mocked.

| Workflow | Verification |
| --- | --- |
| Copy, move and delete patterns | Pattern and kit bytes, song-reference retargeting, deletion confirmation/cancel, undo/redo, untouched files before Save, save/reopen. Both devices. |
| Pattern clipboard between tabs | Unsaved source edits copied, unreferenced pattern cut, source and target draft isolation, sound data and required audio, saving and reopening both projects. Both devices. |
| Archive a song in an empty project | New draft from template, destination mapping, rejection of duplicate destinations, copied patterns/kits/sample locks/WAVs, first Save As, subsequent cut and both project saves. Both devices. |
| Restore an arrangement over newer patterns | Cancelling paste, then Keep patterns; only the destination song changes while its existing patterns, sound kits and sample assets remain. Both devices. |
| Missing sample audio during a pattern cut | Transfer is rejected and both projects, redo history and clipboard are preserved. Digitakt II. |
| Cross-device pattern cut | Rejected before changing either draft or history. |
| Source cleanup fails after song paste | Both project images, asset sets and undo/redo histories are restored; no disk changes. Digitakt II. |

Run these journeys alone with:

```sh
python -m unittest discover -s tests -p 'test_beta_workflows.py' -v
```

Generated archives and WAVs live in temporary folders. Shared builders live in
`tests/project_fixtures.py`, separate from the tests, so the same known inputs
are used for data-level and TUI checks. Human project files are never modified.

Cross-project moves still produce two drafts. Save the destination and source
projects explicitly; this is not a single transaction across two disk files.
If staging either side fails, both in-memory drafts and their histories roll
back together. Backups remain available for each saved project.

These checks establish the supported software workflows for a beta candidate.
They do not establish hardware or firmware compatibility beyond the device
checks recorded below. `TASKS.md` tracks the remaining release checks and user
review; no release is merged automatically.

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

## Beta validation record

On 24 November 2026, the reliable-beta candidate passed all 46 tests locally on
Apple Silicon with Python 3.14 (281 seconds). The installed `dsm --help` command
also passed. CI validation is tracked in `TASKS.md`; remaining device checks are
listed there separately. The candidate is not merged until the user approves.
