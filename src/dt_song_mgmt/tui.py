"""Read-only Textual project browser (first TUI slice)."""

from __future__ import annotations

from pathlib import Path

from textual.app import App, ComposeResult
from textual.containers import Horizontal, Vertical
from textual.widgets import DataTable, Footer, Static

from .session import ProjectSession
from .songs import (
    format_bpm,
    format_length,
    collect_pattern_names,
    pattern_label,
)


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
    ]

    def __init__(self, project_path: Path | str) -> None:
        super().__init__()
        self.project_path = Path(project_path).expanduser().resolve()
        self.project_title = self.project_path.name
        self.device = "Unknown device"
        self.songs: list[dict] = []
        self.pattern_names: list[str] = []
        self.session: ProjectSession | None = None

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

        self.query_one("#project-banner", Static).update(
            f"{self.project_path.name}  ·  {self.project_title}  ·  {self.device}  ·  CLEAN"
        )
        songs_table = self.query_one("#songs-table", DataTable)
        songs_table.add_columns("Slot", "Song", "Rows")
        for song in self.songs:
            songs_table.add_row(
                f"{song['slot']:02d}",
                song["name"],
                str(song["row_count"]),
                key=str(song["slot"]),
            )

        rows_table = self.query_one("#rows-table", DataTable)
        rows_table.add_columns("#", "Pattern", "Label", "Rep", "BPM", "Length", "Muted tracks")
        if self.songs:
            self._show_song(0)
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
        if event.data_table.id != "songs-table" or event.row_key is None:
            return
        try:
            slot = int(event.row_key.value)
        except (TypeError, ValueError):
            return
        self._show_song(slot)

    def _show_song(self, slot: int) -> None:
        rows_table = self.query_one("#rows-table", DataTable)
        rows_table.clear(columns=False)
        song = self.songs[slot]
        for index, row in enumerate(song["rows"], start=1):
            pattern_id = row["pattern"]
            pattern_name = row.get("pattern_name") or pattern_label(pattern_id)
            custom_name = self.pattern_names[pattern_id] if 0 <= pattern_id < len(self.pattern_names) else ""
            if custom_name:
                pattern_name = f"{pattern_name} {custom_name}"
            muted = [f"T{track}" for track in range(1, 17) if row["mute"] & (1 << (track - 1))]
            rows_table.add_row(
                str(index),
                pattern_name,
                row["label"] or "—",
                f"×{row['repeat']}",
                format_bpm(row["bpm_raw"]),
                format_length(row["length"]),
                ",".join(muted) if muted else "—",
            )
        self.query_one("#rows-pane .pane-title", Static).update(
            f"SONG {slot:02d}  ·  {song['name']}  ·  {song['row_count']} ROWS"
        )


def run_tui(project_path: Path | str) -> None:
    """Start the terminal project browser for ``project_path``."""
    ProjectBrowser(project_path).run()
