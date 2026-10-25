"""Web routes."""

import json
from http.server import BaseHTTPRequestHandler
from pathlib import Path
from urllib.parse import urlparse
import shutil

from ..patterns import get_all_patterns_info, rename_pattern, copy_pattern_block, clear_pattern, swap_patterns, move_pattern, retarget_all_pattern_refs
from ..project import pack_project, read_project, unpack_project
from ..songs import get_song_slots, get_song_info, collect_pattern_names
from ..state import apply_operations, get_project_state


class Handler(BaseHTTPRequestHandler):
    def _send_json(self, obj, code=200):
        data = json.dumps(obj).encode()
        self.send_response(code)
        self.send_header('Content-Type', 'application/json')
        self.send_header('Access-Control-Allow-Origin', '*')
        self.end_headers()
        self.wfile.write(data)

    def _send_html(self, html):
        self.send_response(200)
        self.send_header('Content-Type', 'text/html; charset=utf-8')
        self.end_headers()
        self.wfile.write(html.encode())
