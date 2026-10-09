"""Copies a game model's attachment points and physics proxies into a custom model.

Weapons are held, sheathed, picked up and hit through helper nodes (slt_0, slt_1, pck_ir_*, plc_01,
sharpening_center) and $physics_proxy capsules that hang under the model's root node. A model compiled
from Blender has none of them, so the game cannot attach it to Henry's hand or scabbard.
"""
from __future__ import annotations

import struct

CHUNK_MESH = 0x1000
CHUNK_HELPER = 0x1001
CHUNK_NODE = 0x100B
CHUNK_MTLNAME = 0x1014
CHUNK_PHYSICS = 0x1018
NODE_NAME = 64
NODE_REFS = 64  # object, parent, children, material ids follow the name
MESH_PHYSICS_IDS = 92  # MESH_CHUNK_DESC_0801.nPhysicsDataChunkId[4]


def _chunks(data: bytes) -> list[list]:
    if len(data) < 16:
        raise ValueError("Not a KCD2 geometry file")
    sig, version, count, table = struct.unpack_from("<4sIII", data, 0)
    if sig != b"CrCh" or version != 0x746:
        raise ValueError("Not a KCD2 geometry file")
    result = []
    for i in range(count):
        ctype, cver, cid, size, offset = struct.unpack_from("<HHIII", data, table + i * 16)
        result.append([ctype, cver, cid, bytearray(data[offset:offset + size])])
    return result


def _node(chunk) -> tuple[str, int, int, int, int]:
    body = chunk[3]
    name = bytes(body[:NODE_NAME]).split(b"\0", 1)[0].decode("latin-1")
    return (name, *struct.unpack_from("<iiii", body, NODE_REFS))


def _write(chunks: list[list]) -> bytes:
    table = 16
    offset = table + len(chunks) * 16
    header = struct.pack("<4sIII", b"CrCh", 0x746, len(chunks), table)
    entries, blobs = [], []
    for ctype, cver, cid, body in chunks:
        pad = (-offset) % 4
        blobs.append(b"\0" * pad + bytes(body))
        offset += pad
        entries.append(struct.pack("<HHIII", ctype, cver, cid, len(body), offset))
        offset += len(body)
    return header + b"".join(entries) + b"".join(blobs)


def node_names(data: bytes) -> set[str]:
    return {_node(c)[0] for c in _chunks(data) if c[0] == CHUNK_NODE}


def graft_attachments(target: bytes, source: bytes) -> tuple[bytes, list[str]]:
    """target with the source's helper and proxy nodes added under its root; returns (file, added names)."""
    chunks = _chunks(target)
    source_chunks = _chunks(source)
    by_id = {c[2]: c for c in source_chunks}
    roots = [c for c in chunks if c[0] == CHUNK_NODE and _node(c)[2] == -1]
    source_roots = [c for c in source_chunks if c[0] == CHUNK_NODE and _node(c)[2] == -1]
    if not roots or not source_roots:
        return target, []
    root, source_root = roots[0], source_roots[0]
    material = next((c[2] for c in chunks if c[0] == CHUNK_MTLNAME), 0)
    present = {_node(c)[0] for c in chunks if c[0] == CHUNK_NODE}
    next_id = max(c[2] for c in chunks) + 1
    added: list[str] = []
    for chunk in source_chunks:
        if chunk[0] != CHUNK_NODE:
            continue
        name, obj_id, parent, _children, node_material = _node(chunk)
        obj = by_id.get(obj_id)
        if parent != source_root[2] or name in present or obj is None:
            continue
        if obj[0] == CHUNK_HELPER:
            new_obj = [obj[0], obj[1], next_id, bytearray(obj[3])]
            next_id += 1
            chunks.append(new_obj)
        elif obj[0] == CHUNK_MESH and name.startswith("$physics_proxy"):
            mesh = bytearray(obj[3])
            physics = list(struct.unpack_from("<4i", mesh, MESH_PHYSICS_IDS))
            for slot, physics_id in enumerate(physics):
                data_chunk = by_id.get(physics_id) if physics_id else None
                if data_chunk is None or data_chunk[0] != CHUNK_PHYSICS:
                    physics[slot] = 0
                    continue
                chunks.append([data_chunk[0], data_chunk[1], next_id, bytearray(data_chunk[3])])
                physics[slot] = next_id
                next_id += 1
            struct.pack_into("<4i", mesh, MESH_PHYSICS_IDS, *physics)
            new_obj = [obj[0], obj[1], next_id, mesh]
            next_id += 1
            chunks.append(new_obj)
        else:
            continue
        node = bytearray(chunk[3])
        struct.pack_into("<iiii", node, NODE_REFS, new_obj[2], root[2], 0, material if node_material else 0)
        chunks.append([chunk[0], chunk[1], next_id, node])
        next_id += 1
        added.append(name)
    if not added:
        return target, []
    name, obj_id, parent, children, root_material = _node(root)
    struct.pack_into("<iiii", root[3], NODE_REFS, obj_id, parent, children + len(added), root_material)
    return _write(chunks), added


NODE_TM = 84  # name, four ids, four bytes of flags, then the 4x4 transform with translation in centimetres


def _node_body(name: str, obj: int, parent: int, tm: list[float]) -> bytearray:
    body = bytearray(name.encode("latin-1")[:63].ljust(NODE_NAME, b"\0"))
    body += struct.pack("<iiii", obj, parent, 0, 0) + bytes(4)
    body += struct.pack("<16f", *tm) + bytes(40) + struct.pack("<iiii", -1, -1, -1, 0)
    return body


def _cry_tm(points: list[float]) -> list[float]:
    """A row-major Blender matrix in metres -> CryEngine's transposed node matrix in centimetres."""
    rows = [points[i * 4:i * 4 + 4] for i in range(4)]
    tm = [rows[c][r] for r in range(4) for c in range(4)]
    tm[12:15] = [v * 100.0 for v in tm[12:15]]
    return tm


def apply_points(data: bytes, points: dict[str, list[float]]) -> tuple[bytes, list[str]]:
    """Moves helper nodes to the positions placed in Blender and adds the ones the model lacks."""
    if not points:
        return data, []
    chunks = _chunks(data)
    roots = [c for c in chunks if c[0] == CHUNK_NODE and _node(c)[2] == -1]
    if not roots:
        return data, []
    root = roots[0]
    by_name = {_node(c)[0].lower(): c for c in chunks if c[0] == CHUNK_NODE}
    next_id = max(c[2] for c in chunks) + 1
    changed, added = [], 0
    for name, matrix in sorted(points.items()):
        tm = _cry_tm(matrix)
        node = by_name.get(name.lower())
        if node is not None:
            struct.pack_into("<16f", node[3], NODE_TM, *tm)
        else:
            chunks.append([CHUNK_HELPER, 0x744, next_id, bytearray(16)])
            chunks.append([CHUNK_NODE, 0x824, next_id + 1, _node_body(name, next_id, root[2], tm)])
            next_id += 2
            added += 1
        changed.append(name)
    if added:
        name, obj_id, parent, children, material = _node(root)
        struct.pack_into("<iiii", root[3], NODE_REFS, obj_id, parent, children + added, material)
    return _write(chunks), changed
