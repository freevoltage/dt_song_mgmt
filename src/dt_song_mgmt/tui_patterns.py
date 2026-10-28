"""Pattern manager screen for the Textual terminal interface."""

from __future__ import annotations

from textual.app import ComposeResult
from textual.containers import Horizontal, Vertical
from textual.screen import ModalScreen
from textual.widgets import Button, DataTable, Footer, Input, Label, Static

from .patterns import get_all_patterns_info
from .songs import pattern_label


class PatternEntryModal(ModalScreen[str | None]):
    """Prompt for a pattern slot, name, or source project path."""

    CSS = """
    PatternEntryModal { align: center middle; background: $background 60%; }
    #pattern-entry-dialog { width: 68; height: auto; padding: 1 2; border: round $primary; background: $surface; }
    #pattern-entry-dialog Input { margin: 1 0; }
    #pattern-entry-buttons { height: 3; align-horizontal: right; }
    #pattern-entry-buttons Button { margin-left: 1; }
    """

    BINDINGS = [("escape", "cancel", "Cancel")]

    def __init__(self, title: str, prompt: str, placeholder: str = "", initial: str = ""):
        super().__init__()
        self.title_text = title
        self.prompt_text = prompt
        self.placeholder = placeholder
        self.initial = initial

    def compose(self) -> ComposeResult:
        with Vertical(id="pattern-entry-dialog"):
            yield Label(self.title_text)
            yield Static(self.prompt_text)
            yield Input(value=self.initial, placeholder=self.placeholder, id="pattern-entry")
            with Horizontal(id="pattern-entry-buttons"):
                yield Button("Cancel", id="cancel")
                yield Button("Continue", variant="primary", id="continue")

    def on_mount(self) -> None:
        self.query_one("#pattern-entry", Input).focus()

    def on_input_submitted(self, event: Input.Submitted) -> None:
        self.dismiss(event.value)

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "continue":
            self.dismiss(self.query_one("#pattern-entry", Input).value)
        else:
            self.dismiss(None)

    def action_cancel(self) -> None:
        self.dismiss(None)


class PatternManagerScreen(ModalScreen[None]):
    """Search and stage operations on the 128 pattern slots."""

    CSS = """
    PatternManagerScreen { align: center middle; background: $background 60%; }
    #pattern-window { width: 94%; height: 90%; border: round $primary; background: $surface; padding: 1 2; }
    #pattern-heading { height: 1; color: $text; text-style: bold; }
    #pattern-search { height: 3; margin: 1 0; }
    #pattern-table { height: 1fr; }
    DataTable:focus { border: tall $accent; }
    """

    BINDINGS = [
        ("escape", "close", "Back"),
        ("/", "focus_filter", "Search"),
        ("c", "copy_pattern", "Copy"),
        ("m", "move_pattern", "Move"),
        ("d", "clear_pattern", "Clear"),
        ("r", "rename_pattern", "Rename"),
        ("i", "import_pattern", "Import"),
    ]

    def __init__(self, session):
        super().__init__()
        self.session = session
        self.selected_pattern = 0
        self.filter_text = ""

    def compose(self) -> ComposeResult:
        with Vertical(id="pattern-window"):
            yield Static("PATTERN MANAGER", id="pattern-heading")
            yield Input(placeholder="Filter by bank, slot, or pattern name…", id="pattern-search")
            yield DataTable(id="pattern-table", cursor_type="row", zebra_stripes=True)
        yield Footer()

    def on_mount(self) -> None:
        table = self.query_one("#pattern-table", DataTable)
        table.add_columns("Slot", "Pattern name", "Song rows")
        self._refresh_table()
        table.focus()

    def on_input_changed(self, event: Input.Changed) -> None:
        if event.input.id == "pattern-search":
            self.filter_text = event.value.strip().casefold()
            self._refresh_table()

    def on_data_table_row_highlighted(self, event: DataTable.RowHighlighted) -> None:
        if event.data_table.id != "pattern-table" or event.row_key is None:
            return
        try:
            self.selected_pattern = int(event.row_key.value)
        except (TypeError, ValueError):
            pass

    def _visible_patterns(self) -> list[dict]:
        patterns = get_all_patterns_info(self.session.working_raw())
        if not self.filter_text:
            return patterns
        return [
            pattern for pattern in patterns
            if self.filter_text in pattern["label"].casefold()
            or self.filter_text in pattern["name"].casefold()
        ]

    def _refresh_table(self) -> None:
        table = self.query_one("#pattern-table", DataTable)
        patterns = self._visible_patterns()
        table.clear(columns=False)
        for pattern in patterns:
            name = pattern["name"].strip() or "(unnamed)"
            table.add_row(
                pattern["label"],
                name,
                str(pattern["ref_count"]),
                key=str(pattern["index"]),
            )
        if patterns:
            visible_indices = [pattern["index"] for pattern in patterns]
            if self.selected_pattern not in visible_indices:
                self.selected_pattern = visible_indices[0]
            table.move_cursor(row=visible_indices.index(self.selected_pattern), column=0)

    def action_focus_filter(self) -> None:
        self.query_one("#pattern-search", Input).focus()

    def _stage(self, operation: dict, message: str) -> None:
        try:
            self.session.stage(operation)
            self._refresh_table()
            self.app.notify(message)
        except Exception as exc:
            self.app.notify(str(exc), severity="error", timeout=8)

    def _prompt_slot(self, title: str, callback) -> None:
        self.app.push_screen(
            PatternEntryModal(title, "Enter a destination slot (A01–H16 or 0–127).", "e.g. B04"),
            callback,
        )

    @staticmethod
    def _parse_slot(value: str) -> int:
        text = value.strip().upper()
        if len(text) >= 2 and text[0] in "ABCDEFGH" and text[1:].isdigit():
            slot = int(text[1:])
            if not 1 <= slot <= 16:
                raise ValueError
            return (ord(text[0]) - ord("A")) * 16 + slot - 1
        slot = int(text)
        if not 0 <= slot <= 127:
            raise ValueError
        return slot

    def _on_copy_destination(self, value: str | None) -> None:
        if value is None:
            return
        try:
            destination = self._parse_slot(value)
        except ValueError:
            self.app.notify("Use A01–H16 or a slot number from 0 to 127", severity="error")
            return
        if destination == self.selected_pattern:
            self.app.notify("Source and destination are the same slot", severity="warning")
            return
        source = self.selected_pattern
        self._stage(
            {"type": "pattern_copy", "src_idx": source, "dst_idx": destination},
            f"Copied {pattern_label(source)} to {pattern_label(destination)} in the draft",
        )
        self.selected_pattern = destination
        self._refresh_table()

    def _on_move_destination(self, value: str | None) -> None:
        if value is None:
            return
        try:
            destination = self._parse_slot(value)
        except ValueError:
            self.app.notify("Use A01–H16 or a slot number from 0 to 127", severity="error")
            return
        if destination == self.selected_pattern:
            self.app.notify("Source and destination are the same slot", severity="warning")
            return
        source = self.selected_pattern
        self._stage(
            {"type": "pattern_move", "src_idx": source, "dst_idx": destination},
            f"Moved {pattern_label(source)} to {pattern_label(destination)} in the draft",
        )
        self.selected_pattern = destination
        self._refresh_table()

    def action_copy_pattern(self) -> None:
        self._prompt_slot("Copy pattern", self._on_copy_destination)

    def action_move_pattern(self) -> None:
        self._prompt_slot("Move pattern", self._on_move_destination)

    def action_clear_pattern(self) -> None:
        slot = self.selected_pattern
        self._stage(
            {"type": "pattern_clear", "pat_idx": slot},
            f"Cleared {pattern_label(slot)} in the draft",
        )

    def action_rename_pattern(self) -> None:
        slot = self.selected_pattern
        self.app.push_screen(
            PatternEntryModal(
                "Rename pattern",
                "Pattern names can be up to 16 characters. Leave blank to clear the custom name.",
                "pattern name",
                get_all_patterns_info(self.session.working_raw())[slot]["name"],
            ),
            self._on_rename,
        )

    def _on_rename(self, value: str | None) -> None:
        if value is None:
            return
        name = value.strip()
        if len(name) > 16:
            self.app.notify("Pattern names are limited to 16 characters", severity="error")
            return
        self._stage(
            {"type": "pattern_rename", "pat_idx": self.selected_pattern, "name": name},
            f"Renamed {pattern_label(self.selected_pattern)} in the draft",
        )

    def action_import_pattern(self) -> None:
        self.app.push_screen(
            PatternEntryModal("Import pattern", "Enter the source .dn2prj or .dt2prj path."),
            self._on_import_source,
        )

    def _on_import_source(self, value: str | None) -> None:
        if value is None or not value.strip():
            return
        source_path = value.strip()
        self.app.push_screen(
            PatternEntryModal("Source pattern", "Enter the source slot (A01–H16 or 0–127).", "e.g. A01"),
            lambda slot: self._on_import_slot(source_path, slot),
        )

    def _on_import_slot(self, source_path: str, value: str | None) -> None:
        if value is None:
            return
        try:
            source_slot = self._parse_slot(value)
        except ValueError:
            self.app.notify("Use A01–H16 or a slot number from 0 to 127", severity="error")
            return
        destination = self.selected_pattern
        try:
            self.session.stage_pattern_import(
                source_path,
                [{"src_idx": source_slot, "dst_idx": destination}],
            )
            self._refresh_table()
            self.app.notify(
                f"Imported {pattern_label(source_slot)} to {pattern_label(destination)} in the draft"
            )
        except Exception as exc:
            self.app.notify(str(exc), severity="error", timeout=10)

    def action_close(self) -> None:
        self.dismiss()


__all__ = ["PatternManagerScreen"]
