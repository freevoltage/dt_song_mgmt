"""Project read/write/pack/unpack."""
from __future__ import annotations

import json
import struct
import zipfile
from pathlib import Path

from .constants import MAGIC_HEAD, MAGIC_TAIL, PAYLOAD_HEAD_LEN, PROJECT_NAME_LEN, NAME_CHAR
from .format import compress_raw, decompress_blocks, set_uncompressed_size, unwrap_payload, wrap_payload


def die(msg: str, code: int = 1) -> None:
    import sys
    print(f"dt_song_mgmt: {msg}", file=sys.stderr)
    raise SystemExit(code)


def payload_name(manifest: dict) -> str:
    name = manifest.get("Payload")
    if not name:
        die("manifest.json has no Payload")
    return name


def read_project(prj: Path) -> tuple[dict, bytes, list[tuple[zipfile.ZipInfo, bytes]]]:
    if not zipfile.is_zipfile(prj):
        die(f"not a zip/.dt2prj: {prj}")
    members: list[tuple[zipfile.ZipInfo, bytes]] = []
    with zipfile.ZipFile(prj, "r") as zf:
        try:
            manifest = json.loads(zf.read("manifest.json"))
        except KeyError:
            die("manifest.json missing from archive")
        pname = payload_name(manifest)
        try:
            payload = zf.read(pname)
        except KeyError:
            die(f"payload {pname!r} missing from archive")
        for info in zf.infolist():
            members.append((info, zf.read(info.filename)))
    return manifest, payload, members


def write_project(prj: Path, members: list[tuple[zipfile.ZipInfo, bytes]], pname: str, payload: bytes, new_pname: str | None = None) -> None:
    out_name = new_pname or pname
    tmp = prj.with_suffix(prj.suffix + ".tmp")
    with zipfile.ZipFile(tmp, "w") as zf:
        for info, data in members:
            filename = info.filename
            blob = data
            if filename == "manifest.json" and new_pname:
                man = json.loads(data)
                man["Payload"] = new_pname
                blob = (json.dumps(man, indent=2) + "\n").encode("utf-8")
            elif filename == pname:
                filename = out_name
                blob = payload
            out = zipfile.ZipInfo(filename=filename, date_time=info.date_time)
            out.compress_type = info.compress_type
            out.external_attr = info.external_attr
            zf.writestr(out, blob)
    tmp.replace(prj)


def clean_project_name(name: str) -> str:
    out = []
    for ch in name.strip():
        if ch.islower() and ch.upper() in NAME_CHAR:
            out.append(ch.upper())
        elif ch in NAME_CHAR:
            out.append(ch)
        elif ch.isspace():
            out.append("~")
    cleaned = "".join(out).strip("~") or "PROJECT"
    if len(cleaned) > PROJECT_NAME_LEN:
        print(f"note: project name truncated to {PROJECT_NAME_LEN} characters")
        cleaned = cleaned[:PROJECT_NAME_LEN]
    return cleaned


def encode_project_name_field(name: str) -> bytes:
    raw = clean_project_name(name).encode("latin-1")
    if len(raw) >= PROJECT_NAME_LEN:
        return raw[:PROJECT_NAME_LEN]
    return raw + b"\x00" + b"~" * (PROJECT_NAME_LEN - len(raw) - 1)


def read_project_name_field(raw: bytes) -> tuple[int, str]:
    i = raw.find(MAGIC_HEAD)
    if i < 0:
        die("no beefbace marker in project — cannot locate project name")
    off = i + 4 + 4
    if off + PROJECT_NAME_LEN > len(raw):
        die("project too short for project name field")
    field = raw[off : off + PROJECT_NAME_LEN]
    n = field.find(b"\x00")
    name = field if n < 0 else field[:n]
    return off, name.decode("latin-1").rstrip("~")


def patch_project_name(raw: bytes, new_name: str) -> tuple[bytes, str, str]:
    off, old = read_project_name_field(raw)
    cleaned = clean_project_name(new_name)
    field = encode_project_name_field(cleaned)
    patched = bytearray(raw)
    patched[off : off + PROJECT_NAME_LEN] = field
    return bytes(patched), cleaned, old


def unpack_project(payload: bytes) -> tuple[bytes, bytes]:
    head, blocks = unwrap_payload(payload)
    raw = decompress_blocks(blocks)
    stored = struct.unpack_from(">I", head, 25)[0]
    if stored != len(raw):
        print(f"note: header uncompressed size {stored} != decoded {len(raw)}")
    return head, raw


def pack_project(head: bytes, raw: bytes) -> bytes:
    head = set_uncompressed_size(head, len(raw))
    return wrap_payload(head, compress_raw(raw))
