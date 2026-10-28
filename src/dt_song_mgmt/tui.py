"""Read-only Textual project browser (first TUI slice)."""

from __future__ import annotations

from pathlib import Path

from textual.app import App, ComposeResult
from textual.containers import Horizontal, Vertical
from textual.screen import ModalScreen
from textual.widgets import Button, DataTable, Footer, Input, Label, Static

from .session import ProjectSession
from .songs import (
    format_bpm,
    format_length,
    collect_pattern_names,
    pattern_label,
)


class EntryModal(ModalScreen[str | None]):
    """Small input prompt for a single TUI action."""

    CSS = """
    EntryModal { align: center middle; background: $background 60%; }
    #entry-dialog { width: 64; height: auto; padding: 1 2; border: round $primary; background: $surface; }
    #entry-dialog Input { margin: 1 0; }
    #entry-buttons { height: 3; align-horizontal: right; }
    #entry-buttons Button { margin-left: 1; }
    """

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

    def on_input_submitted(self, event: Input.Submitted) -> None:
        self.dismiss(event.value)

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "continue":
            self.dismiss(self.query_one("#entry-input", Input).value)
        else:
            self.dismiss(None)


class ConfirmApplyModal(ModalScreen[bool]):
    """Final one-step confirmation before writing the project file."""

    CSS = """
    ConfirmApplyModal { align: center middle; background: $background 60%; }
    #confirm-dialog { width: 72; height: auto; padding: 1 2; border: round $warning; background: $surface; }
    #confirm-buttons { height: 3; align-horizontal: right; }
    #confirm-buttons Button { margin-left: 1; }
    """

    def __init__(self, summary: str):
        super().__init__()
        self.summary = summary

    def compose(self) -> ComposeResult:
        with Vertical(id="confirm-dialog"):
            yield Label("Apply staged changes?")
            yield Static(self.summary)
            yield Static("A .bak backup will be created before writing the project.")
            with Horizontal(id="confirm-buttons"):
                yield Button("Cancel", id="cancel")
                yield Button("Apply", variant="warning", id="apply")

    def on_button_pressed(self, event: Button.Pressed) -> None:
        self.dismiss(event.button.id == "apply")


class UnsavedExitModal(ModalScreen[str | None]):
    """Offer explicit choices before closing a session with staged edits."""

    CSS = """
    UnsavedExitModal { align: center middle; background: $background 60%; }
    #exit-dialog { width: 72; height: auto; padding: 1 2; border: round $warning; background: $surface; }
    #exit-buttons { height: 3; align-horizontal: right; }
    #exit-buttons Button { margin-left: 1; }
    """

    def compose(self) -> ComposeResult:
        with Vertical(id="exit-dialog"):
            yield Label("There are unapplied project changes.")
            yield Static("Apply writes the project after creating a .bak backup.")
            with Horizontal(id="exit-buttons"):
                yield Button("Stay", id="stay")
                yield Button("Discard & Quit", id="discard", variant="error")
                yield Button("Apply & Quit", id="apply", variant="warning")

    def on_button_pressed(self, event: Button.Pressed) -> None:
        self.dismiss(event.button.id)


class ProjectBrowser(App[None]):
    """Browse a project's song slots and song rows in the terminal."""

    TITLE = "Elektron Digi Song Mode Manager"
    SUB_TITLE = "Project browser"
    CSS = """
    Screen {
        layout: vertical;
        background: #101216;
    }
    #project-banner {
        height: 3;
        padding: 0 1;
        background: #1c222b;
        color: #f3f4f6;
        content-align: left middle;
        text-style: bold;
    }
    #workspace {
        height: 1fr;
        padding: 1;
        layout: horizontal;
    }
    #songs-pane {
        width: 34;
        min-width: 27;
        border: round #3b4654;
        padding: 0 1;
    }
    #rows-pane {
        width: 1fr;
        min-width: 48;
        border: round #3b4654;
        padding: 0 1;
    }
    .pane-title {
        height: 1;
        margin: 0 0 1 0;
        color: #8fd3c7;
        text-style: bold;
    }
    DataTable {
        height: 1fr;
        background: #101216;
    }
    #message {
        height: 1;
        color: #9ca3af;
        padding: 0 1;
    }
    """
    BINDINGS = [
        ("q", "quit", "Quit"),
        ("escape", "quit", "Quit"),
        ("tab", "focus_next", "Switch pane"),
        ("p", "change_pattern", "Set row pattern"),
        ("d", "delete_row", "Delete row"),
        ("ctrl+s", "apply_changes", "Apply changes"),
        ("u", "undo_change", "Undo staged edit"),
    ]

    def __init__(self, project_path: Path | str) -> None:
        super().__init__()
        self.project_path = Path(project_path).expanduser().resolve()
        self.project_title = self.project_path.name
        self.device = "Unknown device"
        self.songs: list[dict] = []
        self.pattern_names: list[str] = []
        self.session: ProjectSession | None = None
        self.active_song_slot = 0
        self.active_row_index: int | None = None

    def compose(self) -> ComposeResult:
        yield Static("Loading project…", id="project-banner")
        with Horizontal(id="workspace"):
            with Vertical(id="songs-pane"):
                yield Static("SONG SLOTS", classes="pane-title")
                yield DataTable(id="songs-table", cursor_type="row", zebra_stripes=True)
            with Vertical(id="rows-pane"):
                yield Static("SONG ROWS", classes="pane-title")
                yield DataTable(id="rows-table", cursor_type="row", zebra_stripes=True)
        yield Static("↑/↓ select · Tab switch pane · q quit", id="message")
        yield Footer()

    def on_mount(self) -> None:
        try:
            self.session = ProjectSession(self.project_path)
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

    def on_data_table_row_selected(self, event: DataTable.RowSelected) -> None:
        if event.data_table.id != "songs-table":
            return
        try:
            slot = int(event.row_key.value)
        except (TypeError, ValueError):
            return
        self._show_song(slot)

    def on_data_table_row_highlighted(self, event: DataTable.RowHighlighted) -> None:
        if event.row_key is None:
            return
        try:
            index = int(event.row_key.value)
        except (TypeError, ValueError):
            return
        if event.data_table.id == "songs-table":
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
        marker = f"PENDING {pending}" if pending else "CLEAN"
        self.query_one("#project-banner", Static).update(
            f"{self.project_path.name}  ·  {self.project_title}  ·  {self.device}  ·  {marker}"
        )
        songs_table = self.query_one("#songs-table", DataTable)
        songs_table.clear(columns=False)
        for song in self.songs:
            songs_table.add_row(
                f"{song['slot']:02d}", song["name"], str(song["row_count"]),
                key=str(song["slot"]),
            )
        if self.songs:
            self._show_song(self.active_song_slot)

    def _show_song(self, slot: int) -> None:
        rows_table = self.query_one("#rows-table", DataTable)
        rows_table.clear(columns=False)
        song = self.songs[slot]
        selected_row = self.active_row_index
        for index, row in enumerate(song["rows"]):
            pattern_id = row["pattern"]
            pattern_name = row.get("pattern_name") or pattern_label(pattern_id)
            custom_name = self.pattern_names[pattern_id] if 0 <= pattern_id < len(self.pattern_names) else ""
            if custom_name:
                pattern_name = f"{pattern_name} {custom_name}"
            muted = [f"T{track}" for track in range(1, 17) if row["mute"] & (1 << (track - 1))]
            rows_table.add_row(
                str(index + 1),
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
        self.query_one("#rows-pane .pane-title", Static).update(
            f"SONG {slot:02d}  ·  {song['name']}  ·  {song['row_count']} ROWS"
        )

    def action_change_pattern(self) -> None:
        if self.active_row_index is None:
            self.notify("Select a song row first", severity="warning")
            return
        self.push_screen(
            EntryModal("Change row pattern", "Enter a pattern slot (A01–H16 or 0–127).", "e.g. B04"),
            self._on_pattern_choice,
        )

    def _on_pattern_choice(self, value: str | None) -> None:
        if value is None or self.session is None or self.active_row_index is None:
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
        row = self.songs[self.active_song_slot]["rows"][self.active_row_index]
        self.session.stage({
            "type": "retarget",
            "slot": self.active_song_slot,
            "rows": [self.active_row_index],
            "from_pattern": row["pattern"],
            "to_pattern": pattern,
        })
        self._refresh_state()
        self.notify(f"Row now uses {pattern_label(pattern)}; apply to save")

    def action_delete_row(self) -> None:
        if self.session is None or self.active_row_index is None:
            self.notify("Select a song row first", severity="warning")
            return
        self.session.stage({
            "type": "delete_rows",
            "slot": self.active_song_slot,
            "rows": [self.active_row_index],
        })
        self.active_row_index = None
        self._refresh_state()
        self.notify("Row deleted from the draft; apply to save")

    def action_undo_change(self) -> None:
        if self.session is None or not self.session.operations:
            self.notify("No staged edit to undo", severity="warning")
            return
        self.session.operations.pop()
        self._refresh_state()
        self.notify("Last staged operation undone")

    def action_apply_changes(self) -> None:
        if self.session is None or not self.session.operations:
            self.notify("No staged changes to apply", severity="warning")
            return
        preview = self.session.preview()
        types = [operation.get("type", "edit") for operation in self.session.operations]
        summary = (
            f"{len(types)} staged operation(s): {', '.join(types)}.\n"
            f"{len(preview['changes'])} song slot(s) have arrangement changes."
        )
        self.push_screen(ConfirmApplyModal(summary), self._on_apply_confirmation)

    def action_quit(self) -> None:
        if self.session is None or not self.session.operations:
            self.exit()
            return
        self.push_screen(UnsavedExitModal(), self._on_exit_choice)

    def _on_exit_choice(self, choice: str | None) -> None:
        if choice == "stay" or choice is None:
            return
        if self.session is None:
            self.exit()
            return
        if choice == "discard":
            self.session.discard()
            self.exit()
            return
        if choice == "apply":
            try:
                backup = self.session.apply()
            except Exception as exc:
                self.notify(f"Could not apply changes: {exc}", severity="error", timeout=10)
                return
            self.notify(f"Applied. Backup: {backup}", timeout=10)
            self.exit()

    def _on_apply_confirmation(self, confirmed: bool) -> None:
        if not confirmed or self.session is None:
            return
        try:
            backup = self.session.apply()
        except Exception as exc:
            self.notify(f"Could not apply changes: {exc}", severity="error", timeout=10)
            return
        self._refresh_state()
        self.notify(f"Applied. Backup: {backup}", timeout=10)


def run_tui(project_path: Path | str) -> None:
    """Start the terminal project browser for ``project_path``."""
    ProjectBrowser(project_path).run()
