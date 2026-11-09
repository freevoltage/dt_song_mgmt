# Testing DSM with a Digitakt II emulator

**Research note — 9 November 2026**

## Short answer

There are unofficial emulators that run the real Digitakt II operating system. They could help us check DSM-created projects without using the physical Digitakt every time. I did not find a documented, ready-to-use command or API that automatically loads a `.dt2prj`, checks its patterns and samples, and confirms that the device can save and reopen it.

## Options I found

| Project | What it offers | Fit for DSM testing |
| --- | --- | --- |
| [Elektron Emu](https://github.com/xerydian/elektron-emu) | VST3 plug-ins for Digitakt II and Digitone II that run the real operating system in an emulated CPU. It also emulates the +Drive and can load WAV files. You supply the firmware. | The closest match for checking how the actual device OS handles projects, but it is designed as a DAW plug-in. I found no documented headless test interface. |
| [digikit](https://github.com/ElekLabs/digikit) | An emulator and workbench for Digitakt II and Digitone II. Its documented setup can boot firmware and show the device screen, controls, storage, and MIDI. You supply the firmware. | A promising base for a test harness. Its existing automated tests are for custom firmware modules, and the emulator’s DSP is not real-time. Its documentation does not describe automated DSM project import and save checks. |

Both are community projects, not official Elektron products. They do not include Elektron firmware; each requires a firmware file that the user obtains separately. See the projects’ own documentation for setup, supported firmware versions, and limitations.

## What an emulator could help us check

If we can automate the emulator’s controls and storage, a useful smoke test would:

1. Put a disposable DSM-created `.dt2prj` and its needed sample files on the emulator’s +Drive.
2. Open the project in the Digitakt II operating system.
3. Check the copied song, patterns, sample locks, and sounds.
4. Save, close, reopen, and check that the project still works.

That would give us stronger confidence in project compatibility than checking the file structure alone. It would still be an emulator check; a final test on the physical Digitakt would remain useful for hardware-specific behavior.

## Recommended next step

Try a small proof of concept with a disposable project and one emulator. First confirm that we can place a `.dt2prj` on its emulated +Drive and operate the device interface from a script. If that works reliably, we can build a repeatable smoke test around load, inspect, save, and reopen. If it requires fragile screen-click automation, keep the emulator as a manual preflight and continue using automated file-format checks for routine changes.

## References

- [Elektron Emu project and setup notes](https://github.com/xerydian/elektron-emu)
- [digikit project and emulator instructions](https://github.com/ElekLabs/digikit)
