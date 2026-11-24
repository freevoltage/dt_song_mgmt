# Reliable beta work

The core project manager is implemented. This milestone focuses on preserving
project data and making the important user workflows repeatably testable.

## Current milestone: reliable beta

- [x] Merge and publish the completed TUI and project-integrity work.
- [x] Confirm Digitone II repeat and label editing on hardware.
- [x] Confirm a basic Digitakt song/sample transfer into an empty project on hardware.
- [x] Automate opening, editing rows, saving, quitting, and reopening both formats.
- [x] Check saved image bytes, sound kits, sample locks, WAV assets, and backups.
- [x] Automate pattern copy/move/delete through Pattern Manager, including save/reopen.
- [x] Automate song and pattern transfers between open project tabs for both devices.
- [x] Automate creating an empty archive project and saving transferred contents.
- [x] Check transfer cancellation/failure and isolation between project drafts.
- [x] Run the strengthened integration suite locally: 46 tests passed on Apple Silicon / Python 3.14; the additional boundary test passed separately.
- [x] Validate the beta branch in CI: all 47 tests passed on Linux and macOS 15 Intel with Python 3.10 / 3.14.
- [x] Record supported workflows and remaining limitations in docs/TESTING.md.
- [ ] User review and approval before merging this milestone into main.

Validation: [final beta CI run](https://github.com/freevoltage/dt_song_mgmt/actions/runs/45414066521)
for code revision `f6b904c` on 24 November 2026. Only documentation was updated
after this tested revision. Main remains unchanged until review approval.

## Device verification still open

These are verification gaps, not additional features promised for this milestone.

- Check the shared song-row format on Digitakt II hardware.
- Confirm physical track mute ordering; app tests check saved bytes and the UI, not the device.
- Compare estimated sample RAM usage with the Digitakt II display.
- Check terminal-specific key handling/rendering outside the headless TUI driver.
- Test more complex transfers on hardware; automated byte preservation does not
  establish playback equivalence for every project or firmware version.

## Scope

Full-device +Drive inventory, Tonverk access, and sample-library synchronization
remain out of scope. DSM manages Digitakt II / Digitone II project files and the
samples referenced by those projects. Full-device inventory belongs in Elektroid.
