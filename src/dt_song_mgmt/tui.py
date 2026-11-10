"""Textual terminal interface for Elektron project management."""

from __future__ import annotations

import json
import math
import re
from pathlib import Path

from rich.text import Text
from textual.app import App, ComposeResult
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.screen import ModalScreen
from textual.widgets import Button, Footer, Input, Label, OptionList, Static, Tab, Tabs

from .constants import SONG_ROW_LABELS
from .session import ProjectSession
from .pattern_steps import pattern_trigs
from .songs import (
    SONG_ROW_MAX,
    format_bpm,
    format_length,
    collect_pattern_names,
    get_song_slots,
    get_song_rows,
    pattern_label,
)


class EntryModal(ModalScreen[str | None]):
    """Small input prompt for a single TUI action."""

    CSS = """
    EntryModal { align: center middle; background: #000000 70%; }
    #entry-dialog { width: 64; height: auto; padding: 1 2; border: solid #c18a3c; background: #111111; }
    #entry-dialog Input { margin: 1 0; }
    #entry-buttons { height: 3; align-horizontal: right; }
    #entry-buttons Button { margin-left: 1; border: none; background: #222222; color: #dedbd2; }
    """
    BINDINGS = [("escape", "cancel", "Cancel")]

    def __init__(self, title: str, prompt: str, placeholder: str = "", initial: str = ""):
        super().__init__()
        self.title_text = title
        self.prompt_text = prompt
        self.placeholder = placeholder
        self.initial = initial

    def compose(self) -> ComposeResult:
        with Vertical(id="entry-dialog"):
            yield Label(self.title_text)
            yield Static(self.prompt_text)
            yield Input(value=self.initial, placeholder=self.placeholder, id="entry-input")
            with Horizontal(id="entry-buttons"):
                yield Button("Cancel", id="cancel")
                yield Button("Continue", variant="primary", id="continue")

    def on_mount(self) -> None:
        self.query_one("#entry-input", Input).focus()

    def action_cancel(self) -> None:
        self.dismiss(None)

    def on_input_submitted(self, event: Input.Submitted) -> None:
        self.dismiss(event.value)

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "continue":
            self.dismiss(self.query_one("#entry-input", Input).value)
        else:
            self.dismiss(None)


class ProjectPickerModal(ModalScreen[Path | None]):
    """Browse folders and select a Digitakt or Digitone project."""

    CSS = """
    ProjectPickerModal { align: center middle; background: #000000 70%; }
    #project-picker-dialog {
        width: 82;
        max-width: 94%;
        height: 70%;
        max-height: 34;
        min-height: 16;
        padding: 1 2;
        border: solid #c18a3c;
        background: #111111;
    }
    #project-picker-title { height: 1; color: #dedbd2; text-style: bold; }
    #project-picker-path { height: 1; color: #c18a3c; overflow: hidden; }
    #project-picker-filter { height: 3; margin: 1 0 0 0; }
    #project-picker-list { height: 1fr; border: none; scrollbar-color: #666666; }
    #project-picker-hint { height: 2; color: #99958b; }
    """
    BINDINGS = [
        ("escape", "cancel", "Close"),
        ("backspace", "go_parent", "Parent folder"),
        ("f", "focus_filter", "Filter"),
        ("ctrl+l", "enter_path", "Enter path"),
    ]

    def __init__(self, start_directory: Path, title: str = "OPEN PROJECT"):
        super().__init__()
        self.directory = start_directory.expanduser().resolve()
        self.title_text = title
        self._entries: list[tuple[Path, bool]] = []

    def compose(self) -> ComposeResult:
        with Vertical(id="project-picker-dialog"):
            yield Static(self.title_text, id="project-picker-title")
            yield Static("", id="project-picker-path")
            yield Input(placeholder="Filter this folder's projects", id="project-picker-filter")
            yield OptionList(id="project-picker-list", markup=False)
            yield Static(
                "↑/↓ browse · Enter open · Backspace parent · f filter · Ctrl+L path · Esc close",
                id="project-picker-hint",
            )

    def on_mount(self) -> None:
        self._refresh_entries()
        self.query_one("#project-picker-list", OptionList).focus()

    def _refresh_entries(self) -> None:
        path_label = self.query_one("#project-picker-path", Static)
        option_list = self.query_one("#project-picker-list", OptionList)
        filter_text = self.query_one("#project-picker-filter", Input).value.strip().casefold()
        path_label.update(str(self.directory))
        old_highlight = option_list.highlighted
        previous = (
            self._entries[old_highlight][0]
            if old_highlight is not None and 0 <= old_highlight < len(self._entries)
            else None
        )

        try:
            children = list(self.directory.iterdir())
        except OSError as exc:
            children = []
            error = f"Cannot read this folder: {exc}"
        else:
            error = ""

        directories = sorted(
            (child for child in children if not child.name.startswith(".") and child.is_dir()),
            key=lambda item: item.name.casefold(),
        )
        projects = sorted(
            (
                child for child in children
                if not child.name.startswith(".")
                and child.is_file()
                and child.suffix.lower() in {".dt2prj", ".dn2prj"}
            ),
            key=lambda item: item.name.casefold(),
        )
        entries: list[tuple[Path, bool]] = []
        entries.extend((project, False) for project in projects)
        entries.extend((directory, True) for directory in directories)
        if self.directory.parent != self.directory:
            entries.append((self.directory.parent, True))
        if filter_text:
            entries = [
                entry for entry in entries
                if entry[0] != self.directory.parent and filter_text in entry[0].name.casefold()
            ]
        self._entries = entries

        option_list.clear_options()
        if error:
            option_list.add_option(Text(error, style="bold red"))
            option_list.disable_option_at_index(0)
            return
        if not entries:
            message = "No matching projects or folders" if filter_text else "No project files in this folder"
            option_list.add_option(Text(message, style="dim"))
            option_list.disable_option_at_index(0)
            return

        for path, is_directory in entries:
            label = Text()
            if path == self.directory.parent and is_directory:
                label.append("↑  ", style="bold #c18a3c")
                label.append("..  (parent folder)")
            elif is_directory:
                label.append("▸  ", style="bold #c18a3c")
                label.append("FOLDER  ", style="dim")
                label.append(path.name + "/")
            else:
                device = "DT2" if path.suffix.lower() == ".dt2prj" else "DN2"
                label.append(f"{device}  ", style="bold")
                label.append(path.name)
            option_list.add_option(label)
        option_list.highlighted = next(
            (index for index, (path, _) in enumerate(entries) if path == previous), 0
        )

    def on_input_changed(self, _event: Input.Changed) -> None:
        self._refresh_entries()

    def on_key(self, event) -> None:
        if self.focused is self.query_one("#project-picker-filter", Input) and event.key in {"up", "down"}:
            option_list = self.query_one("#project-picker-list", OptionList)
            option_list.focus()
            if event.key == "up":
                option_list.action_cursor_up()
            else:
                option_list.action_cursor_down()
            event.stop()

    def on_input_submitted(self, _event: Input.Submitted) -> None:
        option_list = self.query_one("#project-picker-list", OptionList)
        self._select_entry(option_list.highlighted)

    def on_option_list_option_selected(self, event: OptionList.OptionSelected) -> None:
        self._select_entry(event.option_index)

    def _select_entry(self, index: int | None) -> None:
        if index is None or not 0 <= index < len(self._entries):
            return
        path, is_directory = self._entries[index]
        if is_directory:
            self.directory = path.resolve()
            self.query_one("#project-picker-filter", Input).value = ""
            self._refresh_entries()
            self.query_one("#project-picker-list", OptionList).focus()
        else:
            self.dismiss(path.resolve())

    def action_cancel(self) -> None:
        self.dismiss(None)

    def action_go_parent(self) -> None:
        parent = self.directory.parent
        if parent != self.directory:
            self.directory = parent
            self.query_one("#project-picker-filter", Input).value = ""
            self._refresh_entries()
            self.query_one("#project-picker-list", OptionList).focus()

    def action_focus_filter(self) -> None:
        field = self.query_one("#project-picker-filter", Input)
        field.focus()
        field.cursor_position = len(field.value)

    def action_enter_path(self) -> None:
        self.app.push_screen(
            EntryModal("Open project by path", "Enter a project file path or a folder to browse.", initial=str(self.directory)),
            self._on_enter_path,
        )

    def _on_enter_path(self, value: str | None) -> None:
        if value is None or not value.strip():
            self.query_one("#project-picker-list", OptionList).focus()
            return
        target = Path(value.strip().strip('"')).expanduser().resolve()
        if target.is_dir():
            self.directory = target
            self.query_one("#project-picker-filter", Input).value = ""
            self._refresh_entries()
            self.query_one("#project-picker-list", OptionList).focus()
        elif target.is_file() and target.suffix.lower() in {".dt2prj", ".dn2prj"}:
            self.dismiss(target)
        else:
            self.app.notify("Choose a folder or a .dt2prj / .dn2prj file", severity="error")
            self.query_one("#project-picker-list", OptionList).focus()


class SongPatternMappingModal(ModalScreen[list[dict] | None]):
    """Edit a song bundle's source-to-destination pattern slot mapping."""

    CSS = """
    SongPatternMappingModal { align: center middle; background: $background 60%; }
    #song-pattern-map-dialog { width: 84; max-width: 96%; height: auto; max-height: 85%; padding: 1 2; border: solid $primary; background: $surface; }
    #mapping-context { height: 2; }
    #mapping-columns { height: 1; text-style: bold; }
    #mapping-rows { height: 1fr; }
    .mapping-row { height: 1; }
    .mapping-source { width: 28; }
    .mapping-arrow { width: 4; text-align: center; }
    .mapping-destination { width: 12; height: 1; border: none; }
    .mapping-current { width: 1fr; }
    #mapping-note { height: 2; }
    #mapping-error { height: 1; color: $error; }
    #mapping-buttons { height: 3; align-horizontal: right; }
    #mapping-buttons Button { margin-left: 1; }
    """

    BINDINGS = [("escape", "cancel", "Cancel")]

    def __init__(
        self,
        source_patterns: set[int],
        source_pattern_names: list[str],
        destination_pattern_names: list[str],
        source_project: str,
        source_song: int,
        destination_project: str,
        destination_song: int,
    ):
        super().__init__()
        self.source_patterns = sorted(source_patterns)
        self.source_pattern_names = source_pattern_names
        self.destination_pattern_names = destination_pattern_names
        self.source_project = source_project
        self.source_song = source_song
        self.destination_project = destination_project
        self.destination_song = destination_song

    def compose(self) -> ComposeResult:
        with Vertical(id="song-pattern-map-dialog"):
            yield Label("Map song patterns")
            yield Static(
                f"FROM  {self.source_project} · song {self.source_song:02d}\n"
                f"TO      {self.destination_project} · song {self.destination_song:02d}",
                id="mapping-context",
            )
            yield Static("SOURCE SLOT / PATTERN      →      DESTINATION SLOT / CURRENT NAME", id="mapping-columns")
            with VerticalScroll(id="mapping-rows"):
                for source in self.source_patterns:
                    source_name = self.source_pattern_names[source].strip() or "(unnamed)"
                    destination_name = self.destination_pattern_names[source].strip() or "(unnamed)"
                    with Horizontal(classes="mapping-row"):
                        yield Static(
                            f"{pattern_label(source)}  {source_name}",
                            classes="mapping-source",
                        )
                        yield Static("→", classes="mapping-arrow")
                        yield Input(
                            value=pattern_label(source),
                            placeholder="A01–H16",
                            id=f"mapping-destination-{source}",
                            classes="mapping-destination",
                        )
                        yield Static(destination_name, id=f"mapping-current-{source}", classes="mapping-current")
            yield Static(
                "Destinations default to the source slots. Each destination pattern will be replaced.",
                id="mapping-note",
            )
            yield Static("", id="mapping-error")
            with Horizontal(id="mapping-buttons"):
                yield Button("Cancel", id="cancel")
                yield Button("Apply mapping", id="apply", variant="primary")

    def on_mount(self) -> None:
        if self.source_patterns:
            self.query_one(f"#mapping-destination-{self.source_patterns[0]}", Input).focus()

    @staticmethod
    def _parse_destination(value: str) -> int:
        match = re.fullmatch(r"\s*([A-Ha-h])\s*(\d{1,2})\s*", value)
        if not match or not 1 <= int(match.group(2)) <= 16:
            raise ValueError(f"Invalid destination slot: {value.strip() or '(empty)'}")
        return (ord(match.group(1).upper()) - ord("A")) * 16 + int(match.group(2)) - 1

    def _apply_mapping(self) -> None:
        mappings = []
        try:
            for source in self.source_patterns:
                value = self.query_one(f"#mapping-destination-{source}", Input).value
                mappings.append({"src_idx": source, "dst_idx": self._parse_destination(value)})
            destinations = [item["dst_idx"] for item in mappings]
            if len(destinations) != len(set(destinations)):
                raise ValueError("Each source pattern needs a unique destination slot")
        except ValueError as exc:
            self.query_one("#mapping-error", Static).update(str(exc))
            return
        self.dismiss(mappings)

    def on_input_submitted(self, event: Input.Submitted) -> None:
        self._apply_mapping()

    def on_input_changed(self, event: Input.Changed) -> None:
        if not event.input.id.startswith("mapping-destination-"):
            return
        source = int(event.input.id.rsplit("-", 1)[1])
        try:
            destination = self._parse_destination(event.value)
            name = self.destination_pattern_names[destination].strip() or "(unnamed)"
        except (ValueError, IndexError):
            name = "(choose A01–H16)"
        self.query_one(f"#mapping-current-{source}", Static).update(name)

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "apply":
            self._apply_mapping()
        else:
            self.dismiss(None)

    def action_cancel(self) -> None:
        self.dismiss(None)


class ConfirmModal(ModalScreen[bool]):
    """Confirm a file overwrite or staged restore without writing yet."""

    CSS = """
    ConfirmModal { align: center middle; background: #000000 70%; }
    #generic-confirm-dialog { width: 76; height: auto; padding: 1 2; border: solid #c18a3c; background: #111111; }
    #generic-confirm-buttons { height: 3; align-horizontal: right; }
    #generic-confirm-buttons Button { margin-left: 1; border: none; background: #222222; color: #dedbd2; }
    """
    BINDINGS = [("escape", "cancel", "Cancel")]

    def __init__(self, title: str, message: str, confirm_label: str = "Continue"):
        super().__init__()
        self.title_text = title
        self.message_text = message
        self.confirm_label = confirm_label

    def compose(self) -> ComposeResult:
        with Vertical(id="generic-confirm-dialog"):
            yield Label(self.title_text)
            yield Static(self.message_text)
            with Horizontal(id="generic-confirm-buttons"):
                yield Button("Cancel", id="cancel")
                yield Button(self.confirm_label, id="confirm", variant="warning")

    def on_button_pressed(self, event: Button.Pressed) -> None:
        self.dismiss(event.button.id == "confirm")

    def action_cancel(self) -> None:
        self.dismiss(False)


class SaveValidationModal(ModalScreen[bool]):
    """Show pre-save checks before a project is written."""

    CSS = """
    SaveValidationModal { align: center middle; background: #000000 70%; }
    #save-validation-dialog { width: 96; height: auto; max-height: 90%; padding: 1 2; border: solid #c18a3c; background: #111111; }
    #save-validation-results { height: auto; max-height: 1fr; margin: 1 0; }
    #save-validation-buttons { height: 3; align-horizontal: right; }
    #save-validation-buttons Button { margin-left: 1; border: none; background: #222222; color: #dedbd2; }
    """
    BINDINGS = [("escape", "cancel", "Back")]

    def __init__(self, destination: Path, checks: list[dict]):
        super().__init__()
        self.destination = destination
        self.checks = checks
        self.can_continue = not any(check["status"] == "fail" for check in checks)

    def compose(self) -> ComposeResult:
        passed = sum(check["status"] == "pass" for check in self.checks)
        failures = sum(check["status"] == "fail" for check in self.checks)
        warnings = sum(check["status"] == "warning" for check in self.checks)
        verdict = "READY TO SAVE" if self.can_continue else "SAVE BLOCKED"
        yield Vertical(
            Label(f"Pre-save validation · {verdict}"),
            Static(str(self.destination)),
            Static(f"{passed} passed · {warnings} warnings · {failures} failed"),
            Static(
                "\n".join(
                    f"{'✓' if item['status'] == 'pass' else '⚠' if item['status'] == 'warning' else '✗'} "
                    f"{item['label']}: {item['detail']}"
                    for item in self.checks
                ),
                id="save-validation-results",
            ),
            Horizontal(
                Button("Back", id="cancel"),
                *([Button("Continue", id="continue", variant="primary")] if self.can_continue else []),
                id="save-validation-buttons",
            ),
            id="save-validation-dialog",
        )

    def on_button_pressed(self, event: Button.Pressed) -> None:
        self.dismiss(event.button.id == "continue")

    def action_cancel(self) -> None:
        self.dismiss(False)


class UnsavedExitModal(ModalScreen[str | None]):
    """Offer explicit choices before closing a session with staged edits."""

    CSS = """
    UnsavedExitModal { align: center middle; background: #000000 70%; }
    #exit-dialog { width: 72; height: auto; padding: 1 2; border: solid #c18a3c; background: #111111; }
    #exit-buttons { height: 3; align-horizontal: right; }
    #exit-buttons Button { margin-left: 1; border: none; background: #222222; color: #dedbd2; }
    """
    BINDINGS = [("escape", "stay", "Stay")]

    def __init__(self, summary: str):
        super().__init__()
        self.summary = summary

    def compose(self) -> ComposeResult:
        with Vertical(id="exit-dialog"):
            yield Label("Open projects have unsaved draft changes.")
            yield Static(self.summary)
            yield Static("Press s in each project tab to save it as a new project file.")
            with Horizontal(id="exit-buttons"):
                yield Button("Stay", id="stay")
                yield Button("Discard All & Quit", id="discard", variant="error")

    def on_button_pressed(self, event: Button.Pressed) -> None:
        self.dismiss(event.button.id)

    def action_stay(self) -> None:
        self.dismiss("stay")


class NavigatorList(Static):
    """Focusable text list for the main song and row navigators."""

    can_focus = True

    def _horizontal_target(self, event) -> bool:
        if event.key in {"left", "right"} and self.id == "rows-list":
            self.app._cancel_label_edit()
        if event.key == "left" and self.id == "rows-list":
            if self.app.active_row_column == 0:
                self.app.query_one("#songs-list", NavigatorList).focus()
            else:
                self.app.active_row_column -= 1
                self.app._show_song(self.app.active_song_slot)
            return True
        if event.key == "right" and self.id == "songs-list":
            self.app.query_one("#rows-list", NavigatorList).focus()
            return True
        if event.key == "right" and self.id == "rows-list":
            if self.app.active_row_column < len(self.app.ROW_COLUMNS) - 1:
                self.app.active_row_column += 1
                self.app._show_song(self.app.active_song_slot)
            return True
        return False

    def on_key(self, event) -> None:
        if self._horizontal_target(event):
            event.stop()
            return
        action = {
            "up": "action_move_cursor_up",
            "down": "action_move_cursor_down",
            "pageup": "action_move_cursor_page_up",
            "pagedown": "action_move_cursor_page_down",
            "home": "action_move_cursor_home",
            "end": "action_move_cursor_end",
        }.get(event.key)
        if action:
            event.stop()
            getattr(self.app, action)()


class SongWorkspace(Horizontal):
    """Place the sequencer below the song panes when the terminal is narrow."""

    def on_resize(self, event) -> None:
        self.set_class(event.size.width < 100, "compact")


class SongSequencerGrid(Static):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._last_width = -1

    def on_resize(self, event) -> None:
        if event.size.width != self._last_width:
            self._last_width = event.size.width
            if self.app.song_preview_visible:
                self.app._refresh_song_preview()


class ProjectBrowser(App[None]):
    """Browse a project's song slots and song rows in the terminal."""

    TITLE = "Elektron Digi Song Mode Manager"
    SUB_TITLE = "Project browser"
    ROW_COLUMNS = ("pattern", "label", "repeat", "bpm", "length", "mutes")
    ROW_LABEL_OPTIONS = [(0, "(none)"), (1, "Pattern name")] + [
        (index, label) for index, label in enumerate(SONG_ROW_LABELS) if label
    ]
    CSS = """
    Screen {
        layout: vertical;
        background: $background;
    }
    #project-header {
        height: 2;
        padding: 0 2;
        background: $background;
        border-bottom: solid $panel;
    }
    #project-tabs {
        height: 2;
        background: $background;
        padding: 0 1;
    }
    Tabs { background: $background; }
    Tab { background: $background; color: $text-muted; border: none; }
    Tab.-active { background: $background; color: $text; text-style: bold; }
    Tabs > .underline--bar { color: $primary; background: $primary; }
    #project-banner {
        width: 1fr;
        content-align: left middle;
        color: $text;
        text-style: bold;
    }
    #device-banner {
        width: auto;
        min-width: 26;
        content-align: right middle;
        color: $primary;
        text-style: bold;
    }
    #workspace {
        height: 1fr;
        padding: 0 2;
        layout: horizontal;
    }
    #song-workspace-main { width: 1fr; height: 1fr; }
    #song-sequencer { display: none; width: 2fr; min-width: 25; border-left: solid $panel; padding: 0 1; }
    #song-sequencer-grid { height: auto; }
    #workspace.preview-visible #song-workspace-main { width: 3fr; }
    #workspace.preview-visible #song-sequencer { display: block; }
    #workspace.preview-visible.compact { layout: vertical; }
    #workspace.preview-visible.compact #song-workspace-main { width: 100%; height: 1fr; }
    #workspace.preview-visible.compact #song-sequencer { width: 100%; height: 9; border-left: none; border-top: solid $panel; }
    #songs-pane {
        width: 30;
        min-width: 24;
        border-right: solid $panel;
        padding: 0 1 0 0;
    }
    #rows-pane {
        width: 1fr;
        min-width: 32;
        padding: 0 0 0 1;
    }
    .pane-title {
        height: 1;
        margin: 0;
        color: $text-muted;
        text-style: bold;
    }
    #songs-scroll, #rows-scroll {
        height: 1fr;
        scrollbar-color: $text-muted;
    }
    .navigator-list { height: auto; min-height: 1; }
    #rows-columns { height: 1; color: $text-muted; }
    #row-detail { height: 2; color: $text-muted; }
    #song-detail { height: 1; color: $text-muted; }
    #mute-display { height: 3; padding: 0 2; border-top: solid $panel; }
    .pane-title.focused { color: $text; text-style: bold reverse; }
    .navigator-list:focus { color: $text; }
    #message {
        height: 2;
        color: $text-muted;
        padding: 0 2;
        background: $background;
        border-top: solid $panel;
    }
    Footer { background: $background; color: $text-muted; }
    FooterKey { background: $background; }
    FooterKey > .footer-key--key { background: $panel; color: $text; }
    Button { border: none; background: $panel; color: $text; }
    """
    BINDINGS = [
        ("q", "quit", "Quit"),
        ("tab", "switch_pane", "Switch pane"),
        ("enter", "focus_song_rows", "Open / edit row"),
        ("space", "toggle_row_selection", "Select row"),
        ("d", "delete_row", "Delete row"),
        ("alt+up", "move_row_up", "Move row up"),
        ("alt+down", "move_row_down", "Move row down"),
        ("c", "copy_row", "Copy row"),
        ("m", "move_row", "Move row"),
        ("r", "rename_song", "Rename song"),
        ("w", "swap_song", "Swap song slots"),
        ("k", "clear_song", "Clear song rows"),
        ("e", "empty_song", "Empty song slot"),
        ("x", "export_song_file", "Export song .bin"),
        ("i", "import_song_file", "Import song .bin"),
        ("g", "import_song_project", "Import song slot"),
        ("ctrl+e", "export_project_json", "Export project JSON"),
        ("ctrl+i", "import_project_json", "Restore project JSON"),
        ("s", "save_project", "Save project"),
        ("ctrl+s", "save_project", "Save project"),
        ("ctrl+shift+s", "save_project_as", "Save project as"),
        ("u", "undo_change", "Undo staged edit"),
        ("ctrl+y", "redo_change", "Redo staged edit"),
        ("f2", "open_patterns", "Pattern manager"),
        ("f3", "open_sample_memory", "Sample memory"),
        ("f4", "open_song_pattern_overview", "Song pattern overview"),
        ("f5", "open_sample_browser", "Sample browser"),
        ("f6", "toggle_song_preview", "Song sequencer"),
        ("v", "toggle_song_preview", "Song sequencer"),
        ("alt+left", "song_preview_page(-1)", "Previous step page"),
        ("alt+right", "song_preview_page(1)", "Next step page"),
        ("ctrl+up", "scroll_song_preview(-3)", "Scroll sequencer up"),
        ("ctrl+down", "scroll_song_preview(3)", "Scroll sequencer down"),
        ("ctrl+o", "open_project", "Open project"),
        ("ctrl+n", "new_project", "New empty project"),
        ("]", "next_project", "Next project"),
        ("[", "previous_project", "Previous project"),
        ("1", "select_bank_a", "Bank A"),
        ("2", "select_bank_b", "Bank B"),
        ("3", "select_bank_c", "Bank C"),
        ("4", "select_bank_d", "Bank D"),
        ("5", "select_bank_e", "Bank E"),
        ("6", "select_bank_f", "Bank F"),
        ("7", "select_bank_g", "Bank G"),
        ("8", "select_bank_h", "Bank H"),
        ("0", "select_all_banks", "All banks"),
    ]

    def __init__(self, project_path: Path | str | None = None) -> None:
        super().__init__()
        self.project_path = Path(project_path).expanduser().resolve() if project_path is not None else None
        self.project_title = self.project_path.name if self.project_path else "Choose a project"
        self.device = "Unknown device"
        self.songs: list[dict] = []
        self.pattern_names: list[str] = []
        self.session: ProjectSession | None = None
        self.sessions: list[ProjectSession] = []
        self._tab_sessions: dict[str, ProjectSession] = {}
        self._dsm_clipboard: dict | None = None
        self._active_tab_id = "project-0"
        self.active_song_slot = 0
        self.active_row_index: int | None = None
        self.active_row_column = 0
        self.editing_label_idx: int | None = None
        self.selected_row_indices: set[int] = set()
        self.song_preview_visible = False
        self.song_preview_page = 0

    def compose(self) -> ComposeResult:
        with Horizontal(id="project-header"):
            yield Static("Loading project…", id="project-banner")
            yield Static("", id="device-banner")
        yield Tabs(Tab(self.project_path.name if self.project_path else "Choose a project", id="project-0"), id="project-tabs")
        with SongWorkspace(id="workspace"):
            with Horizontal(id="song-workspace-main"):
                with Vertical(id="songs-pane"):
                    yield Static("SONGS", id="songs-title", classes="pane-title")
                    with VerticalScroll(id="songs-scroll"):
                        yield NavigatorList("", id="songs-list", classes="navigator-list")
                    yield Static("", id="song-detail")
                with Vertical(id="rows-pane"):
                    yield Static("SONG ROWS", id="rows-title", classes="pane-title")
                    yield Static("  #  PATTERN/NAME       LABEL  REP   BPM   LEN  MUTES", id="rows-columns")
                    with VerticalScroll(id="rows-scroll"):
                        yield NavigatorList("", id="rows-list", classes="navigator-list")
                    yield Static("", id="row-detail")
            with VerticalScroll(id="song-sequencer"):
                yield SongSequencerGrid("", id="song-sequencer-grid")
        yield Static("", id="mute-display")
        yield Static(
            "↑↓ rows · ←/→ columns · Tab panes · brackets switch projects · Ctrl+O open · Ctrl+N new\n"
            "Songs Y/X/P · Rows c/m/d · v sequencer · Alt+←/→ page · s save",
            id="message",
        )
        yield Footer()

    def on_key(self, event) -> None:
        """Handle song-list clipboard shortcuts only in the songs pane."""
        if event.key == "escape" and self.editing_label_idx is not None:
            event.stop()
            self._cancel_label_edit()
            return
        if event.key not in {"y", "p"} or self.session is None:
            return
        try:
            songs_list = self.query_one("#songs-list", NavigatorList)
        except Exception:
            return
        if self.focused is not songs_list:
            return
        event.stop()
        if event.key == "y":
            self._set_song_clipboard("copy")
        else:
            self._paste_song_clipboard()

    def _set_song_clipboard(self, mode: str) -> None:
        self._dsm_clipboard = {
            "kind": "song",
            "mode": mode,
            "session": self.session,
            "slot": self.active_song_slot,
        }
        action = "Copied" if mode == "copy" else "Cut"
        self.notify(
            f"{action} song slot {self.active_song_slot:02d} with its referenced patterns; "
            "focus a destination song slot and press p"
        )

    def _paste_song_clipboard(self) -> None:
        clipboard = self._dsm_clipboard
        if not clipboard or clipboard.get("kind") != "song":
            self.notify("Song clipboard is empty", severity="warning")
            return
        source_session = clipboard["session"]
        source_slot = int(clipboard["slot"])
        destination_slot = self.active_song_slot
        if clipboard["mode"] == "cut" and source_session is self.session and source_slot == destination_slot:
            self.notify("Choose a different destination song slot", severity="warning")
            return
        source_raw = source_session.working_raw()
        source_patterns = {row[0] for row in get_song_rows(get_song_slots(source_raw)[source_slot])}
        if not source_patterns:
            self.notify("This song has no rows or referenced patterns to paste", severity="warning")
            return
        self.push_screen(
            SongPatternMappingModal(
                source_patterns,
                collect_pattern_names(source_raw),
                collect_pattern_names(self.session.working_raw()),
                source_session.display_name if source_session.is_new_project else source_session.path.name,
                source_slot,
                self.session.display_name if self.session.is_new_project else self.session.path.name,
                destination_slot,
            ),
            lambda value: self._on_song_bundle_mapping(
                value, clipboard, source_raw, destination_slot
            ),
        )

    def _on_song_bundle_mapping(
        self,
        mappings: list[dict] | None,
        clipboard: dict,
        source_raw: bytes,
        destination_slot: int,
    ) -> None:
        if mappings is None:
            return
        source_session = clipboard["session"]
        source_slot = int(clipboard["slot"])
        destination_staged = False
        try:
            source_members = source_session.working_members()
            source_manifest = json.loads(
                next(data for info, data in source_members if info.filename == "manifest.json")
            )
            self.session.stage_song_bundle_import(
                source_session.path,
                source_slot,
                destination_slot,
                mappings,
                source_raw=source_raw,
                source_manifest=source_manifest,
                source_members=source_members,
            )
            destination_staged = True
            if clipboard["mode"] == "cut":
                source_session.stage_song_bundle_cut(source_slot)
        except Exception as exc:
            if destination_staged:
                self.session.undo()
            self.notify(f"Could not paste song bundle: {exc}", severity="error", timeout=10)
            return
        if clipboard["mode"] == "cut":
            self._dsm_clipboard = None
            sample_note = (
                " Available Digitakt WAVs were staged; factory sounds may use device references."
                if self.session.device == "DT2" else ""
            )
            self.notify(
                f"Moved song {source_slot:02d} to slot {destination_slot:02d}; both project drafts are staged. "
                f"Press s to save each project.{sample_note}"
            )
        else:
            sample_note = (
                " Available Digitakt WAVs were staged; factory sounds may use device references."
                if self.session.device == "DT2" else ""
            )
            self.notify(
                f"Copied song {source_slot:02d} to slot {destination_slot:02d} with patterns; press s to save."
                f"{sample_note}"
            )
        if self.session is not None:
            self._refresh_state()

    def on_mount(self) -> None:
        if self.project_path is None:
            self.query_one("#project-banner", Static).update("No project open · Ctrl+O open · Ctrl+N new")
            self.query_one("#songs-list", NavigatorList).focus()
            return
        self._load_initial_project()

    def _load_initial_project(self) -> bool:
        if self.project_path is None:
            return False
        try:
            self.session = ProjectSession(self.project_path)
            self.sessions = [self.session]
            self._tab_sessions[self._active_tab_id] = self.session
            state = self.session.state()
            self.project_title = state["project_name"] or self.project_path.name
            self.device = state["device"]
            self.songs = state["songs"]
            self.pattern_names = collect_pattern_names(self.session.working_raw())
        except Exception as exc:
            self.query_one("#project-banner", Static).update(
                f"Could not open {self.project_path.name}: {exc}"
            )
            self.notify(f"Could not open project: {exc}", severity="error", timeout=10)
            return False

        self._refresh_state()
        self.query_one("#songs-list", NavigatorList).focus()
        self._refresh_pane_titles()
        return True

    def on_tabs_tab_activated(self, event: Tabs.TabActivated) -> None:
        if event.tab is None:
            return
        session = self._tab_sessions.get(event.tab.id or "")
        if session is not None and session is not self.session:
            self._activate_project(event.tab.id or "", session)

    def _activate_project(self, tab_id: str, session: ProjectSession) -> None:
        self._active_tab_id = tab_id
        self.session = session
        self.project_path = session.path
        self.project_title = session.display_name if session.is_new_project else session.name or session.path.name
        self.device = session.device
        self.active_song_slot = 0
        self.active_row_index = None
        self.active_row_column = 0
        self.editing_label_idx = None
        self.selected_row_indices.clear()
        self._refresh_state()

    def _tab_label(self, session: ProjectSession) -> str:
        pending = len(session.operations)
        marker = "NEW" if session.is_new_project else (f"*{pending}" if pending else "clean")
        name = session.display_name if session.is_new_project else session.path.name
        return f"{name} [{session.device} {marker}]"

    def _refresh_tab_labels(self) -> None:
        tabs = self.query_one("#project-tabs", Tabs)
        for tab_id, session in self._tab_sessions.items():
            tab = tabs.get_tab(tab_id)
            if tab is not None:
                tab.label = self._tab_label(session)

    def action_open_project(self) -> None:
        start_directory = self.session.path.parent if self.session is not None else Path.cwd()
        self.push_screen(ProjectPickerModal(start_directory), self._on_open_project)

    def action_new_project(self) -> None:
        if self.session is None:
            self.push_screen(
                ProjectPickerModal(Path.cwd(), "SELECT AN EXISTING PROJECT AS DEVICE TEMPLATE"),
                self._on_new_project_template,
            )
            return
        self._create_project_draft(self.session)

    def _on_new_project_template(self, path: Path | None) -> None:
        if path is None:
            return
        try:
            template = ProjectSession(path)
        except Exception as exc:
            self.notify(f"Could not open project template: {exc}", severity="error", timeout=10)
            return
        self._create_project_draft(template)

    def _create_project_draft(self, template: ProjectSession) -> None:
        try:
            session = ProjectSession.empty_draft_from(template)
        except Exception as exc:
            self.notify(f"Could not create an empty project: {exc}", severity="error", timeout=10)
            return
        template_name = template.display_name
        self._add_project_session(session)
        self.notify(f"Created an empty {session.device} project draft from {template_name}; press s to save it")

    def _on_open_project(self, selected_path: Path | None) -> None:
        if selected_path is None:
            return
        path = selected_path.expanduser().resolve()
        for tab_id, session in self._tab_sessions.items():
            if not session.is_new_project and session.path == path:
                tabs = self.query_one("#project-tabs", Tabs)
                tabs.active = tab_id
                self._activate_project(tab_id, session)
                return
        try:
            session = ProjectSession(path)
        except Exception as exc:
            self.notify(f"Could not open project: {exc}", severity="error", timeout=10)
            return
        self._add_project_session(session)

    def _add_project_session(self, session: ProjectSession) -> None:
        first = not self._tab_sessions
        tab_id = f"project-{len(self._tab_sessions)}"
        self.sessions.append(session)
        self._tab_sessions[tab_id] = session
        tabs = self.query_one("#project-tabs", Tabs)
        if first:
            tabs.get_tab(tab_id).label = self._tab_label(session)
        else:
            tabs.add_tab(Tab(self._tab_label(session), id=tab_id))
        tabs.active = tab_id
        self._activate_project(tab_id, session)

    def action_next_project(self) -> None:
        self.query_one("#project-tabs", Tabs).action_next_tab()

    def action_previous_project(self) -> None:
        self.query_one("#project-tabs", Tabs).action_previous_tab()

    def action_switch_pane(self) -> None:
        self._cancel_label_edit()
        songs_list = self.query_one("#songs-list", NavigatorList)
        rows_list = self.query_one("#rows-list", NavigatorList)
        (rows_list if self.focused is songs_list else songs_list).focus()

    def action_focus_song_rows(self) -> None:
        if self.focused is self.query_one("#songs-list", NavigatorList):
            self.query_one("#rows-list", NavigatorList).focus()
        elif self.focused is self.query_one("#rows-list", NavigatorList):
            if self._selected_row() is None:
                return
            field = self.ROW_COLUMNS[self.active_row_column]
            if field == "pattern":
                self.action_change_pattern()
            elif field == "repeat":
                self.action_edit_repeat()
            elif field == "bpm":
                self.action_edit_bpm()
            elif field == "length":
                self.action_edit_length()
            elif field == "mutes":
                self.action_toggle_mute()
            elif field == "label":
                self._toggle_label_edit()

    def _move_cursor(self, delta: int | None = None, edge: str | None = None) -> None:
        songs_list = self.query_one("#songs-list", NavigatorList)
        rows_list = self.query_one("#rows-list", NavigatorList)
        if self.focused is rows_list and self.editing_label_idx is not None:
            if edge is None and delta in {-1, 1}:
                self._cycle_label(delta)
                return
            self._cancel_label_edit()
        if self.focused is songs_list and self.songs:
            slots = [song["slot"] for song in self.songs]
            current = slots.index(self.active_song_slot) if self.active_song_slot in slots else 0
            if edge == "first":
                target = 0
            elif edge == "last":
                target = len(slots) - 1
            else:
                target = max(0, min(len(slots) - 1, current + (delta or 0)))
            if slots[target] != self.active_song_slot:
                self.active_song_slot = slots[target]
                self.active_row_index = None
                self.selected_row_indices.clear()
                self._refresh_state()
        elif self.focused is rows_list and self.songs:
            rows = self.songs[self.active_song_slot]["rows"]
            if not rows:
                self.active_row_index = None
                self._show_song(self.active_song_slot)
                return
            current = self.active_row_index if self.active_row_index is not None else -1
            if edge == "first":
                self.active_row_index = 0
            elif edge == "last":
                self.active_row_index = len(rows) - 1
            else:
                self.active_row_index = max(0, min(len(rows) - 1, current + (delta or 0)))
            self._show_song(self.active_song_slot)

    def action_move_cursor_up(self) -> None:
        self._move_cursor(-1)

    def action_move_cursor_down(self) -> None:
        self._move_cursor(1)

    def action_move_cursor_page_up(self) -> None:
        self._move_cursor(-12)

    def action_move_cursor_page_down(self) -> None:
        self._move_cursor(12)

    def action_move_cursor_home(self) -> None:
        self._move_cursor(edge="first")

    def action_move_cursor_end(self) -> None:
        self._move_cursor(edge="last")

    def on_descendant_focus(self, event) -> None:
        if self.is_mounted:
            self._refresh_pane_titles()

    def _refresh_pane_titles(self) -> None:
        try:
            songs_focused = self.focused is self.query_one("#songs-list", NavigatorList)
            rows_focused = self.focused is self.query_one("#rows-list", NavigatorList)
            songs_title = self.query_one("#songs-title", Static)
            rows_title = self.query_one("#rows-title", Static)
            songs_title.update(("> " if songs_focused else "  ") + "SONGS")
            rows_title.update(
                ("> " if rows_focused else "  ")
                + f"SONG {self.active_song_slot:02d}  {self.songs[self.active_song_slot]['name']}"
            )
            songs_title.set_class(songs_focused, "focused")
            rows_title.set_class(rows_focused, "focused")
        except Exception:
            return

    def _refresh_state(self) -> None:
        if self.session is None:
            return
        state = self.session.state()
        self.songs = state["songs"]
        self.pattern_names = collect_pattern_names(self.session.working_raw())
        if self.songs:
            self.active_song_slot = min(self.active_song_slot, len(self.songs) - 1)
            if self.active_row_index is None and self.songs[self.active_song_slot]["rows"]:
                self.active_row_index = 0
        pending = state["pending_changes"]
        marker = "NEW PROJECT" if self.session.is_new_project else (f"DRAFT {pending}" if pending else "CLEAN")
        if self.session.is_new_project:
            banner = f"{self.project_title}  ·  based on {self.session.template_label}"
        else:
            banner = f"{self.project_path.name}  ·  {self.project_title}"
        self.query_one("#project-banner", Static).update(banner)
        self.query_one("#device-banner", Static).update(f"{self.device}  ·  {marker}")
        self._refresh_tab_labels()
        song_lines = Text()
        for song in self.songs:
            marker = ">" if song["slot"] == self.active_song_slot else " "
            name = song["name"].strip() or "(unnamed)"
            line = f"{marker} {song['slot']:02d}  {name[:16]:<16}  {song['row_count']:>2}r"
            song_lines.append(line, style="reverse bold" if marker == ">" else None)
            song_lines.append("\n")
        self.query_one("#songs-list", NavigatorList).update(song_lines)
        self.query_one("#songs-scroll", VerticalScroll).scroll_to(
            y=self.active_song_slot, animate=False, force=True
        )
        if self.songs:
            self._show_song(self.active_song_slot)
        self.query_one("#song-detail", Static).update(
            f"{self.active_song_slot:02d} · {self.songs[self.active_song_slot]['row_count']} rows"
            if self.songs else "No songs"
        )
        self._refresh_pane_titles()

    def _show_song(self, slot: int) -> None:
        song = self.songs[slot]
        valid_indices = set(range(len(song["rows"])))
        self.selected_row_indices.intersection_update(valid_indices)
        self.active_row_index = (
            min(self.active_row_index, len(song["rows"]) - 1)
            if self.active_row_index is not None and song["rows"]
            else None
        )
        selected_row = self.active_row_index
        row_lines = Text()
        active_row = None
        rows_list = self.query_one("#rows-list", NavigatorList)
        rows_focused = self.focused is rows_list
        for index, row in enumerate(song["rows"]):
            pattern_id = row["pattern"]
            custom_name = self.pattern_names[pattern_id] if 0 <= pattern_id < len(self.pattern_names) else ""
            marker = ">" if index == selected_row else " "
            check = "✓" if index in self.selected_row_indices else " "
            compact_name = (custom_name.strip() or "(unnamed)")[:10]
            label = (row.get("label") or "—")[:5]
            row_lines.append(f"{marker}{check} {index + 1:02d} ")
            cells = (
                ("pattern", f"{pattern_label(pattern_id):<3} {compact_name:<10}"),
                (
                    "label",
                    f"{self._label_name(self.editing_label_idx) if self.editing_label_idx is not None and index == selected_row else label:<5}",
                ),
                ("repeat", f"×{row['repeat']:<2}"),
                ("bpm", f"{format_bpm(row['bpm_raw']):>7}"),
                ("length", f"{format_length(row['length']):>4}"),
                ("mutes", "16 trk"),
            )
            for column, (field, value) in enumerate(cells):
                style = None
                if index == selected_row:
                    style = "reverse bold" if rows_focused and column == self.active_row_column else "bold"
                row_lines.append(value, style=style)
                if column < len(cells) - 1:
                    row_lines.append(" ")
            row_lines.append("\n")
        rows_list.update(row_lines)
        if self.active_row_index is not None:
            self.query_one("#rows-scroll", VerticalScroll).scroll_to(
                y=self.active_row_index, animate=False, force=True
            )
        if self.active_row_index is not None and song["rows"]:
            active_row = song["rows"][self.active_row_index]
        if active_row is None:
            detail = "Select a row to see its full pattern name and muted tracks."
            mute_display = Text("MUTES  White tile = playing · outline tile = muted\n")
            mute_display.append("Select a song row to show tracks 1–16.")
        else:
            pattern_id = active_row["pattern"]
            pattern_name = self.pattern_names[pattern_id].strip() if 0 <= pattern_id < len(self.pattern_names) else ""
            detail = (
                f"Row {self.active_row_index + 1:02d} · {pattern_label(pattern_id)} {pattern_name or '(unnamed)'}\n"
                f"{(active_row.get('label') or '—')[:8]} · ×{active_row['repeat']} · "
                f"{format_bpm(active_row['bpm_raw'])} BPM · {format_length(active_row['length'])} steps"
            )
        if self.editing_label_idx is not None:
            detail = (
                f"Choose row label · {self._label_name(self.editing_label_idx)}\n"
                "↑/↓ select · Enter apply · Esc cancel"
            )
        self.query_one("#row-detail", Static).update(detail)
        if active_row is not None:
            mute_display = Text("MUTES  White tile = playing · outline tile = muted\n")
            for track in range(1, 17):
                muted = bool(active_row["mute"] & (1 << (track - 1)))
                style = "dim" if muted else "black on white"
                mute_display.append(f"⟦{track}⟧", style=style)
                if track < 16:
                    mute_display.append(" ")
        self.query_one("#mute-display", Static).update(mute_display)
        if self.song_preview_visible:
            self._refresh_song_preview()

    def action_toggle_song_preview(self) -> None:
        if self.session is None:
            self.notify("Open a project first", severity="warning")
            return
        self.song_preview_visible = not self.song_preview_visible
        self.query_one("#workspace", SongWorkspace).set_class(self.song_preview_visible, "preview-visible")
        if self.song_preview_visible:
            self._refresh_song_preview()

    def action_song_preview_page(self, delta: int) -> None:
        if self.song_preview_visible:
            self.song_preview_page = max(0, min(7, self.song_preview_page + delta))
            self._refresh_song_preview()

    def action_scroll_song_preview(self, delta: int) -> None:
        if self.song_preview_visible:
            self.query_one("#song-sequencer", VerticalScroll).scroll_relative(y=delta, animate=False)

    def _refresh_song_preview(self) -> None:
        if not self.song_preview_visible or self.session is None:
            return
        output = Text()
        if not self.songs or self.active_row_index is None:
            output.append("Select a song row to preview its pattern.")
        else:
            rows = self.songs[self.active_song_slot]["rows"]
            if not 0 <= self.active_row_index < len(rows):
                output.append("Select a song row to preview its pattern.")
            else:
                row = rows[self.active_row_index]
                try:
                    tracks = pattern_trigs(self.session.working_raw(), row["pattern"], self.session.device)
                except ValueError as exc:
                    output.append(f"Cannot read trigs: {exc}")
                else:
                    start = self.song_preview_page * 16
                    width = self.query_one("#song-sequencer-grid", SongSequencerGrid).size.width
                    cell_width = max(1, (width - 10) // 16)
                    output.append(f"{pattern_label(row['pattern'])}  STEPS {start + 1:03}–{start + 16:03}\n", style="bold")
                    output.append("      " + " ".join(
                        f"{start + group + 1:03}".ljust(cell_width * 4)
                        for group in (0, 4, 8, 12)
                    ).rstrip() + "\n", style="dim")
                    for index, steps in enumerate(tracks):
                        muted = bool(row["mute"] & (1 << index))
                        output.append(f"T{index + 1:02} {'M' if muted else ' '} ", style="dim" if muted else None)
                        for step in range(16):
                            active = steps[start + step]
                            output.append(("●" if active else "·").center(cell_width), style="dim" if muted or not active else "bold")
                            if step % 4 == 3 and step != 15:
                                output.append(" ")
                        output.append("\n")
                    output.append("\nM = muted in this song row\nAlt+←/→ page · Ctrl+↑/↓ scroll", style="dim")
        self.query_one("#song-sequencer-grid", SongSequencerGrid).update(output)

    def _selected_row(self) -> dict | None:
        if self.active_row_index is None:
            self.notify("Select a song row first", severity="warning")
            return None
        rows = self.songs[self.active_song_slot]["rows"]
        if not 0 <= self.active_row_index < len(rows):
            self.active_row_index = None
            self.notify("Select a song row first", severity="warning")
            return None
        return rows[self.active_row_index]

    def _active_row_indices(self) -> list[int] | None:
        if self._selected_row() is None:
            return None
        rows = self.songs[self.active_song_slot]["rows"]
        indices = sorted(self.selected_row_indices) if self.selected_row_indices else [self.active_row_index]
        return [index for index in indices if 0 <= index < len(rows)]

    def action_toggle_row_selection(self) -> None:
        if self._selected_row() is None:
            return
        index = self.active_row_index
        if index in self.selected_row_indices:
            self.selected_row_indices.remove(index)
            message = f"Row {index + 1} removed from selection"
        else:
            self.selected_row_indices.add(index)
            message = f"Row {index + 1} selected ({len(self.selected_row_indices)} total)"
        self._show_song(self.active_song_slot)
        self.notify(message)

    def _stage_row_update(self, updates: dict, success_message: str) -> None:
        indices = self._active_row_indices()
        if self.session is None or indices is None:
            return
        self.session.stage({
            "type": "update_rows",
            "slot": self.active_song_slot,
            "rows": indices,
            "updates": updates,
        })
        self._refresh_state()
        self.notify(success_message)

    def _reorder_active_row(self, delta: int) -> None:
        if self.session is None or self._selected_row() is None:
            return
        rows = self.songs[self.active_song_slot]["rows"]
        source = self.active_row_index
        destination = source + delta
        if not 0 <= destination < len(rows):
            self.notify("Row is already at the end of the song", severity="warning")
            return
        order = list(range(len(rows)))
        order[source], order[destination] = order[destination], order[source]
        try:
            self.session.stage({"type": "reorder", "slot": self.active_song_slot, "new_order": order})
        except Exception as exc:
            self.notify(f"Could not reorder row: {exc}", severity="error")
            return
        self.active_row_index = destination
        self.selected_row_indices.clear()
        self._refresh_state()
        self.notify("Row reordered in the draft; press s to save")

    def action_move_row_up(self) -> None:
        self._reorder_active_row(-1)

    def action_move_row_down(self) -> None:
        self._reorder_active_row(1)

    def action_copy_row(self) -> None:
        if self._selected_row() is None:
            return
        self.push_screen(
            EntryModal("Copy row", "Enter the destination song slot (0–15).", "0–15"),
            self._on_copy_row_destination,
        )

    def _on_copy_row_destination(self, value: str | None) -> None:
        self._transfer_row(value, move=False)

    def action_move_row(self) -> None:
        if self._selected_row() is None:
            return
        self.push_screen(
            EntryModal("Move row", "Enter the destination song slot (0–15).", "0–15"),
            self._on_move_row_destination,
        )

    def _on_move_row_destination(self, value: str | None) -> None:
        self._transfer_row(value, move=True)

    def _transfer_row(self, value: str | None, *, move: bool) -> None:
        indices = self._active_row_indices()
        if value is None or self.session is None or indices is None:
            return
        try:
            destination = int(value.strip())
            if not 0 <= destination < 16:
                raise ValueError
        except ValueError:
            self.notify("Song slot must be a number from 0 to 15", severity="error")
            return
        source = self.active_song_slot
        if move and source == destination:
            self.notify("Choose a different song slot; use Alt+Up/Down to reorder within this song", severity="warning")
            return
        source_rows = indices
        destination_row = len(self.songs[destination]["rows"])
        if destination_row + len(source_rows) > SONG_ROW_MAX:
            self.notify(f"Song slot {destination:02d} already has the maximum {SONG_ROW_MAX} rows", severity="error")
            return
        operation = (
            {
                "type": "move_rows",
                "from_slot": source,
                "to_slot": destination,
                "rows": source_rows,
                "pos": -1,
                "mode": "insert",
            }
            if move
            else {
                "type": "copy_rows",
                "from_slot": source,
                "to_slot": destination,
                "rows": source_rows,
                "pos": -1,
                "mode": "append",
            }
        )
        try:
            self.session.stage(operation)
        except Exception as exc:
            self.notify(f"Could not {'move' if move else 'copy'} row: {exc}", severity="error", timeout=8)
            return
        self.active_song_slot = destination
        self.active_row_index = destination_row
        self.selected_row_indices.clear()
        self._refresh_state()
        verb = "Moved" if move else "Copied"
        self.notify(f"{verb} {len(source_rows)} row(s) to song slot {destination:02d} in the draft; press s to save")

    def action_swap_song(self) -> None:
        if self.session is None:
            return
        self.push_screen(
            EntryModal("Swap song slots", f"Swap slot {self.active_song_slot:02d} with (0–15).", "0–15"),
            self._on_swap_song_slot,
        )

    def _on_swap_song_slot(self, value: str | None) -> None:
        if value is None or self.session is None:
            return
        try:
            target = int(value.strip())
            if not 0 <= target < 16:
                raise ValueError
        except ValueError:
            self.notify("Song slot must be a number from 0 to 15", severity="error")
            return
        if target == self.active_song_slot:
            self.notify("Choose a different song slot", severity="warning")
            return
        try:
            self.session.stage({"type": "swap_songs", "slot_a": self.active_song_slot, "slot_b": target})
        except Exception as exc:
            self.notify(f"Could not swap song slots: {exc}", severity="error")
            return
        self.active_song_slot = target
        self.selected_row_indices.clear()
        self._refresh_state()
        self.notify(f"Swapped song slots in the draft; press s to save")

    def action_clear_song(self) -> None:
        if self.session is None:
            return
        try:
            self.session.stage({"type": "clear_song", "slot": self.active_song_slot})
        except Exception as exc:
            self.notify(f"Could not clear song rows: {exc}", severity="error")
            return
        self.active_row_index = None
        self.selected_row_indices.clear()
        self._refresh_state()
        self.notify("Cleared song rows in the draft; name kept. Press s to save")

    def action_empty_song(self) -> None:
        if self.session is None:
            return
        try:
            self.session.stage({"type": "empty_song", "slot": self.active_song_slot})
        except Exception as exc:
            self.notify(f"Could not empty song slot: {exc}", severity="error")
            return
        self.active_row_index = None
        self.selected_row_indices.clear()
        self._refresh_state()
        self.notify("Emptied song slot in the draft; press s to save")

    def action_edit_repeat(self) -> None:
        row = self._selected_row()
        if row is None:
            return
        self.push_screen(
            EntryModal("Edit repeat count", "Enter a repeat count from 1 to 99.", "1–99", str(row["repeat"])),
            self._on_repeat_choice,
        )

    def _on_repeat_choice(self, value: str | None) -> None:
        if value is None:
            return
        try:
            repeat = int(value.strip())
            if not 1 <= repeat <= 99:
                raise ValueError
        except ValueError:
            self.notify("Repeat count must be an integer from 1 to 99", severity="error")
            return
        self._stage_row_update({"repeat": repeat}, f"Repeat set to {repeat}; press s to save")

    def action_edit_bpm(self) -> None:
        row = self._selected_row()
        if row is None:
            return
        bpm_raw = row["bpm_raw"]
        current = "" if bpm_raw == 0 else f"{bpm_raw / 120:g}"
        self.push_screen(
            EntryModal("Edit row BPM", "Enter BPM, or leave blank to inherit the pattern tempo.", "inherit", current),
            self._on_bpm_choice,
        )

    def _on_bpm_choice(self, value: str | None) -> None:
        if value is None:
            return
        text = value.strip()
        if not text:
            self._stage_row_update({"bpm_raw": 0}, "Row now inherits the pattern tempo")
            return
        try:
            bpm = float(text)
            bpm_raw = round(bpm * 120)
            if not math.isfinite(bpm) or bpm <= 0 or bpm_raw > 0xFFFFFFFF:
                raise ValueError
        except (ValueError, OverflowError):
            self.notify("Enter a positive BPM value, or leave it blank to inherit", severity="error")
            return
        self._stage_row_update({"bpm_raw": bpm_raw}, f"Row BPM set to {bpm:g}; press s to save")

    def action_edit_length(self) -> None:
        row = self._selected_row()
        if row is None:
            return
        self.push_screen(
            EntryModal("Edit row length", "Enter a row length from 1 to 1024 steps.", "1–1024", str(row["length"])),
            self._on_length_choice,
        )

    def _on_length_choice(self, value: str | None) -> None:
        if value is None:
            return
        try:
            length = int(value.strip())
            if not 1 <= length <= 1024:
                raise ValueError
        except ValueError:
            self.notify("Row length must be an integer from 1 to 1024", severity="error")
            return
        self._stage_row_update({"length": length}, f"Row length set to {length}; press s to save")

    def _toggle_label_edit(self) -> None:
        row = self._selected_row()
        if row is None:
            return
        if self.editing_label_idx is None:
            self.editing_label_idx = row["label_idx"]
            self._show_song(self.active_song_slot)
            self._update_main_help()
            return
        label_idx = self.editing_label_idx
        self.editing_label_idx = None
        self._stage_row_update(
            {"label_idx": label_idx},
            f"Row label set to {self._label_name(label_idx)}; press s to save",
        )
        self._update_main_help()

    @classmethod
    def _label_name(cls, label_idx: int) -> str:
        return next((label for index, label in cls.ROW_LABEL_OPTIONS if index == label_idx), f"T{label_idx}")

    def _cycle_label(self, delta: int) -> None:
        options = self.ROW_LABEL_OPTIONS
        current = next(
            (index for index, (label_idx, _) in enumerate(options) if label_idx == self.editing_label_idx),
            0,
        )
        self.editing_label_idx = options[(current + delta) % len(options)][0]
        self._show_song(self.active_song_slot)

    def _cancel_label_edit(self) -> None:
        if self.editing_label_idx is None:
            return
        self.editing_label_idx = None
        if self.is_mounted and self.songs:
            self._show_song(self.active_song_slot)
            self._update_main_help()

    def _update_main_help(self) -> None:
        if not self.is_mounted:
            return
        if self.editing_label_idx is not None:
            help_text = "LABEL · ↑↓ choose · Enter apply · Esc cancel\nSelect a label; changes remain draft until s"
        else:
            help_text = (
                "↑↓ move rows · ←/→ move columns · Tab / ← at Pattern returns to songs · Enter edits cell\n"
                "Songs Y/X/P bundle · Rows c/m/d · filled = playing · outline = muted · s save"
            )
        self.query_one("#message", Static).update(help_text)

    def action_toggle_mute(self) -> None:
        row = self._selected_row()
        if row is None:
            return
        self.push_screen(
            EntryModal("Toggle track mute", "Enter a track number from 1 to 16.", "1–16"),
            self._on_mute_track_choice,
        )

    def _on_mute_track_choice(self, value: str | None) -> None:
        if value is None:
            return
        try:
            track = int(value.strip())
            if not 1 <= track <= 16:
                raise ValueError
        except ValueError:
            self.notify("Track number must be an integer from 1 to 16", severity="error")
            return
        indices = self._active_row_indices()
        if indices is None:
            return
        if self.session is None:
            return
        rows = self.songs[self.active_song_slot]["rows"]
        for index in indices:
            mute_mask = rows[index]["mute"] ^ (1 << (track - 1))
            # update_row_fields writes big-endian; parsing reads little-endian.
            stored_mask = ((mute_mask & 0xFF) << 8) | ((mute_mask >> 8) & 0xFF)
            self.session.stage({
                "type": "update_rows", "slot": self.active_song_slot,
                "rows": [index], "updates": {"mute_mask": stored_mask},
            })
        toggled_mask = rows[indices[0]]["mute"] ^ (1 << (track - 1))
        state = "muted" if toggled_mask & (1 << (track - 1)) else "unmuted"
        self._refresh_state()
        self.notify(f"Track {track} {state} on {len(indices)} row(s); press s to save")

    def action_rename_song(self) -> None:
        if self.session is None:
            return
        song = self.songs[self.active_song_slot]
        self.push_screen(
            EntryModal("Rename song", "Song names can be up to 16 characters.", "song name", song["name"]),
            self._on_song_name_choice,
        )

    def _on_song_name_choice(self, value: str | None) -> None:
        if value is None:
            return
        name = value.strip()
        if len(name) > 16:
            self.notify("Song names are limited to 16 characters", severity="error")
            return
        if self.session is None:
            return
        self.session.stage({"type": "rename_song", "slot": self.active_song_slot, "name": name})
        self._refresh_state()
        self.notify("Song name updated in the draft; press s to save")

    def action_export_song_file(self) -> None:
        if self.focused is self.query_one("#songs-list", NavigatorList):
            self._set_song_clipboard("cut")
            return
        if self.session is None:
            return
        song = self.songs[self.active_song_slot]
        safe_name = "".join(
            char if char.isalnum() or char in " _-." else "_"
            for char in song["name"]
        ).strip(" .") or "song"
        filename = self.session.path.parent / f"{self.active_song_slot:02d}_{safe_name}.bin"
        self.push_screen(
            EntryModal("Export song backup", "Enter a destination .bin path.", str(filename), str(filename)),
            self._on_export_song_path,
        )

    def _on_export_song_path(self, value: str | None) -> None:
        if value is None or not value.strip() or self.session is None:
            return
        path = Path(value.strip()).expanduser()
        if path.exists():
            self.push_screen(
                ConfirmModal("Replace song backup?", f"{path} already exists. Replace it?", "Replace"),
                lambda confirmed: self._write_song_file(path, confirmed),
            )
            return
        self._write_song_file(path, True)

    def _write_song_file(self, path: Path, confirmed: bool) -> None:
        if not confirmed or self.session is None:
            return
        try:
            raw = self.session.working_raw()
            record = get_song_slots(raw)[self.active_song_slot]
            path.write_bytes(record)
        except Exception as exc:
            self.notify(f"Could not export song: {exc}", severity="error", timeout=10)
            return
        self.notify(f"Exported song slot {self.active_song_slot:02d} to {path}", timeout=10)

    def action_import_song_file(self) -> None:
        self.push_screen(
            EntryModal("Import song backup", f"Enter a .bin path for song slot {self.active_song_slot:02d}."),
            self._on_import_song_file_path,
        )

    def _on_import_song_file_path(self, value: str | None) -> None:
        if value is None or not value.strip() or self.session is None:
            return
        path = Path(value.strip()).expanduser()
        try:
            record = path.read_bytes()
            self.session.stage_song_file_restore(self.active_song_slot, record)
        except Exception as exc:
            self.notify(f"Could not stage song import: {exc}", severity="error", timeout=10)
            return
        self.selected_row_indices.clear()
        self._refresh_state()
        self.notify(f"Song backup staged in slot {self.active_song_slot:02d}; press s to save")

    def action_import_song_project(self) -> None:
        if self.session is None:
            return
        source_sessions = [item for item in self.sessions if item.path != self.session.path]
        tabs = "\n".join(
            f"{index + 1}: {item.display_name if item.is_new_project else item.path.name} ({item.device}, "
            f"{'DRAFT ' + str(len(item.operations)) if item.operations else 'CLEAN'})"
            for index, item in enumerate(source_sessions)
        )
        prompt = "Enter an open project tab number, or a project path."
        if tabs:
            prompt += "\nOpen project tabs:\n" + tabs
        self.push_screen(
            EntryModal("Import song slot", prompt, "tab number or project path"),
            lambda value: self._on_import_song_source(value, source_sessions),
        )

    def _on_import_song_source(self, value: str | None, source_sessions: list[ProjectSession]) -> None:
        if value is None or not value.strip():
            return
        source_input = value.strip()
        source_session = None
        if source_input.isdigit() and 1 <= int(source_input) <= len(source_sessions):
            source_session = source_sessions[int(source_input) - 1]
            source_path = source_session.path
        else:
            source_path = Path(source_input).expanduser().resolve()
            source_session = next((item for item in self.sessions if item.path == source_path), None)
        self.push_screen(
            EntryModal("Source song slot", "Enter a source slot from 0 to 15.", "0–15"),
            lambda slot: self._on_import_song_slot(source_path, source_session, slot),
        )

    def _on_import_song_slot(
        self,
        source_path: Path,
        source_session: ProjectSession | None,
        value: str | None,
    ) -> None:
        if value is None or self.session is None:
            return
        try:
            source_slot = int(value.strip())
            if not 0 <= source_slot < 16:
                raise ValueError
            source_raw = source_session.working_raw() if source_session is not None else None
            self.session.stage_song_import(
                source_path,
                source_slot,
                self.active_song_slot,
                source_raw=source_raw,
            )
        except Exception as exc:
            self.notify(f"Could not stage song import: {exc}", severity="error", timeout=10)
            return
        self.selected_row_indices.clear()
        self._refresh_state()
        self.notify(
            f"Song slot {source_slot:02d} staged in slot {self.active_song_slot:02d}; press s to save"
        )

    def action_export_project_json(self) -> None:
        if self.session is None:
            return
        default = str(self.session.path.with_suffix(".dsm.json"))
        self.push_screen(
            EntryModal(
                "Export full project JSON",
                "Enter a destination path for the full project snapshot.",
                default,
                default,
            ),
            self._on_export_project_json_path,
        )

    def _on_export_project_json_path(self, value: str | None) -> None:
        if value is None or not value.strip() or self.session is None:
            return
        path = Path(value.strip()).expanduser()
        if path.exists():
            self.push_screen(
                ConfirmModal("Replace JSON backup?", f"{path} already exists. Replace it?", "Replace"),
                lambda confirmed: self._write_project_json(path, confirmed),
            )
            return
        self._write_project_json(path, True)

    def _write_project_json(self, path: Path, confirmed: bool) -> None:
        if not confirmed or self.session is None:
            return
        try:
            snapshot = self.session.export_snapshot()
            path.write_text(json.dumps(snapshot, indent=2) + "\n", encoding="utf-8")
        except Exception as exc:
            self.notify(f"Could not export project JSON: {exc}", severity="error", timeout=10)
            return
        self.notify(f"Exported full project snapshot to {path}", timeout=10)

    def action_import_project_json(self) -> None:
        self.push_screen(
            EntryModal("Restore project JSON", "Enter a full DSM JSON snapshot or older arrangement-only JSON path."),
            self._on_import_project_json_path,
        )

    def _on_import_project_json_path(self, value: str | None) -> None:
        if value is None or not value.strip() or self.session is None:
            return
        path = Path(value.strip()).expanduser()
        try:
            backup = json.loads(path.read_text(encoding="utf-8"))
            if backup.get("backup_format") == "dsm-project-state" and backup.get("version") == 1:
                pending_note = (
                    f" This replaces the {len(self.session.operations)} pending operation(s)."
                    if self.session.operations else ""
                )
                message = (
                    f"Stage all patterns and song data from {backup.get('project_file', path.name)}? "
                    f"This replaces the current draft.{pending_note} Assets stored outside the project image, "
                    "such as external samples, stay from the open project file. Nothing is written to a project file until you press s and choose where to save."
                )
                self.push_screen(
                    ConfirmModal("Restore full project snapshot", message, "Stage restore"),
                    lambda confirmed: self._finish_full_snapshot(backup, confirmed),
                )
                return
            if isinstance(backup, dict) and isinstance(backup.get("songs"), list) and len(backup["songs"]) == 16:
                pending_note = (
                    f" This replaces the {len(self.session.operations)} pending operation(s)."
                    if self.session.operations else ""
                )
                message = (
                    "This is an older arrangement-only export. It contains song rows and mutes, "
                    "but no patterns. Current project patterns will be kept. "
                    f"Stage the song data?{pending_note} Nothing is written to a project file until you press s and choose where to save."
                )
                self.push_screen(
                    ConfirmModal("Restore arrangement only", message, "Stage songs"),
                    lambda confirmed: self._finish_legacy_arrangement(backup, confirmed),
                )
                return
            raise ValueError("This is not a supported DSM JSON backup.")
        except Exception as exc:
            self.notify(f"Could not read JSON backup: {exc}", severity="error", timeout=10)

    def _finish_full_snapshot(self, backup: dict, confirmed: bool) -> None:
        if not confirmed or self.session is None:
            return
        try:
            self.session.stage_snapshot(backup)
        except Exception as exc:
            self.notify(f"Could not stage project restore: {exc}", severity="error", timeout=10)
            return
        self.active_song_slot = 0
        self.active_row_index = None
        self.selected_row_indices.clear()
        self._refresh_state()
        self.notify("Full project snapshot staged; press s to save it as a project file", timeout=10)

    def _finish_legacy_arrangement(self, backup: dict, confirmed: bool) -> None:
        if not confirmed or self.session is None:
            return
        try:
            self.session.replace_operations([{"type": "arrangement_restore", "songs": backup["songs"]}])
        except Exception as exc:
            self.notify(f"Could not stage arrangement restore: {exc}", severity="error", timeout=10)
            return
        self.active_song_slot = 0
        self.active_row_index = None
        self.selected_row_indices.clear()
        self._refresh_state()
        self.notify("Arrangement-only JSON staged; existing patterns are unchanged", timeout=10)

    def action_change_pattern(self) -> None:
        if self.focused is self.query_one("#songs-list", NavigatorList):
            self._paste_song_clipboard()
            return
        if self._active_row_indices() is None:
            return
        self.push_screen(
            EntryModal("Change row pattern", "Enter a pattern slot (A01–H16 or 0–127).", "e.g. B04"),
            self._on_pattern_choice,
        )

    def _on_pattern_choice(self, value: str | None) -> None:
        indices = self._active_row_indices()
        if value is None or self.session is None or indices is None:
            return
        text = value.strip().upper()
        try:
            if len(text) >= 2 and text[0] in "ABCDEFGH" and text[1:].isdigit():
                bank_slot = int(text[1:])
                if not 1 <= bank_slot <= 16:
                    raise ValueError
                pattern = (ord(text[0]) - ord("A")) * 16 + bank_slot - 1
            else:
                pattern = int(text)
                if not 0 <= pattern <= 127:
                    raise ValueError
        except ValueError:
            self.notify("Use A01–H16 or a slot number from 0 to 127", severity="error")
            return
        rows = self.songs[self.active_song_slot]["rows"]
        row = rows[indices[0]]
        self.session.stage({
            "type": "retarget",
            "slot": self.active_song_slot,
            "rows": indices,
            "from_pattern": row["pattern"] if len(indices) == 1 else None,
            "to_pattern": pattern,
        })
        self._refresh_state()
        self.notify(f"{len(indices)} row(s) now use {pattern_label(pattern)}; press s to save")

    def action_delete_row(self) -> None:
        indices = self._active_row_indices()
        if self.session is None or indices is None:
            return
        previous_index = self.active_row_index
        remaining = len(self.songs[self.active_song_slot]["rows"]) - len(indices)
        self.session.stage({
            "type": "delete_rows",
            "slot": self.active_song_slot,
            "rows": indices,
        })
        self.selected_row_indices.clear()
        self.active_row_index = min(previous_index, remaining - 1) if remaining else None
        self._refresh_state()
        self.notify(f"Deleted {len(indices)} row(s) from the draft; press s to save")

    def action_undo_change(self) -> None:
        if self.session is None or not self.session.undo():
            self.notify("No staged edit to undo", severity="warning")
            return
        self.selected_row_indices.clear()
        self._refresh_state()
        self.notify("Last staged operation undone")

    def action_redo_change(self) -> None:
        if self.session is None or not self.session.redo():
            self.notify("No staged edit to redo", severity="warning")
            return
        self.selected_row_indices.clear()
        self._refresh_state()
        self.notify("Last undone operation restored")

    def action_open_patterns(self) -> None:
        self._open_patterns(None)

    def action_open_sample_memory(self) -> None:
        if self.session is None:
            return
        if self.session.device != "DT2":
            self.notify("Sample memory analysis is available for Digitakt II projects", severity="warning")
            return
        from .tui_memory import SampleMemoryScreen
        try:
            self.push_screen(SampleMemoryScreen(self.session))
        except Exception as exc:
            self.notify(f"Could not analyze project samples: {exc}", severity="error", timeout=8)

    def action_open_song_pattern_overview(self) -> None:
        if self.session is None:
            return
        from .tui_song_patterns import SongPatternOverviewScreen
        self.push_screen(SongPatternOverviewScreen(self.session))

    def action_open_sample_browser(self) -> None:
        if self.session is None:
            return
        if self.session.device != "DT2":
            self.notify("Sample browsing is available for Digitakt II projects", severity="warning")
            return
        from .tui_sample_browser import SampleBrowserScreen
        try:
            self.push_screen(SampleBrowserScreen(self.session))
        except Exception as exc:
            self.notify(f"Could not browse project samples: {exc}", severity="error", timeout=8)

    def _open_patterns(self, bank_filter: int | None) -> None:
        if self.session is None:
            return
        from .tui_patterns import PatternManagerScreen
        self.push_screen(
            PatternManagerScreen(
                self.session,
                self.sessions,
                bank_filter=bank_filter,
                clipboard_owner=self,
            ),
            self._on_patterns_closed,
        )

    def action_select_bank_a(self) -> None:
        self._open_patterns(0)

    def action_select_bank_b(self) -> None:
        self._open_patterns(1)

    def action_select_bank_c(self) -> None:
        self._open_patterns(2)

    def action_select_bank_d(self) -> None:
        self._open_patterns(3)

    def action_select_bank_e(self) -> None:
        self._open_patterns(4)

    def action_select_bank_f(self) -> None:
        self._open_patterns(5)

    def action_select_bank_g(self) -> None:
        self._open_patterns(6)

    def action_select_bank_h(self) -> None:
        self._open_patterns(7)

    def action_select_all_banks(self) -> None:
        self._open_patterns(None)

    def _on_patterns_closed(self, _result: None) -> None:
        self._refresh_state()

    def action_save_project(self) -> None:
        if self.session is None:
            return
        if not self.session.is_new_project:
            if not self.session.operations:
                self.notify("No staged changes to save", severity="warning")
                return
            self._validate_and_confirm_save(self.session.path)
            return
        self.action_save_project_as()

    def action_save_project_as(self) -> None:
        if self.session is None:
            return
        default_path = (
            self.session.suggested_save_path
            if self.session.is_new_project
            else self.session.path.with_name(f"{self.session.path.stem}_edited{self.session.path.suffix}")
        )
        self.push_screen(
            EntryModal(
                "Save project as",
                "Choose a project filename or full path. Existing destination files are backed up as .bak.",
                str(default_path),
                str(default_path),
            ),
            self._on_save_path,
        )

    def _on_save_path(self, value: str | None) -> None:
        if self.session is None or value is None or not value.strip():
            return
        target = Path(value.strip().strip('"')).expanduser()
        if not target.suffix:
            target = target.with_suffix(self.session.path.suffix)
        target = target.resolve()
        self._validate_and_confirm_save(target)

    def _validate_and_confirm_save(self, target: Path) -> None:
        if self.session is None:
            return
        checks = self.session.validate_save_as(target)
        self.push_screen(
            SaveValidationModal(target, checks),
            lambda proceed: self._confirm_save_target(target) if proceed else None,
        )

    def _confirm_save_target(self, target: Path) -> None:
        if target.exists() and not (
            self.session is not None and target == self.session.path and not self.session.is_new_project
        ):
            self.push_screen(
                ConfirmModal(
                    "Replace existing project?",
                    f"{target} already exists. A .bak copy will be kept before it is replaced.",
                    "Replace",
                ),
                lambda confirmed: self._write_save_as(target) if confirmed else None,
            )
            return
        self._write_save_as(target)

    def _write_save_as(self, target: Path) -> None:
        if self.session is None:
            return
        in_place = target == self.session.path and not self.session.is_new_project
        try:
            saved_path = self.session.save_as(target)
        except Exception as exc:
            self.notify(f"Could not save project: {exc}", severity="error", timeout=10)
            return
        self.project_path = saved_path
        self.project_title = self.session.name or saved_path.name
        self._refresh_state()
        self._refresh_tab_labels()
        if in_place:
            backup = saved_path.with_suffix(saved_path.suffix + ".bak")
            self.notify(f"Saved project in place; backup: {backup}", timeout=10)
        else:
            self.notify(f"Saved project '{self.session.name}' to {saved_path}", timeout=10)

    def action_quit(self) -> None:
        dirty = [session for session in self.sessions if session.operations or session.is_new_project]
        if not dirty:
            self.exit()
            return
        summary = "\n".join(
            f"{session.display_name if session.is_new_project else session.path.name}: "
            + (
                "new project draft not saved"
                if session.is_new_project and not session.operations
                else f"{len(session.operations)} staged change(s)"
            )
            for session in dirty
        )
        self.push_screen(UnsavedExitModal(summary), self._on_exit_choice)

    def _on_exit_choice(self, choice: str | None) -> None:
        if choice == "stay" or choice is None:
            return
        if choice == "discard":
            for session in self.sessions:
                session.discard()
            self.exit()
            return
def run_tui(project_path: Path | str | None = None) -> None:
    """Start the terminal project browser for ``project_path``."""
    ProjectBrowser(project_path).run()
