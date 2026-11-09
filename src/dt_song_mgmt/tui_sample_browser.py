"""Browse samples referenced by an open Digitakt II project."""

from pathlib import PurePosixPath

from rich.text import Text
from textual.app import ComposeResult
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.screen import ModalScreen
from textual.widgets import Static, Tree

from .sample_memory import analyze_sample_memory, format_bytes
from .songs import pattern_label


class SampleBrowserScreen(ModalScreen[None]):
    """Show sample paths, archive presence, and pattern usage."""

    CSS = """
    SampleBrowserScreen { background: $background; }
    #sample-browser { height: 100%; padding: 0 2; }
    #sample-browser-title { height: 2; text-style: bold; }
    #sample-browser-columns { height: 1fr; }
    #sample-tree { width: 1fr; border-right: solid $panel; }
    #sample-details-scroll { width: 1fr; padding: 0 1; }
    #sample-details { height: auto; }
    #sample-browser-hint { height: 2; color: $text-muted; }
    """
    BINDINGS = [("escape", "close", "Back"), ("q", "close", "Back")]

    def __init__(self, session):
        super().__init__()
        self.analysis = analyze_sample_memory(session.working_raw(), session.working_manifest())
        self.members = {info.filename for info, _ in session.working_members()}

    def compose(self) -> ComposeResult:
        with Vertical(id="sample-browser"):
            yield Static(
                f"DIGITAKT II  /  PROJECT SAMPLES  ·  {self.analysis['pattern_error_count']} unresolved patterns",
                id="sample-browser-title",
            )
            with Horizontal(id="sample-browser-columns"):
                yield Tree("Samples", id="sample-tree")
                with VerticalScroll(id="sample-details-scroll"):
                    yield Static("Select a sample to see its details.", id="sample-details")
            yield Static(
                "↑/↓ browse · Enter expand/collapse · Esc back · Sample sizes are reference sizes",
                id="sample-browser-hint",
            )

    def on_mount(self) -> None:
        tree = self.query_one("#sample-tree", Tree)
        folders = {(): tree.root}
        for sample_hash, sample in sorted(
            self.analysis["samples"].items(),
            key=lambda item: (item[1].get("path") or "~pool/" + item[1]["name"]).casefold(),
        ):
            path = sample.get("path")
            parts = list(PurePosixPath(path).parts) if path else ["References (path unavailable)", sample["name"]]
            if parts and parts[0] == "Samples":
                parts.pop(0)
            if not parts:
                parts = [sample["name"]]
            for index in range(1, len(parts)):
                key = tuple(parts[:index])
                if key not in folders:
                    folders[key] = folders[key[:-1]].add(parts[index - 1])
            label = Text(parts[-1])
            size = format_bytes(sample["size"]) if sample.get("size_known", True) else "unknown size"
            label.append(f"  {size}", style="dim")
            folders[tuple(parts[:-1])].add_leaf(label, data=sample_hash)
        tree.root.expand()
        tree.focus()

    def on_tree_node_highlighted(self, event: Tree.NodeHighlighted) -> None:
        sample_hash = event.node.data
        if sample_hash is None or sample_hash not in self.analysis["samples"]:
            self.query_one("#sample-details", Static).update("Select a sample to see its details.")
            return
        sample = self.analysis["samples"][sample_hash]
        path = sample.get("path")
        status = "WAV included in project" if path and path in self.members else (
            "WAV missing from archive" if path else "Reference only; WAV not in archive"
        )
        details = Text()
        details.append(sample["name"] + "\n\n", style="bold")
        details.append(f"Path: {path or 'unknown'}\nHash: {sample_hash:08X}\n")
        size = format_bytes(sample["size"]) if sample.get("size_known", True) else "unknown"
        details.append(f"Reference size: {size}\nAudio: {status}\n\n")
        details.append("Assigned to tracks (including empty pattern slots)\n", style="bold")
        uses = []
        for pattern in self.analysis["patterns"]:
            for item in pattern["samples"]:
                if item["hash"] == sample_hash:
                    tracks = ", ".join(f"T{track + 1}" for track in item["tracks"])
                    uses.append(f"{pattern_label(pattern['index'])}  {tracks}" + ("  sample lock" if item["sample_locked"] else ""))
        details.append("\n".join(uses) if uses else "No resolved pattern references")
        if self.analysis["pattern_error_count"]:
            details.append(f"\n\n{self.analysis['pattern_error_count']} pattern(s) could not be analyzed; usage may be incomplete.")
        self.query_one("#sample-details", Static).update(details)

    def action_close(self) -> None:
        self.dismiss(None)
