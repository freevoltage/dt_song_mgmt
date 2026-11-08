"""Textual terminal interface for Elektron project management."""

from __future__ import annotations

import json
import math
import re
from pathlib import Path

from textual.app import App, ComposeResult
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.screen import ModalScreen
from textual.widgets import Button, DataTable, Footer, Input, Label, Static, Tab, Tabs

from .session import ProjectSession
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


class SongPatternMappingModal(ModalScreen[list[dict] | None]):
    """Edit a song bundle's source-to-destination pattern slot mapping."""

    CSS = """
    SongPatternMappingModal { align: center middle; background: $background 60%; }
    #song-pattern-map-dialog { width: 96%; height: 90%; padding: 1 2; border: solid $primary; background: $surface; }
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


class ProjectBrowser(App[None]):
    """Browse a project's song slots and song rows in the terminal."""

    TITLE = "Elektron Digi Song Mode Manager"
    SUB_TITLE = "Project browser"
    CSS = """
    Screen {
        layout: vertical;
        background: #101010;
    }
    #project-header {
        height: 2;
        padding: 0 2;
        background: #101010;
        border-bottom: solid #37342e;
    }
    #project-tabs {
        height: 2;
        background: #101010;
        padding: 0 1;
    }
    Tabs { background: #101010; }
    Tab { background: #101010; color: #8d887d; border: none; }
    Tab.-active { background: #101010; color: #d6a04b; text-style: bold; }
    Tabs > .underline--bar { color: #d6a04b; background: #d6a04b; }
    #project-banner {
        width: 1fr;
        content-align: left middle;
        color: #e4e0d6;
        text-style: bold;
    }
    #device-banner {
        width: auto;
        min-width: 26;
        content-align: right middle;
        color: #d6a04b;
        text-style: bold;
    }
    #workspace {
        height: 1fr;
        padding: 0 2;
        layout: horizontal;
    }
    #songs-pane {
        width: 30;
        min-width: 24;
        border-right: solid #37342e;
        padding: 0 2 0 0;
    }
    #rows-pane {
        width: 1fr;
        min-width: 32;
        padding: 0 0 0 2;
    }
    .pane-title {
        height: 2;
        margin: 0;
        color: #a49f93;
        text-style: bold;
    }
    DataTable {
        height: 1fr;
        background: #101010;
        border: none;
    }
    DataTable > .datatable--header {
        background: #191919;
        color: #a49f93;
    }
    DataTable > .datatable--cursor {
        background: #25221c;
        color: #f1c36d;
        text-style: bold;
    }
    DataTable:focus > .datatable--cursor {
        background: #d6a04b;
        color: #15120d;
    }
    #message {
        height: 2;
        color: #a49f93;
        padding: 0 2;
        background: #101010;
        border-top: solid #37342e;
    }
    Footer { background: #101010; color: #a49f93; }
    FooterKey { background: #101010; }
    FooterKey > .footer-key--key { background: #25221c; color: #d6a04b; }
    Button { border: none; background: #222222; color: #dedbd2; }
    """
    BINDINGS = [
        ("q", "quit", "Quit"),
        ("escape", "quit", "Quit"),
        ("tab", "focus_next", "Switch pane"),
        ("space", "toggle_row_selection", "Select row"),
        ("p", "change_pattern", "Set row pattern"),
        ("d", "delete_row", "Delete row"),
        ("alt+up", "move_row_up", "Move row up"),
        ("alt+down", "move_row_down", "Move row down"),
        ("c", "copy_row", "Copy row"),
        ("m", "move_row", "Move row"),
        ("r", "edit_repeat", "Edit repeat"),
        ("b", "edit_bpm", "Edit BPM"),
        ("l", "edit_length", "Edit length"),
        ("t", "toggle_mute", "Toggle track mute"),
        ("n", "rename_song", "Rename song"),
        ("w", "swap_song", "Swap song slots"),
        ("k", "clear_song", "Clear song rows"),
        ("e", "empty_song", "Empty song slot"),
        ("x", "export_song_file", "Export song .bin"),
        ("v", "import_song_file", "Import song .bin"),
        ("g", "import_song_project", "Import song slot"),
        ("ctrl+e", "export_project_json", "Export project JSON"),
        ("ctrl+i", "import_project_json", "Restore project JSON"),
        ("s", "save_project", "Save project as"),
        ("ctrl+s", "save_project", "Save project as"),
        ("u", "undo_change", "Undo staged edit"),
        ("ctrl+y", "redo_change", "Redo staged edit"),
        ("f2", "open_patterns", "Pattern manager"),
        ("f3", "open_sample_memory", "Sample memory"),
        ("f4", "open_song_pattern_overview", "Song pattern overview"),
        ("ctrl+o", "open_project", "Open project"),
        ("ctrl+tab", "next_project", "Next project"),
        ("ctrl+shift+tab", "previous_project", "Previous project"),
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

    def __init__(self, project_path: Path | str) -> None:
        super().__init__()
        self.project_path = Path(project_path).expanduser().resolve()
        self.project_title = self.project_path.name
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
        self.selected_row_indices: set[int] = set()

    def compose(self) -> ComposeResult:
        with Horizontal(id="project-header"):
            yield Static("Loading project…", id="project-banner")
            yield Static("", id="device-banner")
        yield Tabs(Tab(self.project_path.name, id="project-0"), id="project-tabs")
        with Horizontal(id="workspace"):
            with Vertical(id="songs-pane"):
                yield Static("SONG SLOTS", classes="pane-title")
                yield DataTable(id="songs-table", cursor_type="row", zebra_stripes=True)
            with Vertical(id="rows-pane"):
                yield Static("SONG ROWS", classes="pane-title")
                yield DataTable(id="rows-table", cursor_type="row", zebra_stripes=True)
        yield Static("Space select rows · Alt+↑/↓ reorder · c copy · m move · Y/X/P song bundle on slots · s save · F2 patterns · F4 song patterns", id="message")
        yield Footer()

    def on_key(self, event) -> None:
        """Use Y/X/P for song bundles only while the song-slot table is focused."""
        if event.key != "y" or self.session is None:
            return
        try:
            songs_table = self.query_one("#songs-table", DataTable)
        except Exception:
            return
        if self.focused is not songs_table:
            return
        event.stop()
        self._set_song_clipboard("copy")

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
                source_session.path.name,
                source_slot,
                self.session.path.name,
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
            self.notify(
                f"Moved song {source_slot:02d} to slot {destination_slot:02d}; both project drafts are staged. Press s to save each project."
            )
        else:
            self.notify(
                f"Copied song {source_slot:02d} to slot {destination_slot:02d} with patterns; press s to save."
            )
        if self.session is not None:
            self._refresh_state()

    def on_mount(self) -> None:
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
            return

        songs_table = self.query_one("#songs-table", DataTable)
        songs_table.add_columns("Slot", "Song", "Rows")
        rows_table = self.query_one("#rows-table", DataTable)
        rows_table.add_columns("#", "Pattern", "Label", "Rep", "BPM", "Length", "Muted tracks")
        self._refresh_state()
        songs_table.focus()

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
        self.project_title = session.name or session.path.name
        self.device = session.device
        self.active_song_slot = 0
        self.active_row_index = None
        self.selected_row_indices.clear()
        self._refresh_state()

    def _tab_label(self, session: ProjectSession) -> str:
        pending = len(session.operations)
        marker = f"*{pending}" if pending else "clean"
        return f"{session.path.name} [{session.device} {marker}]"

    def _refresh_tab_labels(self) -> None:
        tabs = self.query_one("#project-tabs", Tabs)
        for tab_id, session in self._tab_sessions.items():
            tab = tabs.get_tab(tab_id)
            if tab is not None:
                tab.label = self._tab_label(session)

    def action_open_project(self) -> None:
        self.push_screen(
            EntryModal("Open project", "Enter a .dn2prj or .dt2prj file path."),
            self._on_open_project,
        )

    def _on_open_project(self, value: str | None) -> None:
        if value is None or not value.strip():
            return
        path = Path(value.strip()).expanduser().resolve()
        for tab_id, session in self._tab_sessions.items():
            if session.path == path:
                tabs = self.query_one("#project-tabs", Tabs)
                tabs.active = tab_id
                self._activate_project(tab_id, session)
                return
        try:
            session = ProjectSession(path)
        except Exception as exc:
            self.notify(f"Could not open project: {exc}", severity="error", timeout=10)
            return
        tab_id = f"project-{len(self._tab_sessions)}"
        self.sessions.append(session)
        self._tab_sessions[tab_id] = session
        tabs = self.query_one("#project-tabs", Tabs)
        tabs.add_tab(Tab(self._tab_label(session), id=tab_id))
        tabs.active = tab_id
        self._activate_project(tab_id, session)

    def action_next_project(self) -> None:
        self.query_one("#project-tabs", Tabs).action_next_tab()

    def action_previous_project(self) -> None:
        self.query_one("#project-tabs", Tabs).action_previous_tab()

    def on_data_table_row_selected(self, event: DataTable.RowSelected) -> None:
        if event.data_table.id != "songs-table":
            return
        try:
            slot = int(event.row_key.value)
        except (TypeError, ValueError):
            return
        self.active_song_slot = slot
        self.active_row_index = None
        self.selected_row_indices.clear()
        self._show_song(slot)

    def on_data_table_row_highlighted(self, event: DataTable.RowHighlighted) -> None:
        if event.row_key is None:
            return
        try:
            index = int(event.row_key.value)
        except (TypeError, ValueError):
            return
        if event.data_table.id == "songs-table":
            if index != self.active_song_slot:
                self.selected_row_indices.clear()
            self.active_song_slot = index
            self.active_row_index = None
            self._show_song(index)
        elif event.data_table.id == "rows-table":
            self.active_row_index = index

    def _refresh_state(self) -> None:
        if self.session is None:
            return
        state = self.session.state()
        self.songs = state["songs"]
        self.pattern_names = collect_pattern_names(self.session.working_raw())
        if self.songs:
            self.active_song_slot = min(self.active_song_slot, len(self.songs) - 1)
        pending = state["pending_changes"]
        marker = f"DRAFT {pending}" if pending else "CLEAN"
        self.query_one("#project-banner", Static).update(
            f"{self.project_path.name}  ·  {self.project_title}"
        )
        self.query_one("#device-banner", Static).update(f"{self.device}  ·  {marker}")
        self._refresh_tab_labels()
        songs_table = self.query_one("#songs-table", DataTable)
        songs_table.clear(columns=False)
        for song in self.songs:
            songs_table.add_row(
                f"{song['slot']:02d}", song["name"], str(song["row_count"]),
                key=str(song["slot"]),
            )
        if self.songs:
            songs_table.move_cursor(row=self.active_song_slot, column=0)
            self._show_song(self.active_song_slot)

    def _show_song(self, slot: int) -> None:
        rows_table = self.query_one("#rows-table", DataTable)
        rows_table.clear(columns=False)
        song = self.songs[slot]
        valid_indices = set(range(len(song["rows"])))
        self.selected_row_indices.intersection_update(valid_indices)
        selected_row = self.active_row_index
        for index, row in enumerate(song["rows"]):
            pattern_id = row["pattern"]
            pattern_name = row.get("pattern_name") or pattern_label(pattern_id)
            custom_name = self.pattern_names[pattern_id] if 0 <= pattern_id < len(self.pattern_names) else ""
            if custom_name:
                pattern_name = f"{pattern_name} {custom_name}"
            muted = [f"T{track}" for track in range(1, 17) if row["mute"] & (1 << (track - 1))]
            rows_table.add_row(
                f"{'✓' if index in self.selected_row_indices else ' '} {index + 1}",
                pattern_name,
                row["label"] or "—",
                f"×{row['repeat']}",
                format_bpm(row["bpm_raw"]),
                format_length(row["length"]),
                ",".join(muted) if muted else "—",
                key=str(index),
            )
        self.active_row_index = (
            min(selected_row, len(song["rows"]) - 1)
            if selected_row is not None and song["rows"]
            else None
        )
        if self.active_row_index is not None:
            rows_table.move_cursor(row=self.active_row_index, column=0)
        self.query_one("#rows-pane .pane-title", Static).update(
            f"SONG {slot:02d}  ·  {song['name']}  ·  {song['row_count']} ROWS"
        )

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
        if self.focused is self.query_one("#songs-table", DataTable):
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
            f"{index + 1}: {item.path.name} ({item.device}, "
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
        if self.focused is self.query_one("#songs-table", DataTable):
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
        default_path = self.session.path.with_name(
            f"{self.session.path.stem}_edited{self.session.path.suffix}"
        )
        self.push_screen(
            EntryModal(
                "Save project as",
                "Choose a new project filename or full path. The original stays untouched.",
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
        if target == self.session.path:
            self.notify("Save As needs a new path; the source project is kept unchanged", severity="error")
            return
        if self.session is None:
            return
        checks = self.session.validate_save_as(target)
        self.push_screen(
            SaveValidationModal(target, checks),
            lambda proceed: self._confirm_save_target(target) if proceed else None,
        )

    def _confirm_save_target(self, target: Path) -> None:
        if target.exists():
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
        try:
            saved_path = self.session.save_as(target)
        except Exception as exc:
            self.notify(f"Could not save project: {exc}", severity="error", timeout=10)
            return
        self.project_path = saved_path
        self.project_title = self.session.name or saved_path.name
        self._refresh_state()
        self._refresh_tab_labels()
        self.notify(f"Saved project '{self.session.name}' to {saved_path}", timeout=10)

    def action_quit(self) -> None:
        dirty = [session for session in self.sessions if session.operations]
        if not dirty:
            self.exit()
            return
        summary = "\n".join(
            f"{session.path.name}: {len(session.operations)} staged change(s)"
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
def run_tui(project_path: Path | str) -> None:
    """Start the terminal project browser for ``project_path``."""
    ProjectBrowser(project_path).run()
