import struct

from compiler.attachments import (
    CHUNK_HELPER,
    CHUNK_MESH,
    CHUNK_MTLNAME,
    CHUNK_NODE,
    CHUNK_PHYSICS,
    MESH_PHYSICS_IDS,
    _chunks,
    _node,
    _write,
    graft_attachments,
)


def node(name, obj, parent, children=0, material=0, extra=b""):
    body = bytearray(name.encode().ljust(64, b"\0") + struct.pack("<iiii", obj, parent, children, material))
    body += b"\0" * (204 - len(body))
    return body + extra


def mesh(physics_id=0):
    body = bytearray(264)
    struct.pack_into("<i", body, MESH_PHYSICS_IDS, physics_id)
    return body


def game_sword():
    return _write([
        [CHUNK_MTLNAME, 0x802, 64, bytearray(b"sword\0")],
        [CHUNK_MESH, 0x801, 65, mesh()],
        [CHUNK_NODE, 0x824, 66, node("sword_mesh", 65, -1, 3, 64)],
        [CHUNK_HELPER, 0x744, 67, bytearray(16)],
        [CHUNK_NODE, 0x824, 68, node("slt_0", 67, 66)],
        [CHUNK_PHYSICS, 0x800, 75, bytearray(b"capsule-data")],
        [CHUNK_MESH, 0x801, 76, mesh(75)],
        [CHUNK_NODE, 0x824, 77, node("$physics_proxy_Capsule", 76, 66, 0, 64, b"capsule\r\n")],
        [CHUNK_NODE, 0x824, 78, node("not_a_child", 67, 99)],
    ])


def custom_sword():
    return _write([
        [CHUNK_MTLNAME, 0x802, 2, bytearray(b"mine\0")],
        [0x1016, 0x800, 4, bytearray(b"vertices")],
        [CHUNK_MESH, 0x801, 9, mesh()],
        [CHUNK_NODE, 0x824, 10, node("Merged", 9, -1, 0, 2)],
    ])


def test_helpers_and_proxies_hang_under_the_custom_root_with_fresh_ids():
    data, added = graft_attachments(custom_sword(), game_sword())
    assert added == ["slt_0", "$physics_proxy_Capsule"]
    chunks = {c[2]: c for c in _chunks(data)}
    nodes = {_node(c)[0]: _node(c) for c in chunks.values() if c[0] == CHUNK_NODE}
    assert nodes["Merged"][3] == 2  # two children now
    slot = nodes["slt_0"]
    assert slot[2] == 10 and chunks[slot[1]][0] == CHUNK_HELPER and slot[4] == 0
    proxy = nodes["$physics_proxy_Capsule"]
    assert proxy[2] == 10 and proxy[4] == 2  # the custom model's material
    physics_id = struct.unpack_from("<i", chunks[proxy[1]][3], MESH_PHYSICS_IDS)[0]
    assert chunks[physics_id][0] == CHUNK_PHYSICS and bytes(chunks[physics_id][3]) == b"capsule-data"
    assert bytes(chunks[4][3]) == b"vertices"  # the custom geometry is untouched


def test_grafting_twice_adds_nothing_and_foreign_files_are_refused():
    data, _ = graft_attachments(custom_sword(), game_sword())
    again, added = graft_attachments(data, game_sword())
    assert added == [] and again == data
    try:
        graft_attachments(b"not a model", game_sword())
    except ValueError:
        pass
    else:
        raise AssertionError("expected ValueError")
