"""Read-only song-to-pattern overview for the Textual interface."""

from __future__ import annotations

from collections import Counter

from textual.app import ComposeResult
from textual.containers import Horizontal, Vertical
from textual.screen import ModalScreen
from textual.widgets import DataTable, Footer, Static

from .constants import PATTERN_SLOTS
from .songs import collect_pattern_names, get_all_songs_info, pattern_label


class SongPatternOverviewScreen(ModalScreen[None]):
    """List each song's distinct patterns and their row usage counts."""

    CSS = """
    SongPatternOverviewScreen { align: center middle; background: $background 60%; }
    #song-pattern-window { width: 96%; height: 92%; border: round $primary; background: $surface; padding: 1 2; }
    #song-pattern-heading { height: 1; color: $text; text-style: bold; }
    #song-pattern-columns { height: 1fr; layout: horizontal; margin-top: 1; }
    #overview-songs { width: 1fr; }
    #overview-patterns { width: 1fr; margin-left: 1; }
    DataTable:focus { border: tall $accent; }
    """

    BINDINGS = [("escape", "close", "Back"), ("q", "close", "Back")]

    def __init__(self, session):
        super().__init__()
        self.session = session
        raw = session.working_raw()
        self.songs = get_all_songs_info(raw)
        self.pattern_names = collect_pattern_names(raw)
        self.selected_song = 0

    def compose(self) -> ComposeResult:
        with Vertical(id="song-pattern-window"):
            yield Static("SONG PATTERN OVERVIEW · SELECT A SONG TO SEE ITS PATTERNS", id="song-pattern-heading")
            with Horizontal(id="song-pattern-columns"):
                yield DataTable(id="overview-songs", cursor_type="row", zebra_stripes=True)
                yield DataTable(id="overview-patterns", cursor_type="row", zebra_stripes=True)
        yield Footer()

    def on_mount(self) -> None:
        songs_table = self.query_one("#overview-songs", DataTable)
        songs_table.add_columns("Slot", "Song", "Rows", "Patterns")
        for song in self.songs:
            distinct = {row["pattern"] for row in song["rows"] if 0 <= row["pattern"] < PATTERN_SLOTS}
            songs_table.add_row(
                f"{song['slot']:02d}", song["name"], str(song["row_count"]), str(len(distinct)),
                key=str(song["slot"]),
            )
        patterns_table = self.query_one("#overview-patterns", DataTable)
        patterns_table.add_columns("Pattern", "Pattern name", "Song rows")
        songs_table.focus()
        if self.songs:
            self._show_song_patterns(self.selected_song)

    def on_data_table_row_highlighted(self, event: DataTable.RowHighlighted) -> None:
        if event.data_table.id != "overview-songs" or event.row_key is None:
            return
        try:
            self.selected_song = int(event.row_key.value)
            self._show_song_patterns(self.selected_song)
        except (TypeError, ValueError):
            return

    def _show_song_patterns(self, song_slot: int) -> None:
        table = self.query_one("#overview-patterns", DataTable)
        table.clear(columns=False)
        song = self.songs[song_slot]
        counts = Counter(
            row["pattern"] for row in song["rows"]
            if 0 <= row["pattern"] < PATTERN_SLOTS
        )
        for index, count in sorted(counts.items()):
            name = self.pattern_names[index].strip() or "(unnamed)"
            table.add_row(pattern_label(index), name, str(count), key=str(index))
        if not counts:
            table.add_row("—", "No patterns in this song", "0")

    def action_close(self) -> None:
        self.dismiss(None)


__all__ = ["SongPatternOverviewScreen"]
