"""Pattern manager screen for the Textual terminal interface."""

from __future__ import annotations

import json

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
        ("1", "filter_bank_a", "Bank A"),
        ("2", "filter_bank_b", "Bank B"),
        ("3", "filter_bank_c", "Bank C"),
        ("4", "filter_bank_d", "Bank D"),
        ("5", "filter_bank_e", "Bank E"),
        ("6", "filter_bank_f", "Bank F"),
        ("7", "filter_bank_g", "Bank G"),
        ("8", "filter_bank_h", "Bank H"),
        ("0", "filter_all_banks", "All banks"),
        ("y", "yank_pattern", "Yank pattern"),
        ("x", "cut_pattern_to_clipboard", "Cut pattern"),
        ("p", "paste_pattern", "Paste pattern"),
        ("c", "copy_pattern", "Copy"),
        ("m", "move_pattern", "Move"),
        ("d", "clear_pattern", "Clear"),
        ("r", "rename_pattern", "Rename"),
        ("i", "import_pattern", "Import"),
    ]

    def __init__(self, session, sessions=None, bank_filter: int | None = None, clipboard_owner=None):
        super().__init__()
        self.session = session
        self.sessions = list(sessions or [session])
        self.clipboard_owner = clipboard_owner
        self.selected_pattern = 0
        self.filter_text = ""
        self.bank_filter = bank_filter

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
        if self.bank_filter is not None:
            patterns = [pattern for pattern in patterns if pattern["index"] // 16 == self.bank_filter]
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
        bank_label = "ALL BANKS" if self.bank_filter is None else f"BANK {chr(ord('A') + self.bank_filter)}"
        heading = f"PATTERN MANAGER · {bank_label} · 1–8 SELECT BANK · 0 ALL"
        clipboard = self._clipboard()
        if clipboard:
            action = "CUT" if clipboard["mode"] == "cut" else "COPY"
            heading += f" · CLIPBOARD {action} {pattern_label(clipboard['slot'])}"
        self.query_one("#pattern-heading", Static).update(heading)
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

    def _select_bank(self, bank: int | None) -> None:
        self.bank_filter = bank
        self._refresh_table()

    def action_filter_bank_a(self) -> None:
        self._select_bank(0)

    def action_filter_bank_b(self) -> None:
        self._select_bank(1)

    def action_filter_bank_c(self) -> None:
        self._select_bank(2)

    def action_filter_bank_d(self) -> None:
        self._select_bank(3)

    def action_filter_bank_e(self) -> None:
        self._select_bank(4)

    def action_filter_bank_f(self) -> None:
        self._select_bank(5)

    def action_filter_bank_g(self) -> None:
        self._select_bank(6)

    def action_filter_bank_h(self) -> None:
        self._select_bank(7)

    def action_filter_all_banks(self) -> None:
        self._select_bank(None)

    def _stage(self, operation: dict, message: str) -> None:
        try:
            self.session.stage(operation)
            self._refresh_table()
            self.app.notify(message)
        except Exception as exc:
            self.app.notify(str(exc), severity="error", timeout=8)

    def _clipboard(self) -> dict | None:
        value = getattr(self.clipboard_owner, "clipboard", None)
        return value if value and value.get("kind") == "pattern" else None

    def _set_clipboard(self, value: dict | None) -> None:
        if self.clipboard_owner is not None:
            self.clipboard_owner.clipboard = value

    def action_yank_pattern(self) -> None:
        self._set_clipboard({
            "kind": "pattern",
            "session": self.session,
            "slot": self.selected_pattern,
            "mode": "copy",
        })
        self._refresh_table()
        self.app.notify(f"Copied {pattern_label(self.selected_pattern)} to the pattern clipboard")

    def action_cut_pattern_to_clipboard(self) -> None:
        self._set_clipboard({
            "kind": "pattern",
            "session": self.session,
            "slot": self.selected_pattern,
            "mode": "cut",
        })
        self._refresh_table()
        self.app.notify(
            f"Marked {pattern_label(self.selected_pattern)} to move; choose a destination and press p"
        )

    def action_paste_pattern(self) -> None:
        clipboard = self._clipboard()
        if clipboard is None:
            self.app.notify("Pattern clipboard is empty", severity="warning")
            return
        source_session = clipboard["session"]
        source = clipboard["slot"]
        destination = self.selected_pattern
        is_cut = clipboard["mode"] == "cut"
        if source_session is self.session and source == destination:
            self.app.notify("Choose a different destination pattern", severity="warning")
            return
        try:
            if source_session is self.session:
                operation_type = "pattern_move" if is_cut else "pattern_copy"
                self.session.stage({"type": operation_type, "src_idx": source, "dst_idx": destination})
            else:
                source_raw = source_session.working_raw()
                source_members = source_session.working_members()
                source_manifest = json.loads(
                    next(data for info, data in source_members if info.filename == "manifest.json")
                )
                source_cut_staged = False
                if is_cut:
                    source_session.stage_pattern_bundle_cut(source)
                    source_cut_staged = True
                try:
                    self.session.stage_pattern_import(
                        source_session.path,
                        [{"src_idx": source, "dst_idx": destination}],
                        source_raw=source_raw,
                        source_manifest=source_manifest,
                        source_members=source_members,
                    )
                except Exception:
                    if source_cut_staged:
                        source_session.undo()
                    raise
        except Exception as exc:
            self.app.notify(f"Could not paste pattern: {exc}", severity="error", timeout=8)
            return
        self.selected_pattern = destination
        if is_cut:
            self._set_clipboard(None)
            if source_session is not self.session and self.clipboard_owner is not None:
                self.clipboard_owner._refresh_tab_labels()
        self._refresh_table()
        verb = "Moved" if is_cut else "Pasted"
        message = f"{verb} {pattern_label(source)} to {pattern_label(destination)} in the draft"
        if is_cut and source_session is not self.session:
            message += "; both projects are staged, press s in each project to save"
        else:
            message += "; press s to save"
        self.app.notify(message)

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
            f"Copied {pattern_label(source)} to {pattern_label(destination)} in the draft; press s to save",
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
            f"Moved {pattern_label(source)} to {pattern_label(destination)} in the draft; press s to save",
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
            f"Cleared {pattern_label(slot)} in the draft; press s to save",
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
            f"Renamed {pattern_label(self.selected_pattern)} in the draft; press s to save",
        )

    def action_import_pattern(self) -> None:
        source_sessions = [item for item in self.sessions if item.path != self.session.path]
        sources = "\n".join(
            f"{index + 1}: {item.path.name} ({item.device}, "
            f"{'DRAFT ' + str(len(item.operations)) if item.operations else 'CLEAN'})"
            for index, item in enumerate(source_sessions)
        )
        prompt = "Enter a source tab number or project path."
        if sources:
            prompt += "\nOpen project tabs:\n" + sources
        self.app.push_screen(
            PatternEntryModal("Import pattern", prompt, "tab number or project path"),
            lambda value: self._on_import_source(value, source_sessions),
        )

    def _on_import_source(self, value: str | None, source_sessions: list) -> None:
        if value is None or not value.strip():
            return
        source_input = value.strip()
        source_session = None
        if source_input.isdigit() and 1 <= int(source_input) <= len(source_sessions):
            source_session = source_sessions[int(source_input) - 1]
            source_path = source_session.path
        else:
            from pathlib import Path
            source_path = Path(source_input).expanduser().resolve()
            source_session = next(
                (item for item in self.sessions if item.path == source_path),
                None,
            )
        self.app.push_screen(
            PatternEntryModal("Source pattern", "Enter the source slot (A01–H16 or 0–127).", "e.g. A01"),
            lambda slot: self._on_import_slot(source_path, source_session, slot),
        )

    def _on_import_slot(self, source_path, source_session, value: str | None) -> None:
        if value is None:
            return
        try:
            source_slot = self._parse_slot(value)
        except ValueError:
            self.app.notify("Use A01–H16 or a slot number from 0 to 127", severity="error")
            return
        destination = self.selected_pattern
        try:
            source_raw = source_session.working_raw() if source_session is not None else None
            self.session.stage_pattern_import(
                source_path,
                [{"src_idx": source_slot, "dst_idx": destination}],
                source_raw=source_raw,
            )
            self._refresh_table()
            self.app.notify(
                f"Imported {pattern_label(source_slot)} to {pattern_label(destination)} in the draft; press s to save"
            )
        except Exception as exc:
            self.app.notify(str(exc), severity="error", timeout=10)

    def action_close(self) -> None:
        self.dismiss()


__all__ = ["PatternManagerScreen"]
