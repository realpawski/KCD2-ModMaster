"""Adds the UVs of a CryEngine .skin to a glTF exported from it; the converter leaves them out."""
from __future__ import annotations

import json
import struct
from pathlib import Path

STREAM_TEXCOORDS = 2
CHUNK_DATASTREAM = 0x1016


def _half(raw: int) -> float:
    return struct.unpack("<e", struct.pack("<H", raw))[0]


def read_texcoords(data: bytes) -> list[tuple[float, float]] | None:
    if data[:4] != b"CrCh":
        return None
    _version, count, table = struct.unpack_from("<III", data, 4)
    for i in range(count):
        kind, _ver, _cid, size, offset = struct.unpack_from("<HHIII", data, table + i * 16)
        if kind != CHUNK_DATASTREAM or size < 24:
            continue
        _flags, stream, n, elem = struct.unpack_from("<iiii", data, offset)
        if stream != STREAM_TEXCOORDS:
            continue
        base = offset + 24
        if elem == 8:
            return [struct.unpack_from("<ff", data, base + k * 8) for k in range(n)]
        if elem == 4:
            return [(_half(a), _half(b)) for a, b in (struct.unpack_from("<HH", data, base + k * 4) for k in range(n))]
    return None


def _read_glb(path: Path) -> tuple[dict, bytes]:
    data = path.read_bytes()
    json_len = struct.unpack_from("<I", data, 12)[0]
    doc = json.loads(data[20:20 + json_len])
    rest = data[20 + json_len:]
    binary = b""
    if len(rest) >= 8:
        bin_len, kind = struct.unpack_from("<II", rest, 0)
        if kind == 0x004E4942:
            binary = rest[8:8 + bin_len]
    return doc, binary


def _write_glb(path: Path, doc: dict, binary: bytes) -> None:
    text = json.dumps(doc, separators=(",", ":")).encode("utf-8")
    text += b" " * (-len(text) % 4)
    binary += b"\0" * (-len(binary) % 4)
    total = 12 + 8 + len(text) + 8 + len(binary)
    out = struct.pack("<III", 0x46546C67, 2, total)
    out += struct.pack("<II", len(text), 0x4E4F534A) + text
    out += struct.pack("<II", len(binary), 0x004E4942) + binary
    path.write_bytes(out)


def inject_skin_uvs(glb: Path, skin: Path) -> bool:
    """Give every primitive without UVs the .skin texcoords when its vertex count matches."""
    uvs = read_texcoords(Path(skin).read_bytes())
    if not uvs:
        return False
    doc, binary = _read_glb(Path(glb))
    targets = [p for m in doc.get("meshes", []) for p in m.get("primitives", [])
               if "TEXCOORD_0" not in p.get("attributes", {})
               and doc["accessors"][p["attributes"]["POSITION"]]["count"] == len(uvs)]
    if not targets:
        return False
    binary += b"\0" * (-len(binary) % 4)
    offset = len(binary)
    binary += b"".join(struct.pack("<ff", u, v) for u, v in uvs)
    doc.setdefault("bufferViews", []).append(
        {"buffer": 0, "byteOffset": offset, "byteLength": len(uvs) * 8, "target": 34962})
    doc.setdefault("accessors", []).append({
        "bufferView": len(doc["bufferViews"]) - 1, "componentType": 5126, "count": len(uvs), "type": "VEC2",
        "min": [min(u for u, _ in uvs), min(v for _, v in uvs)],
        "max": [max(u for u, _ in uvs), max(v for _, v in uvs)],
    })
    accessor = len(doc["accessors"]) - 1
    for primitive in targets:
        primitive["attributes"]["TEXCOORD_0"] = accessor
    doc["buffers"][0]["byteLength"] = len(binary)
    _write_glb(Path(glb), doc, binary)
    return True
