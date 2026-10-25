#!/usr/bin/env python3
2: \"\"\"Dump and restore Digitakt II song blobs inside an Elektron Transfer .dt2prj.
3: 
4: The Transfer payload is LZ4-linked 32 KiB blocks, not raw song bytes. This
5: script decompresses the project, copies the 16 uncompressed song slots (3072
6: bytes each), and recompresses on restore so the device can import the file.
7: 
8: Dump:
9:   python ./dt_song_mgmt.py project.dt2prj
10:     → ./SONGS_<stem>/00_<name>.bin … 15_<name>.bin  (16 × 3072-byte slots)
11:     → ./SONGS_<stem>/songs.html  (rows, mute maps)
12: 
13: Restore (overwrites the .dt2prj; writes a .bak first):
14:     python ./dt_song_mgmt.py project.dt2prj ./SONGS_<stem>
15:     python ./dt_song_mgmt.py project.dt2prj ./SONGS_<stem> NEW_NAME
16: 
17: Restore matches files by the NN_ slot prefix. Slots with no file
18: are cleared to an empty song (the folder is the full 16-slot setlist).
19: 
20: NEW_NAME - new project name (not just file/folder names but actual name in .dt2prj payload)
21: \"\"\"
22: 
23: from __future__ import annotations
24: 
25: import ctypes
26: import ctypes.util
27: import json
28: import shutil
29: import struct
30: import sys
31: import zipfile
32: import zlib
33: from html import escape
34: from pathlib import Path
35: 
36: MAGIC_TAIL = bytes.fromhex(\"bacef00c\")
37: MAGIC_HEAD = bytes.fromhex(\"beefbace\")
38: SONG_SLOTS = 16
39: SONG_SIZE = 3072  # uncompressed songStorage record
40: SONG_TABLE_LEN = SONG_SLOTS * SONG_SIZE
41: LZ4_BLOCK = 32768
42: # Transfer wrapper around the packed project body:
43: #   [31-byte header starting ac11d303] [body] [crc32][size][aaa1daaa]
44: PAYLOAD_HEAD_LEN = 31
45: PAYLOAD_TAIL_LEN = 12  # checksum + size + tail magic
46: PAYLOAD_WRAP_LEN = PAYLOAD_HEAD_LEN + PAYLOAD_TAIL_LEN  # 43
47: UNCOMP_SIZE_OFF = 25  # u32be uncompressed project size in the 31-byte head
48: # +Drive / Transfer project title: 13 bytes, NUL-terminated, '~'-padded.
49: PROJECT_NAME_LEN = 13
50: SONG_NAME_LEN = 16
51: # Song-mode layout (SPEC.md §8): 4-byte header, 16-byte name, rows at +0x14.
52: # Name at +0x04 ends where the row array begins (0x04 + 16 = 0x14).
53: SONG_NAME_OFF = 4
54: SONG_ROW_OFF = 0x14
55: SONG_ROW_SIZE = 0x1D  # 29
56: SONG_ROW_MAX = 99
57: SONG_ROW_COUNT_OFF = 0x0B4B  # u16be active row count (SPEC.md §8)
58: SONG_TEMPO_OFF = 0x0B50  # u16be leftover / default tempo (raw = BPM * 120)
59: SONG_TRACKS = 16
60: BPM_SCALE = 120  # raw = BPM * 120
61: # Row byte 1 = Tag ID (SPEC.md §9: +0x01 on disk).
62: #   1 = (PTN NAME): 16-byte custom name at pattern config +0x00, else A01
63: #   2.. = static keywords from Digitakt II MAIN OS (Song::updateMirror table)
64: SONG_ROW_LABELS: tuple[str | None, ...] = (
65:     None,  # 0: unused
66:     None,  # 1: (PTN NAME) — resolved from the pattern
67:     \"INTRO\",
68:     \"OUTRO\",
69:     \"CHORUS\",
70:     \"SOLO\",
71:     \"FILL\",
72:     \"PEAK\",
73:     \"JAM\",
74:     \"NOISE\",
75:     \"MISC\",
76:     \"PAUSE\",
77: )
78: PATTERN_SLOTS = 128
79: PATTERN_BASE = 0x200
80: PATTERN_STRIDE = 0x15C00  # SPEC.md §2
81: PATTERN_NAME_OFF = 0x15AA4  # 40-byte master; first 16 bytes are the name
82: PATTERN_NAME_LEN = 16
83: 
84: PAYLOAD_HEAD_MAGIC = bytes.fromhex(\"ac11d303\")
85: PAYLOAD_TAIL_MAGIC = bytes.fromhex(\"aaa1daaa\")
86: 
87: NAME_CHAR = set(\"ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_~ -#$\")
88: 
89: 
90: def die(msg: str, code: int = 1) -> None:
91:     print(f\"dt_song_mgmt: {msg}\", file=sys.stderr)
92:     raise SystemExit(code)
93: 
94: 
95: def payload_name(manifest: dict) -> str:
96:     name = manifest.get(\"Payload\")
97:     if not name:
98:         die(\"manifest.json has no Payload\")
99:     return name
100: 
101: 
102: def read_project(prj: Path) -> tuple[dict, bytes, list[tuple[zipfile.ZipInfo, bytes]]]:
103:     if not zipfile.is_zipfile(prj):
104:         die(f\"not a zip/.dt2prj: {prj}\")
105:     members: list[tuple[zipfile.ZipInfo, bytes]] = []
106:     with zipfile.ZipFile(prj, \"r\") as zf:
107:         try:
108:             manifest = json.loads(zf.read(\"manifest.json\"))
109:         except KeyError:
110:             die(\"manifest.json missing from archive\")
111:         pname = payload_name(manifest)
112:         try:
113:             payload = zf.read(pname)
114:         except KeyError:
115:             die(f\"payload {pname!r} missing from archive\")
116:         for info in zf.infolist():
117:             members.append((info, zf.read(info.filename)))
118:     return manifest, payload, members
119: 
120: 
121: def write_project(
122:     prj: Path,
123:     members: list[tuple[zipfile.ZipInfo, bytes]],
124:     pname: str,
125:     payload: bytes,
126:     new_pname: str | None = None,
127: ) -> None:
128:     out_name = new_pname or pname
129:     tmp = prj.with_suffix(prj.suffix + \".tmp\")
130:     with zipfile.ZipFile(tmp, \"w\") as zf:
131:         for info, data in members:
132:             filename = info.filename
133:             blob = data
134:             if filename == \"manifest.json\" and new_pname:
135:                 man = json.loads(data)
136:                 man[\"Payload\"] = new_pname
137:                 blob = (json.dumps(man, indent=2) + \"\
\").encode(\"utf-8\")
138:             elif filename == pname:
139:                 filename = out_name
140:                 blob = payload
141:             out = zipfile.ZipInfo(filename=filename, date_time=info.date_time)
142:             out.compress_type = info.compress_type
143:             out.external_attr = info.external_attr
144:             zf.writestr(out, blob)
145:     tmp.replace(prj)
146: 
147: 
148: def clean_project_name(name: str) -> str:
149:     out: list[str] = []
150:     for ch in name.strip():
151:         if ch.islower() and ch.upper() in NAME_CHAR:
152:             out.append(ch.upper())
153:         elif ch in NAME_CHAR:
154:             out.append(ch)
155:         elif ch.isspace():
156:             out.append(\"~\")
157:     cleaned = \"\".join(out).strip(\"~\") or \"PROJECT\"
158:     if len(cleaned) > PROJECT_NAME_LEN:
159:         print(f\"note: project name truncated to {PROJECT_NAME_LEN} characters\")
160:         cleaned = cleaned[:PROJECT_NAME_LEN]
161:     return cleaned
162: 
163: 
164: def encode_project_name_field(name: str) -> bytes:
165:     raw = clean_project_name(name).encode(\"latin-1\")
166:     if len(raw) >= PROJECT_NAME_LEN:
167:         return raw[:PROJECT_NAME_LEN]
168:     return raw + b\"\\x00\" + b\"~\" * (PROJECT_NAME_LEN - len(raw) - 1)
169: 
170: 
171: def read_project_name_field(raw: bytes) -> tuple[int, str]:
172:     i = raw.find(MAGIC_HEAD)
173:     if i < 0:
174:         die(\"no beefbace marker in project — cannot locate project name\")
175:     off = i + 4 + 4
176:     if off + PROJECT_NAME_LEN > len(raw):
177:         die(\"project too short for project name field\")
178:     field = raw[off : off + PROJECT_NAME_LEN]
179:     n = field.find(b\"\\x00\")
180:     name = field if n < 0 else field[:n]
181:     return off, name.decode(\"latin-1\").rstrip(\"~\")
182: 
183: 
184: def patch_project_name(raw: bytes, new_name: str) -> tuple[bytes, str, str]:
185:     off, old = read_project_name_field(raw)
186:     cleaned = clean_project_name(new_name)
187:     field = encode_project_name_field(cleaned)
188:     patched = bytearray(raw)
189:     patched[off : off + PROJECT_NAME_LEN] = field
190:     return bytes(patched), cleaned, old
191: 
192: 
193: def payload_crc32(data: bytes) -> int:
194:     \"\"\"CRC-32 of the compressed stream (chunk lengths, LZ4 blocks, null terminator).
195: 
196:     Reflected poly 0xEDB88320, register init 0, xorout 0xFFFFFFFF.
197:     zlib.crc32(data) seeds the register with 0xFFFFFFFF and Transfer rejects
198:     that footer as \"payload has incorrect checksum\". Passing 0xFFFFFFFF as the
199:     zlib starting value cancels that seed, leaving init 0.
200:     \"\"\"
201:     return zlib.crc32(data, 0xFFFFFFFF) & 0xFFFFFFFF
202: 
203: 
204: # --- LZ4 (raw blocks, 32 KiB, linked on decompress) ---
205: 
206: _LZ4 = None
207: _LZ4_TRIED = False
208: 
209: 
210: def _lz4_lib():
211:     global _LZ4, _LZ4_TRIED
212:     if _LZ4_TRIED:
213:         return _LZ4
214:     _LZ4_TRIED = True
215:     path = ctypes.util.find_library(\"lz4\")
216:     if not path:
217:         return None
218:     lib = ctypes.CDLL(path)
219:     lib.LZ4_compressBound.argtypes = [ctypes.c_int]
220:     lib.LZ4_compressBound.restype = ctypes.c_int
221:     lib.LZ4_compress_default.argtypes = [
222:         ctypes.c_char_p,
223:         ctypes.c_char_p,
224:         ctypes.c_int,
225:         ctypes.c_int,
226:     ]
227:     lib.LZ4_compress_default.restype = ctypes.c_int
228:     _LZ4 = lib
229:     return lib
230: 
231: 
232: def lz4_decompress_block(src: bytes, out: bytearray) -> None:
233:     \"\"\"Decode one raw LZ4 block, appending into `out` (linked lookback).\"\"\"
234:     i = 0
235:     n = len(src)
236:     while i < n:
237:         token = src[i]
238:         i += 1
239:         lit = token >> 4
240:         if lit == 15:
241:             while True:
242:                 if i >= n:
243:                     raise ValueError(\"truncated LZ4 literal length\")
244:                 extra = src[i]
245:                 i += 1
246:                 lit += extra
247:                 if extra != 255:
248:                     break
249:         if i + lit > n:
250:             raise ValueError(\"truncated LZ4 literals\")
251:         out.extend(src[i : i + lit])
252:         i += lit
253:         if i >= n:
254:             break
255:         if i + 2 > n:
256:             raise ValueError(\"truncated LZ4 match offset\")
257:         offset = src[i] | (src[i + 1] << 8)
258:         i += 2
259:         if offset == 0 or offset > len(out):
260:             raise ValueError(f\"bad LZ4 offset {offset} (out {len(out)})\")
261:         mlen = (token & 15) + 4
262:         if (token & 15) == 15:
263:             while True:
264:                 if i >= n:
265:                     raise ValueError(\"truncated LZ4 match length\")
266:                 extra = src[i]
267:                 i += 1
268:                 mlen += extra
269:                 if extra != 255:
270:                     break
271:         start = len(out) - offset
272:         for _ in range(mlen):
273:             out.append(out[start])
274:             start += 1
275: 
276: 
277: def _lz4_compress_py(src: bytes) -> bytes:
278:     \"\"\"Independent raw LZ4 block (greedy hash matcher).\"\"\"
279:     n = len(src)
280:     if n == 0:
281:         return b\"\\x00\"
282:     HASH_LOG = 12
283:     HASH_SIZE = 1 << HASH_LOG
284:     table = [-1] * HASH_SIZE
285:     out = bytearray()
286:     i = 0
287:     anchor = 0
288: 
289:     def hash4(p: int) -> int:
290:         v = int.from_bytes(src[p : p + 4], \"little\")
291:         return ((v * 2654435761) & 0xFFFFFFFF) >> (32 - HASH_LOG)
292: 
293:     def emit(lit_from: int, lit_to: int, match_off: int | None, match_len: int) -> None:
294:         literals = src[lit_from:lit_to]
295:         nlit = len(literals)
296:         token_lit = 15 if nlit >= 15 else nlit
297:         if match_off is None:
298:             out.append(token_lit << 4)
299:             if nlit >= 15:
300:                 rest = nlit - 15
301:                 while rest >= 255:
302:                     out.append(255)
303:                     rest -= 255
304:                 out.append(rest)
305:             out.extend(literals)
306:             return
307:         nml = match_len - 4
308:         token_ml = 15 if nml >= 15 else nml
309:         out.append((token_lit << 4) | token_ml)
310:         if nlit >= 15:
311:             rest = nlit - 15
312:             while rest >= 255:
313:                 out.append(255)
314:                 rest -= 255
315:             out.append(rest)
316:         out.extend(literals)
317:         out.append(match_off & 0xFF)
318:         out.append((match_off >> 8) & 0xFF)
319:         if nml >= 15:
320:             rest = nml - 15
321:             while rest >= 255:
322:                 out.append(255)
323:                 rest -= 255
324:             out.append(rest)
325: 
326:     last_match = n - 12  # LZ4 last sequence: ≥5 bytes of literals, ≥12 before end for matches
327:     while i < last_match:
328:         h = hash4(i)
329:         ref = table[h]
330:         table[h] = i
331:         if ref < 0 or i - ref >= 65536 or src[ref : ref + 4] != src[i : i + 4]:
332:             i += 1
333:             continue
334:         ml = 4
335:         while i + ml < n - 5 and src[ref + ml] == src[i + ml]:
336:             ml += 1
337:         emit(anchor, i, i - ref, ml)
338:         i += ml
339:         anchor = i
340:         if i < last_match:
341:             table[hash4(i - 2)] = i - 2
342:     emit(anchor, n, None, 0)
343:     return bytes(out)
344: 
345: 
346: def lz4_compress_block(src: bytes) -> bytes:
347:     lib = _lz4_lib()
348:     if lib is not None:
349:         bound = lib.LZ4_compressBound(len(src))
350:         buf = ctypes.create_string_buffer(bound)
351:         n = lib.LZ4_compress_default(src, buf, len(src), bound)
352:         if n <= 0:
353:             die(\"lz4 compress failed\")
354:         return buf.raw[:n]
355:     return _lz4_compress_py(src)
356: 
357: 
358: def unwrap_payload(payload: bytes) -> tuple[bytes, list[bytes]]:
359:     \"\"\"Split Transfer payload into header + LZ4 block list.\"\"\"
360:     if len(payload) < PAYLOAD_WRAP_LEN:
361:         die(\"payload too short for Transfer wrapper\")
362:     if payload[:4] != PAYLOAD_HEAD_MAGIC:
363:         die(\"payload missing Transfer head magic (ac11d303)\")
364:     if payload[-4:] != PAYLOAD_TAIL_MAGIC:
365:         die(\"payload missing Transfer tail magic (aaa1daaa)\")
366:     i = PAYLOAD_HEAD_LEN
367:     blocks: list[bytes] = []
368:     end = len(payload) - PAYLOAD_TAIL_LEN
369:     while i + 4 <= end:
370:         n = struct.unpack_from(\">I\", payload, i)[0]
371:         i += 4
372:         if n == 0:
373:             return payload[:PAYLOAD_HEAD_LEN], blocks
374:         if n < 0 or i + n > end:
375:             die(\"payload chunk list is corrupt\")
376:         blocks.append(payload[i : i + n])
377:         i += n
378:     die(\"payload chunk list is corrupt (no terminating 0-length chunk)\")
379:     raise AssertionError
380: 
381: 
382: def decompress_blocks(blocks: list[bytes]) -> bytes:
383:     out = bytearray()
384:     try:
385:         for b in blocks:
386:             lz4_decompress_block(b, out)
387:     except ValueError as e:
388:         die(
389:             f\"LZ4 decompress failed ({e}). Restore into an original Transfer \"
390:             \"export, not a previously broken file.\"
391:         )
392:     return bytes(out)
393: 
394: 
395: def compress_raw(raw: bytes) -> list[bytes]:
396:     blocks: list[bytes] = []
397:     for i in range(0, len(raw), LZ4_BLOCK):
398:         blocks.append(lz4_compress_block(raw[i : i + LZ4_BLOCK]))
399:     return blocks
400: 
401: 
402: def wrap_payload(head: bytes, blocks: list[bytes]) -> bytes:
403:     \"\"\"Rebuild Transfer TLV framing, uncompressed-size, CRC32 around LZ4 blocks.\"\"\"
404:     if len(head) < PAYLOAD_HEAD_LEN:
405:         die(\"Transfer head too short\")
406:     body = b\"\".join(struct.pack(\">I\", len(c)) + c for c in blocks) + struct.pack(\">I\", 0)
407:     crc = payload_crc32(body)
408:     return (
409:         head[:PAYLOAD_HEAD_LEN]
410:         + body
411:         + struct.pack(\">I\", crc)
412:         + struct.pack(\">I\", len(body))
413:         + PAYLOAD_TAIL_MAGIC
414:     )
415: 
416: 
417: def set_uncompressed_size(head: bytes, size: int) -> bytes:
418:     h = bytearray(head[:PAYLOAD_HEAD_LEN])
419:     if len(h) < UNCOMP_SIZE_OFF + 4:
420:         die(\"Transfer head too short for uncompressed size\")
421:     struct.pack_into(\">I\", h, UNCOMP_SIZE_OFF, size)
422:     return bytes(h)
423: 
424: 
425: def unpack_project(payload: bytes) -> tuple[bytes, bytes]:
426:     head, blocks = unwrap_payload(payload)
427:     raw = decompress_blocks(blocks)
428:     stored = struct.unpack_from(\">I\", head, UNCOMP_SIZE_OFF)[0]
429:     if stored != len(raw):
430:         print(f\"note: header uncompressed size {stored} != decoded {len(raw)}\")
431:     return head, raw
432: 
433: 
434: def pack_project(head: bytes, raw: bytes) -> bytes:
435:     head = set_uncompressed_size(head, len(raw))
436:     return wrap_payload(head, compress_raw(raw))
437: 
438: 
439: def song_table_off(raw: bytes) -> int:
440:     if len(raw) < SONG_TABLE_LEN + 4:
441:         die(\"uncompressed project too short to hold 16 songs\")
442:     if raw[-4:] != MAGIC_TAIL:
443:         die(\"uncompressed project does not end with bacef00c\")
444:     # Songs sit immediately before the 4-byte 0xBACEF00C terminator.
445:     return len(raw) - SONG_TABLE_LEN - 4
446: 
447: 
448: def song_name(rec: bytes) -> str:
449:     field = rec[SONG_NAME_OFF : SONG_NAME_OFF + SONG_NAME_LEN]
450:     return decode_name_field(field) or \"EMPTY\"
451: 
452: 
453: def pattern_label(idx: int) -> str:
454:     if not 0 <= idx <= 127:
455:         return f\"?{idx}\"
456:     return f\"{chr(ord('A') + idx // 16)}{(idx % 16) + 1:02d}\"
457: 
458: 
459: def decode_name_field(field: bytes) -> str:
460:     n = field.find(b\"\\x00\")
461:     raw = field if n < 0 else field[:n]
462:     return raw.decode(\"cp1252\", errors=\"replace\").strip()
463: 
464: 
465: def pattern_name_at(raw: bytes, idx: int) -> str:
466:     if not 0 <= idx < PATTERN_SLOTS:
467:         return \"\"
468:     off = PATTERN_BASE + idx * PATTERN_STRIDE + PATTERN_NAME_OFF
469:     if off + PATTERN_NAME_LEN > len(raw):
470:         return \"\"
471:     return decode_name_field(raw[off : off + PATTERN_NAME_LEN])
472: 
473: 
474: def collect_pattern_names(raw: bytes) -> list[str]:
475:     return [pattern_name_at(raw, i) for i in range(PATTERN_SLOTS)]
476: 
477: 
478: def row_label(tag_id: int, pattern_idx: int, saved_pattern_name: str) -> str:
479:     \"\"\"What Digitakt shows in the LABEL column (SPEC.md §9).\"\"\"
480:     if tag_id == 1:
481:         return saved_pattern_name or pattern_label(pattern_idx)
482:     if 0 <= tag_id < len(SONG_ROW_LABELS):
483:         name = SONG_ROW_LABELS[tag_id]
484:         if name:
485:             return name
486:     if tag_id == 0:
487:         return \"\"
488:     return f\"T{tag_id}\"
489: 
490: 
491: def format_length(length: int) -> str:
492:     \"\"\"Row length: 1000–1024 display as K00–K24 on the device.\"\"\"
493:     if 1000 <= length <= 1024:
494:         return f\"K{length - 1000:02d}\"
495:     return str(length)
496: 
497: 
498: def format_bpm(raw: int) -> str:
499:     if raw == 0:
500:         return \"inherit\"
501:     bpm = raw / BPM_SCALE
502:     if abs(bpm - round(bpm)) < 1e-6:
503:         return str(int(round(bpm)))
504:     return f\"{bpm:.2f}\"
505: 
506: 
507: def song_row_count(rec: bytes) -> int:
508:     \"\"\"Active rows: u16be at +0x0B4B, else scan until an all-zero 29-byte row.\"\"\"
509:     n = 0
510:     if len(rec) >= SONG_ROW_COUNT_OFF + 2:
511:         n = struct.unpack_from(\">H\", rec, SONG_ROW_COUNT_OFF)[0]
512:         if n > SONG_ROW_MAX:
513:             n = 0
514:     if n:
515:         return n
516:     for i in range(SONG_ROW_MAX):
517:         off = SONG_ROW_OFF + i * SONG_ROW_SIZE
518:         if off + SONG_ROW_SIZE > len(rec):
519:             return i
520:         if rec[off : off + SONG_ROW_SIZE] == bytes(SONG_ROW_SIZE):
521:             return i
522:     return SONG_ROW_MAX
523: 
524: 
525: def parse_song_row(row: bytes, pattern_names: list[str] | None = None) -> dict:
526:     # Byte 7 = tracks 1–8 (bit 0 = T1), byte 8 = tracks 9–16.
527:     mute = row[7] | (row[8] << 8)
528:     length = struct.unpack_from(\">H\", row, 9)[0]
529:     if length > 1024:
530:         swapped = struct.unpack_from(\"<H\", row, 9)[0]
531:         if 1 <= swapped <= 1024:
532:             length = swapped
533:     pat = row[0]
534:     slot = pattern_label(pat)
535:     saved = \"\"
536:     if pattern_names and 0 <= pat < len(pattern_names):
537:         saved = pattern_names[pat]
538:     tag_id = row[1]
539:     return {
540:         \"pattern\": pat,
541:         \"pattern_name\": slot,
542:         \"label_idx\": tag_id,
543:         \"label\": row_label(tag_id, pat, saved),
544:         \"repeat\": row[2],
545:         \"bpm_raw\": struct.unpack_from(\">I\", row, 3)[0],
546:         \"mute\": mute,
547:         \"length\": length,
548:     }
549: 
550: 
551: def parse_song(rec: bytes, pattern_names: list[str] | None = None) -> dict:
552:     n = song_row_count(rec)
553:     rows = []
554:     for i in range(n):
555:         off = SONG_ROW_OFF + i * SONG_ROW_SIZE
556:         if off + SONG_ROW_SIZE > len(rec):
557:             break
558:         rows.append(parse_song_row(rec[off : off + SONG_ROW_SIZE], pattern_names))
559:     default_bpm = None
560:     if len(rec) >= SONG_TEMPO_OFF + 2:
561:         raw = struct.unpack_from(\">H\", rec, SONG_TEMPO_OFF)[0]
562:         if raw % BPM_SCALE == 0:
563:             bpm = raw // BPM_SCALE
564:             if 30 <= bpm <= 300:
565:                 default_bpm = bpm
566:     return {
567:         \"name\": song_name(rec),
568:         \"rows\": rows,
569:         \"default_bpm\": default_bpm,
570:     }
571: 
572: 
573: def mute_pads_html(mute: int) -> str:
574:     \"\"\"Digitakt-style 2×8 trig pads: upper 9–16, lower 1–8.\"\"\"
575: 
576:     def pad(t: int) -> str:
577:         muted = bool(mute & (1 << (t - 1)))
578:         state = \"muted\" if muted else \"live\"
579:         label = \"muted\" if muted else \"live\"
580:         return f'<span class=\"pad {state}\" title=\"T{t} {label}\">{t}</span>'
581: 
582:     upper = \"\".join(pad(t) for t in range(9, 17))
583:     lower = \"\".join(pad(t) for t in range(1, 9))
584:     return (
585:         '<td class=\"mutes\"><div class=\"pads\">'
586:         f'<div class=\"pad-row\">{upper}</div>'
587:         f'<div class=\"pad-row\">{lower}</div>'
588:         \"</div></td>\"
589:     )
590: 
591: 
592: def render_songs_html(
593:     title: str,
594:     slots: list[bytes],
595:     pattern_names: list[str] | None = None,
596: ) -> str:
597:     \"\"\"Self-contained setlist page: pattern, repeats, BPM, length, mute map.\"\"\"
598:     parsed = [parse_song(rec, pattern_names) for rec in slots]
599:     toc = []
600:     sections = []
601:     for i, song in enumerate(parsed):
602:         name = song[\"name\"]
603:         empty = name == \"EMPTY\" and not song[\"rows\"]
604:         n_rows = len(song[\"rows\"])
605:         cls = \" empty\" if empty else \"\"
606:         toc.append(
607:             f'<a href=\"#s{i:02d}\" class=\"toc-item{cls}\">'
608:             f\"<span class='slot'>{i:02d}</span>\"
609:             f\"<span class='nm'>{escape(name)}</span>\"
610:             f\"<span class='n'>{n_rows}</span></a>\"
611:         )
612:         meta = [f\"{n_rows} row{'s' if n_rows != 1 else ''}\"]
613:         if song[\"default_bpm\"] is not None:
614:             meta.append(f\"{song['default_bpm']} BPM\")
615:         body = []
616:         if not song[\"rows\"]:
617:             body.append('<p class=\"empty-msg\">No rows</p>')
618:         else:
619:             body.append(
620:                 \"<table><thead><tr>\"
621:                 \"<th>#</th><th>Pattern</th><th>Repeat</th>\"
622:                 \"<th>BPM</th><th>Length</th>\"
623:                 \"<th class='m-label'>Mute</th></tr></thead><tbody>\"
624:             )
625:             for r_i, row in enumerate(song[\"rows\"], start=1):
626:                 body.append(
627:                     \"<tr>\"
628:                     f\"<td class='idx'>{r_i}</td>\"
629:                     f\"<td class='pat'>{escape(row['pattern_name'])}</td>\"
630:                     f\"<td class='rep'>×{row['repeat']}</td>\"
631:                     f\"<td class='bpm'>{escape(format_bpm(row['bpm_raw']))}</td>\"
632:                     f\"<td class='len'>{escape(format_length(row['length']))}</td>\"
633:                     f\"{mute_pads_html(row['mute'])}</tr>\"
634:                 )
635:             body.append(\"</tbody></table>\")
636:         sections.append(
637:             f'<section id=\"s{i:02d}\" class=\"song{cls}\">'
638:             f\"<h2><span class='slot'>{i:02d}</span> {escape(name)} \"
639:             f\"<span class='meta'>{escape(' · '.join(meta))}</span></h2>\"
640:             f\"{''.join(body)}</section>\"
641:         )
642: 
643:     css = \"\"\"
644: :root { color-scheme: dark; }
645: * { box-sizing: border-box; }
646: body {
647:   margin: 0; padding: 24px 28px 48px;
648:   font: 13px/1.4 ui-monospace, SFMono-Regular, Menlo, Consolas, monospace;
649:   background: #141414; color: #e6e6e6;
650: }
651: h1 { font-size: 16px; font-weight: 650; margin: 0 0 6px; }
652: .sub { color: #8c8c8c; margin: 0 0 18px; }
653: nav.toc {
654:   display: grid; grid-template-columns: repeat(auto-fill, minmax(140px, 1fr));
655:   gap: 6px; margin: 0 0 28px;
656: }
657: .toc-item {
658:   display: flex; gap: 8px; align-items: baseline;
659:   padding: 6px 8px; border: 1px solid #2c2c2c; border-radius: 4px;
660:   color: inherit; text-decoration: none; background: #1a1a1a;
661: }
662: .toc-item:hover { border-color: #4a4a4a; }
663: .toc-item.empty { opacity: 0.45; }
664: .toc-item .slot, h2 .slot {
665:   color: #8c8c8c; font-variant-numeric: tabular-nums;
666: }
667: .toc-item .nm { flex: 1; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
668: .toc-item .n { color: #6e6e6e; }
669: section.song {
670:   margin: 0 0 22px; padding: 14px 16px 16px;
671:   background: #1b1b1b; border: 1px solid #2a2a2a; border-radius: 6px;
672: }
673: section.song.empty { opacity: 0.55; }
674: h2 { font-size: 14px; font-weight: 650; margin: 0 0 10px; }
675: h2 .meta { color: #8c8c8c; font-weight: 500; font-size: 12px; }
676: .empty-msg { color: #8c8c8c; margin: 0; }
677: table { border-collapse: collapse; width: max-content; max-width: 100%; }
678: th, td { padding: 3px 8px; text-align: left; white-space: nowrap; }
679: th { color: #8c8c8c; font-weight: 500; font-size: 11px; }
680: td.idx { color: #6e6e6e; font-variant-numeric: tabular-nums; vertical-align: middle; }
681: td.pat { font-weight: 650; vertical-align: middle; }
682: td.rep, td.bpm, td.len { vertical-align: middle; }
683: td.mutes { padding: 6px 8px; }
684: .pads { display: flex; flex-direction: column; gap: 3px; }
685: .pad-row { display: flex; gap: 3px; }
686: .pad {
687:   width: 22px; height: 22px; border-radius: 3px;
688:   display: flex; align-items: center; justify-content: center;
689:   font-size: 10px; font-weight: 650; font-variant-numeric: tabular-nums;
690: }
691: .pad.live { background: #d4652f; color: #1a0c06; }
692: .pad.muted { background: #2a2a2a; color: #5a5a5a; }
693: th.m-label { color: #8c8c8c; font-weight: 500; }
694: tbody tr:hover td:not(.mutes) { background: #222; }
695: \"\"\".strip()
696: 
697:     return (
698:         \"<!DOCTYPE html>\
<html lang='en'><head><meta charset='utf-8'>\"
699:         f\"<title>{escape(title)} songs</title>\"
700:         f\"<style>{css}</style></head><body>\"
701:         f\"<h1>{escape(title)}</h1>\"
702:         \"<p class='sub'>16 song slots — pattern, repeats, BPM, length, mute pads \"
703:         \"(9–16 over 1–8; lit = playing, dark = muted).</p>\"
704:         f\"<nav class='toc'>{''.join(toc)}</nav>\"
705:         f\"{''.join(sections)}</body></html>\
\"
706:     )
707: 
708: 
709: def empty_song_template(raw: bytes, start: int) -> bytes:
710:     \"\"\"Blank 3072-byte slot copied from this project's first EMPTY slot.\"\"\"
711:     for i in range(SONG_SLOTS):
712:         rec = raw[start + i * SONG_SIZE : start + (i + 1) * SONG_SIZE]
713:         if song_name(rec) == \"EMPTY\":
714:             return rec
715:     rec = bytearray(SONG_SIZE)
716:     rec[SONG_TEMPO_OFF : SONG_TEMPO_OFF + 2] = b\"\\x38\\x40\"  # 120 BPM leftover in factory-empty slots
717:     return bytes(rec)
718: 
719: 
720: def sanitize(name: str) -> str:
721:     out = \"\".join(ch if ch.isalnum() or ch in \"~-._\" else \"_\" for ch in name)
722:     return out.strip(\"._\") or \"song\"
723: 
724: 
725: def slot_index_from_name(path: Path) -> int | None:
726:     stem = path.stem
727:     if len(stem) >= 2 and stem[:2].isdigit() and (len(stem) == 2 or stem[2] in \"_-.\"):
728:         idx = int(stem[:2])
729:         if 0 <= idx < SONG_SLOTS:
730:             return idx
731:     return None
732: 
733: 
734: def dump_songs(prj: Path) -> Path:
735:     _manifest, payload, _ = read_project(prj)
736:     _head, raw = unpack_project(payload)
737:     start = song_table_off(raw)
738:     outdir = Path.cwd() / f\"SONGS_{prj.stem}\"
739:     outdir.mkdir(parents=True, exist_ok=True)
740:     for p in outdir.glob(\"*.bin\"):
741:         p.unlink()
742:     used = 0
743:     slots: list[bytes] = []
744:     for i in range(SONG_SLOTS):
745:         rec = raw[start + i * SONG_SIZE : start + (i + 1) * SONG_SIZE]
746:         slots.append(rec)
747:         name = song_name(rec)
748:         if name != \"EMPTY\":
749:             used += 1
750:         path = outdir / f\"{i:02d}_{sanitize(name)}.bin\"
751:         path.write_bytes(rec)
752:         print(f\"dump  {path.name:40s}  {len(rec):5d} bytes  {name}\")
753:     html_path = outdir / \"songs.html\"
754:     html_path.write_text(
755:         render_songs_html(prj.stem, slots, collect_pattern_names(raw)),
756:         encoding=\"utf-8\",
757:     )
758:     print(f\"wrote {SONG_SLOTS} slots ({used} named) to {outdir}\")
759:     print(f\"wrote {html_path}\")
760:     print(f\"uncompressed project {len(raw)} bytes; each slot is {SONG_SIZE} bytes\")
761:     return outdir
762: 
763: 
764: def restore_songs(prj: Path, folder: Path, new_name: str | None = None) -> None:
765:     if not folder.is_dir():
766:         die(f\"not a directory: {folder}\")
767:     bins = sorted(
768:         p
769:         for p in folder.iterdir()
770:         if p.is_file() and p.suffix.lower() == \".bin\" and not p.name.startswith(\"99_\")
771:     )
772:     if not bins:
773:         die(f\"no .bin files in {folder}\")
774: 
775:     by_slot: dict[int, Path] = {}
776:     for p in bins:
777:         idx = slot_index_from_name(p)
778:         if idx is None:
779:             die(f\"song file name must start with NN_ slot number (00–15): {p.name}\")
780:         if idx in by_slot:
781:             die(f\"duplicate slot {idx:02d}: {by_slot[idx].name} and {p.name}\")
782:         by_slot[idx] = p
783: 
784:     manifest, payload, members = read_project(prj)
785:     pname = payload_name(manifest)
786:     head, raw = unpack_project(payload)
787:     start = song_table_off(raw)
788:     patched = bytearray(raw)
789:     old_len = len(payload)
790:     empty = empty_song_template(raw, start)
791: 
792:     for idx in range(SONG_SLOTS):
793:         path = by_slot.get(idx)
794:         off = start + idx * SONG_SIZE
795:         if path is None:
796:             patched[off : off + SONG_SIZE] = empty
797:             print(f\"  slot {idx:02d}  ←  (empty)\")
798:             continue
799:         blob = path.read_bytes()
800:         if len(blob) == 0:
801:             patched[off : off + SONG_SIZE] = empty
802:             print(f\"  slot {idx:02d}  ←  {path.name}  (empty file)\")
803:             continue
804:         if len(blob) != SONG_SIZE:
805:             die(
806:                 f\"{path.name} is {len(blob)} bytes, expected {SONG_SIZE}. \"
807:                 \"Re-dump songs with this script (older dumps were LZ4 fragments \"
808:                 \"and will not import).\"
809:             )
810:         patched[off : off + SONG_SIZE] = blob
811:         print(f\"  slot {idx:02d}  ←  {path.name}  {song_name(blob)}\")
812: 
813:     new_raw = bytes(patched)
814:     out_pname: str | None = None
815:     if new_name is not None:
816:         new_raw, out_pname, old_internal = patch_project_name(new_raw, new_name)
817:         print(f\"name   {old_internal!r} → {out_pname!r}\")
818: 
819:     new_payload = pack_project(head, new_raw)
820:     crc = struct.unpack_from(\">I\", new_payload, len(new_payload) - 12)[0]
821:     size = struct.unpack_from(\">I\", new_payload, len(new_payload) - 8)[0]
822:     if len(new_payload) != old_len:
823:         print(f\"payload length {old_len} → {len(new_payload)}\")
824:     print(f\"footer size={size}  crc32={crc:08x}  uncompressed={len(new_raw)}\")
825: 
826:     bak = prj.with_suffix(prj.suffix + \".bak\")
827:     shutil.copy2(prj, bak)
828:     write_project(prj, members, pname, new_payload, out_pname)
829:     print(f\"backup {bak}\")
830:     print(f\"wrote  {prj}\")
831:     missing = [i for i in range(SONG_SLOTS) if i not in by_slot]
832:     if missing:
833:         print(
834:             f\"cleared {len(missing)} missing slot\"
835:             f\"{'s' if len(missing) != 1 else ''} to empty\"
836:         )
837: 
838: 
839: def main(argv: list[str]) -> None:
840:     if not argv or argv[0] in (\"-h\", \"--help\"):
841:         print(__doc__.strip(), file=sys.stderr)
842:         raise SystemExit(0 if argv and argv[0] in (\"-h\", \"--help\") else 2)
843:     prj = Path(argv[0]).expanduser().resolve()
844:     if not prj.is_file():
845:         die(f\"not a file: {prj}\")
846:     if len(argv) == 1:
847:         dump_songs(prj)
848:     elif len(argv) == 2:
849:         restore_songs(prj, Path(argv[1]).expanduser().resolve())
850:     elif len(argv) == 3:
851:         restore_songs(prj, Path(argv[1]).expanduser().resolve(), argv[2])
852:     else:
853:         die(\"usage: python ./dt_song_mgmt.py project.dt2prj [songs_folder [new_project_name]]\")
854: 
855: 
856: if __name__ == \"__main__\":
857:     main(sys.argv[1:])"