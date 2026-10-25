"""Web server."""

import webbrowser
from http.server import HTTPServer, BaseHTTPRequestHandler
from pathlib import Path
from urllib.parse import urlparse
import json
import shutil

from ..patterns import get_all_patterns_info, rename_pattern, copy_pattern_block, clear_pattern, swap_patterns, move_pattern, retarget_all_pattern_refs
from ..project import pack_project, read_project, unpack_project, payload_name
from ..songs import get_song_slots, get_song_info, collect_pattern_names, SONG_SLOTS
from ..state import apply_operations, get_project_state


def create_handler(prj: Path):
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

        def log_message(self, *args):
            pass

        def do_OPTIONS(self):
            self.send_response(200)
            self.send_header('Access-Control-Allow-Origin', '*')
            self.send_header('Access-Control-Allow-Methods', 'GET, POST, OPTIONS')
            self.send_header('Access-Control-Allow-Headers', 'Content-Type')
            self.end_headers()

        def do_GET(self):
            parsed = urlparse(self.path)
            if parsed.path in ['/', '/editor', '/index.html']:
                editor_path = Path(__file__).parent.parent / 'static' / 'editor.html'
                if not editor_path.exists():
                    editor_path = Path(__file__).parent.parent / 'editor.html'
                if editor_path.exists():
                    self._send_html(editor_path.read_text())
                else:
                    self._send_html('<h1>editor.html not found</h1>')
            elif parsed.path == '/api/state':
                try:
                    state = get_project_state(prj)
                    self._send_json(state)
                except Exception as e:
                    self._send_json({'error': str(e)}, 500)
            elif parsed.path == '/api/patterns':
                try:
                    manifest, payload, _ = read_project(prj)
                    _head, raw = unpack_project(payload)
                    patterns = get_all_patterns_info(raw)
                    self._send_json({'patterns': patterns})
                except Exception as e:
                    self._send_json({'error': str(e)}, 500)
            else:
                self.send_error(404)

        def do_POST(self):
            parsed = urlparse(self.path)
            content_length = int(self.headers.get('Content-Length', 0))
            body = self.rfile.read(content_length).decode()
            if parsed.path == '/api/preview':
                try:
                    data = json.loads(body)
                    ops = data.get('operations', [])
                    manifest, payload, members = read_project(prj)
                    head, raw = unpack_project(payload)
                    try:
                        new_raw = apply_operations(raw, ops)
                        pattern_names = collect_pattern_names(new_raw)
                        slots = get_song_slots(new_raw)
                        songs = []
                        for i in range(len(slots)):
                            info = get_song_info(slots[i], pattern_names)
                            info['slot'] = i
                            songs.append(info)
                        patterns = get_all_patterns_info(new_raw)
                        self._send_json({'ok': True, 'songs': songs, 'patterns': patterns})
                    except Exception as e:
                        self._send_json({'error': str(e)}, 500)
                except Exception as e:
                    self._send_json({'error': str(e)}, 500)
            elif parsed.path == '/api/apply':
                try:
                    data = json.loads(body)
                    ops = data.get('operations', [])
                    manifest, payload, members = read_project(prj)
                    pname = payload_name(manifest)
                    head, raw = unpack_project(payload)
                    new_raw = apply_operations(raw, ops)
                    new_payload = pack_project(head, new_raw)
                    bak = prj.with_suffix(prj.suffix + ".bak")
                    shutil.copy2(prj, bak)
                    from ..project import write_project
                    write_project(prj, members, pname, new_payload)
                    state = get_project_state(prj)
                    self._send_json({'ok': True, 'backup': str(bak), 'state': state})
                except Exception as e:
                    self._send_json({'error': str(e)}, 500)
            elif parsed.path == '/api/patterns/rename':
                try:
                    data = json.loads(body)
                    pat_idx = int(data['pat_idx'])
                    name = data['name']
                    manifest, payload, members = read_project(prj)
                    pname = payload_name(manifest)
                    head, raw = unpack_project(payload)
                    new_raw = rename_pattern(raw, pat_idx, name)
                    new_payload = pack_project(head, new_raw)
                    bak = prj.with_suffix(prj.suffix + ".bak")
                    shutil.copy2(prj, bak)
                    from ..project import write_project
                    write_project(prj, members, pname, new_payload)
                    self._send_json({'success': True, 'backup': str(bak)})
                except Exception as e:
                    self._send_json({'error': str(e)}, 500)
            elif parsed.path == '/api/patterns/move':
                try:
                    data = json.loads(body)
                    src_idx = int(data['src_idx'])
                    dst_idx = int(data['dst_idx'])
                    also_retarget = data.get('also_retarget', True)
                    manifest, payload, members = read_project(prj)
                    pname = payload_name(manifest)
                    head, raw = unpack_project(payload)
                    new_raw = move_pattern(raw, src_idx, dst_idx, also_retarget)
                    new_payload = pack_project(head, new_raw)
                    bak = prj.with_suffix(prj.suffix + ".bak")
                    shutil.copy2(prj, bak)
                    from ..project import write_project
                    write_project(prj, members, pname, new_payload)
                    self._send_json({'success': True, 'backup': str(bak)})
                except Exception as e:
                    self._send_json({'error': str(e)}, 500)
            elif parsed.path == '/api/patterns/copy':
                try:
                    data = json.loads(body)
                    src_idx = int(data['src_idx'])
                    dst_idx = int(data['dst_idx'])
                    manifest, payload, members = read_project(prj)
                    pname = payload_name(manifest)
                    head, raw = unpack_project(payload)
                    new_raw = copy_pattern_block(raw, src_idx, dst_idx)
                    new_payload = pack_project(head, new_raw)
                    bak = prj.with_suffix(prj.suffix + ".bak")
                    shutil.copy2(prj, bak)
                    from ..project import write_project
                    write_project(prj, members, pname, new_payload)
                    self._send_json({'success': True, 'backup': str(bak)})
                except Exception as e:
                    self._send_json({'error': str(e)}, 500)
            elif parsed.path == '/api/patterns/swap':
                try:
                    data = json.loads(body)
                    pat_a = int(data['pat_a'])
                    pat_b = int(data['pat_b'])
                    manifest, payload, members = read_project(prj)
                    pname = payload_name(manifest)
                    head, raw = unpack_project(payload)
                    new_raw = swap_patterns(raw, pat_a, pat_b)
                    new_payload = pack_project(head, new_raw)
                    bak = prj.with_suffix(prj.suffix + ".bak")
                    shutil.copy2(prj, bak)
                    from ..project import write_project
                    write_project(prj, members, pname, new_payload)
                    self._send_json({'success': True, 'backup': str(bak)})
                except Exception as e:
                    self._send_json({'error': str(e)}, 500)
            elif parsed.path == '/api/patterns/clear':
                try:
                    data = json.loads(body)
                    pat_idx = int(data['pat_idx'])
                    manifest, payload, members = read_project(prj)
                    pname = payload_name(manifest)
                    head, raw = unpack_project(payload)
                    new_raw = clear_pattern(raw, pat_idx)
                    new_payload = pack_project(head, new_raw)
                    bak = prj.with_suffix(prj.suffix + ".bak")
                    shutil.copy2(prj, bak)
                    from ..project import write_project
                    write_project(prj, members, pname, new_payload)
                    self._send_json({'success': True, 'backup': str(bak)})
                except Exception as e:
                    self._send_json({'error': str(e)}, 500)
            elif parsed.path == '/api/patterns/retarget-all':
                try:
                    data = json.loads(body)
                    from_pat = int(data['from_pat'])
                    to_pat = int(data['to_pat'])
                    manifest, payload, members = read_project(prj)
                    pname = payload_name(manifest)
                    head, raw = unpack_project(payload)
                    new_raw = retarget_all_pattern_refs(raw, from_pat, to_pat)
                    new_payload = pack_project(head, new_raw)
                    bak = prj.with_suffix(prj.suffix + ".bak")
                    shutil.copy2(prj, bak)
                    from ..project import write_project
                    write_project(prj, members, pname, new_payload)
                    self._send_json({'success': True, 'backup': str(bak)})
                except Exception as e:
                    self._send_json({'error': str(e)}, 500)
            elif parsed.path == '/api/import-song':
                try:
                    data = json.loads(body)
                    src_path = Path(data['src_path']).expanduser()
                    src_slot = int(data['src_slot'])
                    dst_slot = int(data['dst_slot'])
                    manifest, payload, members = read_project(prj)
                    pname = payload_name(manifest)
                    head, raw = unpack_project(payload)
                    sman, spayload, _ = read_project(src_path)
                    shead, sraw = unpack_project(spayload)
                    src_slots = get_song_slots(sraw)
                    dst_slots = get_song_slots(raw)
                    if src_slot < 0 or src_slot >= SONG_SLOTS or dst_slot < 0 or dst_slot >= SONG_SLOTS:
                        raise ValueError('invalid slot')
                    dst_slots[dst_slot] = bytes(src_slots[src_slot])
                    from ..songs import set_song_slots
                    new_raw = set_song_slots(raw, dst_slots)
                    new_payload = pack_project(head, new_raw)
                    bak = prj.with_suffix(prj.suffix + ".bak")
                    shutil.copy2(prj, bak)
                    from ..project import write_project
                    write_project(prj, members, pname, new_payload)
                    self._send_json({'success': True, 'backup': str(bak)})
                except Exception as e:
                    self._send_json({'error': str(e)}, 500)
            elif parsed.path == '/api/list-project-songs':
                try:
                    data = json.loads(body)
                    src_path = Path(data['src_path']).expanduser()
                    sman, spayload, _ = read_project(src_path)
                    shead, sraw = unpack_project(spayload)
                    info = get_all_songs_info(sraw)
                    self._send_json({'songs': info})
                except Exception as e:
                    self._send_json({'error': str(e)}, 500)
            else:
                self.send_error(404)

    return Handler


def run_web_server(prj: Path, port: int = 8080):
    handler = create_handler(prj)
    server = HTTPServer(('127.0.0.1', port), handler)
    url = f'http://127.0.0.1:{port}'
    print(f'Starting server at {url}')
    print('Press Ctrl+C to stop')
    try:
        webbrowser.open(url)
    except Exception:
        pass
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print('\nStopping server')
        server.shutdown()
