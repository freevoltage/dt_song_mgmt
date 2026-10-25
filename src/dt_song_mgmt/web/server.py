"""Web server."""

import webbrowser
from http.server import HTTPServer, BaseHTTPRequestHandler
from pathlib import Path
from urllib.parse import urlparse
import json
import shutil
import base64
import errno
from urllib.parse import quote

from ..patterns import get_all_patterns_info, rename_pattern, copy_pattern_block, copy_pattern_blocks, validate_pattern_mapping, clear_pattern, swap_patterns, move_pattern, retarget_all_pattern_refs
from ..project import pack_project, read_project, unpack_project, payload_name
from ..songs import get_song_slots, get_song_info, get_all_songs_info, collect_pattern_names, song_name, SONG_SLOTS, SONG_SIZE
from ..state import apply_operations, get_project_state
from ..constants import device_name


def create_handler(prj: Path):
    class Handler(BaseHTTPRequestHandler):
        def _apply_staged_operations(self, raw, operations):
            for op in operations:
                if op.get('type') == 'pattern_import':
                    src_path = Path(op['src_path']).expanduser().resolve()
                    if src_path == prj.expanduser().resolve():
                        raise ValueError('choose a different source project')
                    _manifest, payload, _members = read_project(src_path)
                    _head, source_raw = unpack_project(payload)
                    if device_name(source_raw, src_path.suffix) != device_name(raw, prj.suffix):
                        raise ValueError('patterns can only be imported between matching devices')
                    raw = copy_pattern_blocks(source_raw, raw, op.get('mappings'))
                else:
                    raw = apply_operations(raw, [op])
            return raw

        def _pattern_import_context(self, data):
            src_path = Path(data['src_path']).expanduser().resolve()
            if src_path == prj.expanduser().resolve():
                raise ValueError('choose a different source project')
            mappings = data.get('mappings')
            pairs = validate_pattern_mapping(mappings)
            _source_manifest, source_payload, _source_members = read_project(src_path)
            _source_head, source_raw = unpack_project(source_payload)
            target_manifest, target_payload, target_members = read_project(prj)
            target_head, target_raw = unpack_project(target_payload)
            source_device = device_name(source_raw, src_path.suffix)
            target_device = device_name(target_raw, prj.suffix)
            if source_device != target_device:
                raise ValueError(f'patterns can only be imported between matching devices ({source_device} → {target_device})')
            source_patterns = get_all_patterns_info(source_raw)
            target_patterns = get_all_patterns_info(target_raw)
            details = [
                {
                    'src_idx': src_idx,
                    'dst_idx': dst_idx,
                    'source': source_patterns[src_idx],
                    'destination': target_patterns[dst_idx],
                }
                for src_idx, dst_idx in pairs
            ]
            return src_path, source_raw, target_raw, target_head, target_members, payload_name(target_manifest), details, source_device

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
            elif parsed.path.startswith('/api/songs/') and parsed.path.endswith('/export'):
                try:
                    slot = int(parsed.path.split('/')[-2])
                    if not 0 <= slot < SONG_SLOTS:
                        raise ValueError('invalid song slot')
                    _manifest, payload, _ = read_project(prj)
                    _head, raw = unpack_project(payload)
                    rec = get_song_slots(raw)[slot]
                    filename = f"{slot:02d}_{song_name(rec)}.bin"
                    safe_filename = quote(filename, safe='')
                    self.send_response(200)
                    self.send_header('Content-Type', 'application/octet-stream')
                    self.send_header('Content-Disposition', f"attachment; filename*=UTF-8''{safe_filename}")
                    self.send_header('Content-Length', str(len(rec)))
                    self.end_headers()
                    self.wfile.write(rec)
                except Exception as e:
                    self._send_json({'error': str(e)}, 400)
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
                        old_songs = get_all_songs_info(raw)
                        new_raw = self._apply_staged_operations(raw, ops)
                        pattern_names = collect_pattern_names(new_raw)
                        slots = get_song_slots(new_raw)
                        songs = []
                        for i in range(len(slots)):
                            info = get_song_info(slots[i], pattern_names)
                            info['slot'] = i
                            songs.append(info)
                        patterns = get_all_patterns_info(new_raw)
                        changes = []
                        for old, new in zip(old_songs, songs):
                            if old == new:
                                continue
                            changes.append({
                                'slot': old['slot'],
                                'name_old': old['name'],
                                'name_new': new['name'],
                                'rows_old': old['row_count'],
                                'rows_new': new['row_count'],
                                'rows': [
                                    {'index': i, 'before': old['rows'][i] if i < len(old['rows']) else None,
                                     'after': new['rows'][i] if i < len(new['rows']) else None}
                                    for i in range(max(len(old['rows']), len(new['rows'])))
                                    if i >= len(old['rows']) or i >= len(new['rows']) or old['rows'][i] != new['rows'][i]
                                ],
                            })
                        self._send_json({'ok': True, 'changes': changes, 'songs': songs, 'patterns': patterns})
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
                    new_raw = self._apply_staged_operations(raw, ops)
                    new_payload = pack_project(head, new_raw)
                    bak = prj.with_suffix(prj.suffix + ".bak")
                    shutil.copy2(prj, bak)
                    from ..project import write_project
                    write_project(prj, members, pname, new_payload)
                    state = get_project_state(prj)
                    self._send_json({'ok': True, 'success': True, 'backup': str(bak), 'state': state})
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
            elif parsed.path == '/api/list-project-patterns':
                try:
                    data = json.loads(body)
                    src_path = Path(data['src_path']).expanduser().resolve()
                    if src_path == prj.expanduser().resolve():
                        raise ValueError('choose a different source project')
                    _manifest, payload, _members = read_project(src_path)
                    _head, raw = unpack_project(payload)
                    self._send_json({
                        'patterns': get_all_patterns_info(raw),
                        'device': device_name(raw, src_path.suffix),
                        'project_file': src_path.name,
                    })
                except Exception as e:
                    self._send_json({'error': str(e)}, 400)
            elif parsed.path == '/api/import-patterns/preview':
                try:
                    data = json.loads(body)
                    src_path, _source_raw, _target_raw, _target_head, _target_members, _target_name, details, device = self._pattern_import_context(data)
                    self._send_json({
                        'ok': True,
                        'source_project': src_path.name,
                        'device': device,
                        'mappings': details,
                    })
                except Exception as e:
                    self._send_json({'error': str(e)}, 400)
            elif parsed.path == '/api/import-patterns':
                try:
                    data = json.loads(body)
                    src_path, source_raw, target_raw, target_head, target_members, pname, details, device = self._pattern_import_context(data)
                    new_raw = copy_pattern_blocks(source_raw, target_raw, data.get('mappings'))
                    new_payload = pack_project(target_head, new_raw)
                    backup = prj.with_suffix(prj.suffix + '.bak')
                    shutil.copy2(prj, backup)
                    from ..project import write_project
                    write_project(prj, target_members, pname, new_payload)
                    self._send_json({
                        'success': True,
                        'backup': str(backup),
                        'source_project': src_path.name,
                        'device': device,
                        'mappings': details,
                    })
                except Exception as e:
                    self._send_json({'error': str(e)}, 400)
            elif parsed.path == '/api/import-song-file':
                try:
                    data = json.loads(body)
                    dst_slot = int(data['dst_slot'])
                    song_data = base64.b64decode(data['song_data'], validate=True)
                    if not 0 <= dst_slot < SONG_SLOTS:
                        raise ValueError('invalid target slot')
                    if len(song_data) != SONG_SIZE:
                        raise ValueError(f'song backup must be exactly {SONG_SIZE} bytes')
                    manifest, payload, members = read_project(prj)
                    pname = payload_name(manifest)
                    head, raw = unpack_project(payload)
                    slots = get_song_slots(raw)
                    slots[dst_slot] = song_data
                    from ..songs import set_song_slots
                    new_payload = pack_project(head, set_song_slots(raw, slots))
                    bak = prj.with_suffix(prj.suffix + '.bak')
                    shutil.copy2(prj, bak)
                    from ..project import write_project
                    write_project(prj, members, pname, new_payload)
                    self._send_json({'success': True, 'backup': str(bak)})
                except Exception as e:
                    self._send_json({'error': str(e)}, 400)
            elif parsed.path == '/api/list-project-songs':
                try:
                    data = json.loads(body)
                    src_path = Path(data['src_path']).expanduser()
                    sman, spayload, _ = read_project(src_path)
                    shead, sraw = unpack_project(spayload)
                    info = get_all_songs_info(sraw)
                    from ..constants import device_name
                    self._send_json({'songs': info, 'device': device_name(sraw, src_path.suffix), 'project_file': src_path.name})
                except Exception as e:
                    self._send_json({'error': str(e)}, 500)
            else:
                self.send_error(404)

    return Handler


def run_web_server(prj: Path, port: int = 8080, auto_port: bool = True):
    handler = create_handler(prj)
    requested_port = port
    server = None
    candidates = [port] if not auto_port or port == 0 else range(port, min(port + 1000, 65536))
    for candidate in candidates:
        try:
            server = HTTPServer(('127.0.0.1', candidate), handler)
            break
        except OSError as exc:
            if not auto_port or exc.errno != errno.EADDRINUSE:
                raise SystemExit(f'Cannot start DSM on port {candidate}: {exc}') from exc
    if server is None:
        raise SystemExit(f'No available port found from {requested_port} through {min(requested_port + 999, 65535)}.')
    port = server.server_address[1]
    url = f'http://127.0.0.1:{port}'
    if port != requested_port:
        print(f'Port {requested_port} is already in use; using port {port}.')
    print(f'Starting server at {url}')
    print('Press Ctrl+C to stop')
    try:
        webbrowser.open(url, new=1)
    except Exception:
        pass
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print('\nStopping server')
        server.shutdown()
