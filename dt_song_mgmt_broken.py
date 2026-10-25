"""Compatibility shim for dt_song_mgmt."""

from .constants import *
from .crc import *
from .lz4 import *
from .format import *
from .project import *
from .songs import *
from .patterns import *
from .state import *
from .cli import main
from .web.server import run_web_server

# Re-export functions that might be imported
from . import dump_songs, restore_songs, apply_song_edits, render_songs_html, sanitize, slot_index_from_name

if __name__ == "__main__":
    import sys
    main(sys.argv[1:])
