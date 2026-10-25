"""Compatibility shim for dt_song_mgmt."""

from __future__ import annotations

import sys
from pathlib import Path

# Ensure package imports work when run as a script
if __package__ is None or __package__ == "":
    pkg_dir = Path(__file__).parent
    parent_dir = pkg_dir.parent
    if str(parent_dir) not in sys.path:
        sys.path.insert(0, str(parent_dir))
    from dt_song_mgmt import *
    from dt_song_mgmt.cli import main
else:
    from . import *
    from .cli import main


if __name__ == "__main__":
    main(sys.argv[1:])
