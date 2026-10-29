"""Digitakt II sample memory report for the Textual interface."""

from __future__ import annotations

from textual.app import ComposeResult
from textual.containers import Vertical
from textual.screen import ModalScreen
from textual.widgets import DataTable, Footer, Static

from .sample_memory import analyze_sample_memory, format_bytes
from .songs import pattern_label


class SampleMemoryScreen(ModalScreen[None]):
    """Show project sample totals and per-pattern sample references."""

    CSS = """
    SampleMemoryScreen { align: center middle; background: $background 60%; }
    #memory-window { width: 96%; height: 94%; border: round $primary; background: $surface; padding: 1 2; }
    #memory-heading { height: 2; color: $text; text-style: bold; }
    #memory-note { height: 2; color: $text-muted; }
    #memory-columns { height: 1fr; layout: horizontal; }
    #memory-patterns { width: 2fr; }
    #memory-samples { width: 3fr; margin-left: 1; }
    DataTable:focus { border: tall $accent; }
    """

    BINDINGS = [("escape", "close", "Back"), ("q", "close", "Back")]

    def __init__(self, session):
        super().__init__()
        self.session = session
        self.selected_pattern = 0
        self.analysis = analyze_sample_memory(session.working_raw(), session.working_manifest())

    def compose(self) -> ComposeResult:
        total = self.analysis["project_sample_bytes"]
        referenced = self.analysis["referenced_sample_bytes"]
        with Vertical(id="memory-window"):
            yield Static(
                f"DIGITAKT II SAMPLE MEMORY · {format_bytes(total)} across "
                f"{self.analysis['project_sample_count']} project samples · "
                f"{format_bytes(referenced)} referenced by patterns",
                id="memory-heading",
            )
            yield Static(
                f"Pattern totals count unique samples within each pattern. "
                f"Shared samples: {self.analysis['shared_sample_count']} · "
                f"Unreferenced project samples: {self.analysis['unreferenced_sample_count']} "
                f"({format_bytes(self.analysis['unreferenced_sample_bytes'])}). "
                "Includes kit samples and sample locks. Pool-only assets may not be in this archive; sizes do not guarantee freed RAM.",
                id="memory-note",
            )
            with Vertical(id="memory-columns"):
                yield DataTable(id="memory-patterns", cursor_type="row", zebra_stripes=True)
                yield DataTable(id="memory-samples", cursor_type="row", zebra_stripes=True)
        yield Footer()

    def on_mount(self) -> None:
        patterns = self.query_one("#memory-patterns", DataTable)
        patterns.add_columns("Pattern", "Samples", "Referenced", "Pattern-only")
        ranked = sorted(self.analysis["patterns"], key=lambda item: (-item["referenced_bytes"], item["index"]))
        for entry in ranked:
            patterns.add_row(
                pattern_label(entry["index"]),
                str(entry["sample_count"]),
                format_bytes(entry["referenced_bytes"]),
                format_bytes(entry["exclusive_bytes"]),
                key=str(entry["index"]),
            )
        samples = self.query_one("#memory-samples", DataTable)
        samples.add_columns("Sample", "Tracks", "Patterns", "Size", "Use")
        patterns.focus()
        if ranked:
            self.selected_pattern = ranked[0]["index"]
            self._refresh_samples()

    def on_data_table_row_highlighted(self, event: DataTable.RowHighlighted) -> None:
        if event.data_table.id != "memory-patterns" or event.row_key is None:
            return
        try:
            self.selected_pattern = int(event.row_key.value)
            self._refresh_samples()
        except (TypeError, ValueError):
            return

    def _refresh_samples(self) -> None:
        table = self.query_one("#memory-samples", DataTable)
        table.clear(columns=False)
        entry = self.analysis["patterns"][self.selected_pattern]
        for sample in entry["samples"]:
            track_text = ",".join(f"{track + 1:02}" for track in sample["tracks"])
            table.add_row(
                sample["name"],
                track_text,
                str(sample["pattern_count"]),
                format_bytes(sample["size"]),
                ("shared" if sample["shared"] else "unique") + (" · locked" if sample.get("sample_locked") else ""),
            )
        if not entry["samples"]:
            table.add_row("No samples referenced by this pattern", "", "", "", "")

    def action_close(self) -> None:
        self.dismiss(None)


__all__ = ["SampleMemoryScreen"]
