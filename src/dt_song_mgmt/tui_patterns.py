"""Pattern manager screen for the Textual terminal interface."""

from __future__ import annotations

import json

from rich.text import Text
from textual.app import ComposeResult
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.screen import ModalScreen
from textual.widgets import Button, Input, Label, Static

from .patterns import get_all_patterns_info
from .songs import pattern_label


class PatternEntryModal(ModalScreen[str | None]):
    """Prompt for a pattern slot, name, or source project path."""

    CSS = """
    PatternEntryModal { align: center middle; background: #000000 70%; }
    #pattern-entry-dialog { width: 68; height: auto; padding: 1 2; border: solid #c18a3c; background: #111111; }
    #pattern-entry-dialog Input { margin: 1 0; }
    #pattern-entry-buttons { height: 3; align-horizontal: right; }
    #pattern-entry-buttons Button { margin-left: 1; border: none; background: #222222; color: #dedbd2; }
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


class PatternConfirmModal(ModalScreen[bool]):
    """Confirm clearing a pattern and its corresponding sound kit."""

    CSS = """
    PatternConfirmModal { align: center middle; background: #000000 70%; }
    #pattern-confirm-dialog { width: 76; height: auto; padding: 1 2; border: solid #c18a3c; background: #111111; }
    #pattern-confirm-buttons { height: 3; align-horizontal: right; }
    #pattern-confirm-buttons Button { margin-left: 1; border: none; background: #222222; color: #dedbd2; }
    """
    BINDINGS = [("escape", "cancel", "Cancel")]

    def __init__(self, message: str):
        super().__init__()
        self.message = message

    def compose(self) -> ComposeResult:
        with Vertical(id="pattern-confirm-dialog"):
            yield Label("Clear pattern?")
            yield Static(self.message)
            with Horizontal(id="pattern-confirm-buttons"):
                yield Button("Cancel", id="cancel")
                yield Button("Clear pattern and kit", id="confirm", variant="error")

    def on_mount(self) -> None:
        self.query_one("#cancel", Button).focus()

    def on_button_pressed(self, event: Button.Pressed) -> None:
        self.dismiss(event.button.id == "confirm")

    def action_cancel(self) -> None:
        self.dismiss(False)


class PatternList(Static):
    """Focusable, text-rendered pattern list with no table widget chrome."""

    can_focus = True
    BINDINGS = [
        ("up", "move(-1)", "Previous pattern"),
        ("down", "move(1)", "Next pattern"),
        ("pageup", "move(-12)", "Page up"),
        ("pagedown", "move(12)", "Page down"),
        ("home", "first", "First pattern"),
        ("end", "last", "Last pattern"),
    ]

    def action_move(self, delta: int) -> None:
        self.screen._move_selection(delta)

    def action_first(self) -> None:
        self.screen.action_select_first_pattern()

    def action_last(self) -> None:
        self.screen.action_select_last_pattern()


class PatternManagerScreen(ModalScreen[None]):
    """Search and stage operations on the 128 pattern slots."""

    CSS = """
    PatternManagerScreen { align: left top; background: $background; color: $text; }
    #pattern-workspace { width: 100%; height: 100%; padding: 0 1; }
    #pattern-topline { height: 2; }
    #pattern-heading { width: 1fr; text-style: bold; }
    #pattern-project { width: auto; }
    #pattern-content { height: 1fr; }
    #pattern-bank-pane { width: 14; padding-right: 1; }
    #pattern-bank-title { height: 1; text-style: bold; }
    #pattern-banks { height: auto; }
    #pattern-results { width: 1fr; padding-left: 1; }
    #pattern-count { height: 1; }
    #pattern-search { height: 3; margin: 1 0; }
    #pattern-columns { height: 1; }
    #pattern-scroll { height: 1fr; }
    #pattern-list { height: auto; min-height: 1; }
    #pattern-selection { height: 5; }
    #pattern-help { height: 2; }
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
        ("up", "select_previous_pattern", "Previous pattern"),
        ("down", "select_next_pattern", "Next pattern"),
        ("pageup", "page_up_patterns", "Page up"),
        ("pagedown", "page_down_patterns", "Page down"),
        ("home", "select_first_pattern", "First pattern"),
        ("end", "select_last_pattern", "Last pattern"),
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
        self._visible_patterns: list[dict] = []

    def compose(self) -> ComposeResult:
        with Vertical(id="pattern-workspace"):
            with Horizontal(id="pattern-topline"):
                yield Static("PATTERNS", id="pattern-heading")
                yield Static("", id="pattern-project")
            with Horizontal(id="pattern-content"):
                with Vertical(id="pattern-bank-pane"):
                    yield Static("BANK", id="pattern-bank-title")
                    yield Static("", id="pattern-banks")
                with Vertical(id="pattern-results"):
                    yield Static("", id="pattern-count")
                    yield Input(placeholder="/ to filter slots or names", id="pattern-search")
                    yield Static("    SLOT  SONG   PATTERN NAME", id="pattern-columns")
                    with VerticalScroll(id="pattern-scroll"):
                        yield PatternList("", id="pattern-list")
            yield Static("", id="pattern-selection")
            yield Static(
                "↑/↓ browse · PgUp/PgDn jump · Home/End · 1–8 banks · 0 all · / filter · Enter return\n"
                "c copy · m move · d clear · r rename · i import · y copy · x cut · p paste · Esc back",
                id="pattern-help",
            )

    def on_mount(self) -> None:
        pattern_list = self.query_one("#pattern-list", PatternList)
        self._refresh_view()
        pattern_list.focus()

    def on_input_changed(self, event: Input.Changed) -> None:
        if event.input.id == "pattern-search":
            self.filter_text = event.value.strip().casefold()
            self._refresh_view()

    def on_input_submitted(self, event: Input.Submitted) -> None:
        if event.input.id == "pattern-search":
            self.query_one("#pattern-list", PatternList).focus()

    def _refresh_view(self) -> None:
        all_patterns = get_all_patterns_info(self.session.working_raw())
        patterns = all_patterns
        if self.bank_filter is not None:
            patterns = [pattern for pattern in patterns if pattern["index"] // 16 == self.bank_filter]
        if self.filter_text:
            patterns = [
                pattern for pattern in patterns
                if self.filter_text in pattern["label"].casefold()
                or self.filter_text in pattern["name"].casefold()
            ]
        self._visible_patterns = patterns
        bank_label = "ALL BANKS" if self.bank_filter is None else f"BANK {chr(ord('A') + self.bank_filter)}"
        clipboard = self._clipboard()
        draft_status = f"DRAFT {len(self.session.operations)}" if self.session.operations else "CLEAN"
        project_name = self.session.display_name if self.session.is_new_project else self.session.path.name
        project_line = f"{self.session.device} / {project_name}"
        if clipboard:
            action = "CUT" if clipboard["mode"] == "cut" else "COPY"
            project_line += f" · {action} {pattern_label(clipboard['slot'])} ready"
        self.query_one("#pattern-heading", Static).update("PATTERNS")
        self.query_one("#pattern-project", Static).update(f"{project_line}  ·  {draft_status}")
        bank_text = Text()
        bank_text.append("\n")
        for bank in range(8):
            name = chr(ord("A") + bank)
            marker = ">" if self.bank_filter == bank else " "
            bank_text.append(f"{marker} {name}    {bank + 1}\n", style="reverse bold" if marker == ">" else None)
        all_marker = ">" if self.bank_filter is None else " "
        bank_text.append(f"{all_marker} ALL    0", style="reverse bold" if all_marker == ">" else None)
        self.query_one("#pattern-banks", Static).update(bank_text)
        named_count = sum(bool(pattern["name"].strip()) for pattern in all_patterns)
        self.query_one("#pattern-count", Static).update(
            f"{bank_label}  ·  {len(patterns)} slots  ·  {named_count}/128 named"
        )
        visible_indices = [pattern["index"] for pattern in patterns]
        if visible_indices and self.selected_pattern not in visible_indices:
            self.selected_pattern = visible_indices[0]
        selected_row = visible_indices.index(self.selected_pattern) if visible_indices else 0
        content = Text()
        for pattern in patterns:
            name = pattern["name"].strip() or "(unnamed)"
            marker = ">" if pattern["index"] == self.selected_pattern else " "
            usage = f"{pattern['ref_count']}r" if pattern["ref_count"] else "–"
            line = f"{marker} {pattern['label']:<4}  {usage:<5}  {name}"
            content.append(line, style="reverse bold" if marker == ">" else None)
            content.append("\n")
        if not patterns:
            content.append("No slots match this filter. Press / and clear the search.")
        self.query_one("#pattern-list", PatternList).update(content)
        if patterns:
            self.query_one("#pattern-scroll", VerticalScroll).scroll_to(
                y=selected_row, animate=False, force=True
            )
        self._refresh_selection()

    def _refresh_selection(self) -> None:
        if not self.is_mounted:
            return
        pattern = next(
            (item for item in self._visible_patterns if item["index"] == self.selected_pattern),
            None,
        )
        if pattern is None:
            detail = "No pattern slots match this search. Clear the search field to show slots again."
        else:
            name = pattern["name"].strip() or "(unnamed)"
            refs = pattern["ref_count"]
            usage = f"USED by {refs} song row(s)" if refs else "UNUSED by songs"
            detail = f"{pattern['label']}   {name}   ·   {usage}\n{self._reference_summary(pattern)}"
        self.query_one("#pattern-selection", Static).update(detail)

    def _pattern_info(self, slot: int, session=None) -> dict:
        session = session or self.session
        return get_all_patterns_info(session.working_raw())[slot]

    @staticmethod
    def _reference_summary(pattern: dict, max_songs: int = 3) -> str:
        grouped: dict[tuple[int, str], list[int]] = {}
        for reference in pattern.get("references", []):
            key = (reference["song_slot"], reference["song_name"])
            grouped.setdefault(key, []).append(reference["row"])
        if not grouped:
            return "No song rows reference this pattern."
        parts = []
        entries = list(grouped.items())
        for (slot, name), rows in entries[:max_songs]:
            song_name = "(unnamed)" if name == "EMPTY" else name
            row_list = ", ".join(f"{row:02d}" for row in rows[:3])
            if len(rows) > 3:
                row_list += f" +{len(rows) - 3} rows"
            prefix = "Used by: " if not parts else "         "
            parts.append(f"{prefix}Song {slot + 1:02d} {song_name} · rows {row_list}")
        if len(entries) > max_songs:
            parts.append(f"         +{len(entries) - max_songs} more songs")
        return "\n".join(parts)

    def action_focus_filter(self) -> None:
        self.query_one("#pattern-search", Input).focus()

    def _move_selection(self, delta: int) -> None:
        if not self._visible_patterns:
            return
        indices = [pattern["index"] for pattern in self._visible_patterns]
        current = indices.index(self.selected_pattern) if self.selected_pattern in indices else 0
        self.selected_pattern = indices[max(0, min(len(indices) - 1, current + delta))]
        self._refresh_view()

    def action_select_previous_pattern(self) -> None:
        self._move_selection(-1)

    def action_select_next_pattern(self) -> None:
        self._move_selection(1)

    def action_page_up_patterns(self) -> None:
        self._move_selection(-12)

    def action_page_down_patterns(self) -> None:
        self._move_selection(12)

    def action_select_first_pattern(self) -> None:
        if self._visible_patterns:
            self.selected_pattern = self._visible_patterns[0]["index"]
            self._refresh_view()

    def action_select_last_pattern(self) -> None:
        if self._visible_patterns:
            self.selected_pattern = self._visible_patterns[-1]["index"]
            self._refresh_view()

    def _select_bank(self, bank: int | None) -> None:
        self.bank_filter = bank
        self._refresh_view()

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
            self._refresh_view()
            self.app.notify(message)
        except Exception as exc:
            self.app.notify(str(exc), severity="error", timeout=8)

    def _clipboard(self) -> dict | None:
        value = getattr(self.clipboard_owner, "_dsm_clipboard", None)
        return value if value and value.get("kind") == "pattern" else None

    def _set_clipboard(self, value: dict | None) -> None:
        if self.clipboard_owner is not None:
            self.clipboard_owner._dsm_clipboard = value

    def action_yank_pattern(self) -> None:
        info = self._pattern_info(self.selected_pattern)
        self._set_clipboard({
            "kind": "pattern",
            "session": self.session,
            "slot": self.selected_pattern,
            "mode": "copy",
        })
        self._refresh_view()
        message = f"Copied {pattern_label(self.selected_pattern)} to the pattern clipboard"
        if info["ref_count"]:
            message += f" · {self._reference_summary(info)}"
        self.app.notify(message, timeout=8)

    def action_cut_pattern_to_clipboard(self) -> None:
        info = self._pattern_info(self.selected_pattern)
        self._set_clipboard({
            "kind": "pattern",
            "session": self.session,
            "slot": self.selected_pattern,
            "mode": "cut",
        })
        self._refresh_view()
        message = f"Marked {pattern_label(self.selected_pattern)} to move; choose a destination and press p"
        if info["ref_count"]:
            message += f" · {self._reference_summary(info)}; same-project moves retarget these rows"
        self.app.notify(message, timeout=8)

    def action_paste_pattern(self) -> None:
        clipboard = self._clipboard()
        if clipboard is None:
            self.app.notify("Pattern clipboard is empty", severity="warning")
            return
        source_session = clipboard["session"]
        source = clipboard["slot"]
        destination = self.selected_pattern
        is_cut = clipboard["mode"] == "cut"
        source_info = self._pattern_info(source, source_session)
        destination_info = self._pattern_info(destination)
        if source_session is self.session and source == destination:
            self.app.notify("Choose a different destination pattern", severity="warning")
            return
        if is_cut and source_session is not self.session and source_info["ref_count"]:
            self.app.notify(
                f"Cannot move {pattern_label(source)} across projects while songs reference it. "
                f"{self._reference_summary(source_info)}",
                severity="error",
                timeout=10,
            )
            return
        try:
            if source_session is self.session:
                if is_cut:
                    self.session.stage_pattern_move(source, destination)
                else:
                    self.session.stage({"type": "pattern_copy", "src_idx": source, "dst_idx": destination})
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
        self._refresh_view()
        verb = "Moved" if is_cut else "Pasted"
        message = f"{verb} {pattern_label(source)} to {pattern_label(destination)} in the draft"
        if is_cut and source_session is not self.session:
            message += "; both projects are staged, press s in each project to save"
        else:
            message += "; press s to save"
        context = []
        if is_cut and source_info["ref_count"]:
            context.append(f"song rows retargeted from {pattern_label(source)}: {self._reference_summary(source_info)}")
        elif source_info["ref_count"]:
            context.append(f"source remains used: {self._reference_summary(source_info)}")
        if destination_info["ref_count"]:
            context.append(f"destination users now play the pasted pattern: {self._reference_summary(destination_info)}")
        if source_session is not self.session and self.session.device == "DT2":
            context.append("Available WAVs staged; factory sounds may use device references")
        if context:
            message += " · " + " · ".join(context)
        self.app.notify(message, timeout=10)

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
        source_info = self._pattern_info(source)
        destination_info = self._pattern_info(destination)
        message = f"Copied {pattern_label(source)} to {pattern_label(destination)} in the draft; press s to save"
        if source_info["ref_count"]:
            message += f" · source remains used: {self._reference_summary(source_info)}"
        if destination_info["ref_count"]:
            message += f" · destination users now play the copied pattern: {self._reference_summary(destination_info)}"
        self._stage(
            {"type": "pattern_copy", "src_idx": source, "dst_idx": destination},
            message,
        )
        self.selected_pattern = destination
        self._refresh_view()

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
        source_info = self._pattern_info(source)
        destination_info = self._pattern_info(destination)
        message = f"Moved {pattern_label(source)} to {pattern_label(destination)} in the draft; press s to save"
        if source_info["ref_count"]:
            message += f" · song rows retargeted: {self._reference_summary(source_info)}"
        if destination_info["ref_count"]:
            message += f" · existing destination users now play the moved pattern: {self._reference_summary(destination_info)}"
        if not self._stage_move(source, destination, message):
            return
        self.selected_pattern = destination
        self._refresh_view()

    def _stage_move(self, source: int, destination: int, message: str) -> bool:
        try:
            self.session.stage_pattern_move(source, destination)
            self._refresh_view()
            self.app.notify(message, timeout=10)
            return True
        except Exception as exc:
            self.app.notify(f"Could not move pattern: {exc}", severity="error", timeout=10)
            return False

    def action_copy_pattern(self) -> None:
        self._prompt_slot("Copy pattern", self._on_copy_destination)

    def action_move_pattern(self) -> None:
        self._prompt_slot("Move pattern", self._on_move_destination)

    def action_clear_pattern(self) -> None:
        slot = self.selected_pattern
        info = self._pattern_info(slot)
        if info["ref_count"]:
            message = (
                f"{self._reference_summary(info)}. Clearing this pattern and its sound kit leaves those "
                "song rows pointing at an empty pattern slot."
            )
        else:
            message = "No song rows use this pattern. This clears its pattern data and associated sound kit."
        self.app.push_screen(
            PatternConfirmModal(message),
            lambda confirmed: self._on_clear_confirmation(confirmed, slot, info),
        )

    def _on_clear_confirmation(self, confirmed: bool, slot: int, info: dict) -> None:
        if not confirmed:
            return
        message = f"Cleared {pattern_label(slot)} and its sound kit in the draft; press s to save"
        if info["ref_count"]:
            message += f" · rows still reference the now-empty slot: {self._reference_summary(info)}"
        self._stage({"type": "pattern_clear", "pat_idx": slot}, message)

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
            f"{index + 1}: {item.display_name if item.is_new_project else item.path.name} ({item.device}, "
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
            destination_info = self._pattern_info(destination)
            source_info = self._pattern_info(source_slot, source_session) if source_session else None
            self.session.stage_pattern_import(
                source_path,
                [{"src_idx": source_slot, "dst_idx": destination}],
                source_raw=source_raw,
            )
            self._refresh_view()
            message = f"Imported {pattern_label(source_slot)} to {pattern_label(destination)} in the draft; press s to save"
            if source_info and source_info["ref_count"]:
                message += f" · source remains used: {self._reference_summary(source_info)}"
            if destination_info["ref_count"]:
                message += f" · destination users now play the imported pattern: {self._reference_summary(destination_info)}"
            if self.session.device == "DT2":
                message += " · Available WAVs staged; factory sounds may use device references"
            self.app.notify(message, timeout=10)
        except Exception as exc:
            self.app.notify(str(exc), severity="error", timeout=10)

    def action_close(self) -> None:
        self.dismiss()


__all__ = ["PatternManagerScreen"]
