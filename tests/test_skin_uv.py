import json
import struct

from preview.skin_uv import _read_glb, _write_glb, inject_skin_uvs, read_texcoords

UVS = [(0.0, 0.25), (0.5, 0.75), (1.0, 1.0)]


def fake_skin(uvs=UVS) -> bytes:
    payload = struct.pack("<iiii", 0, 2, len(uvs), 8) + b"\0" * 8 + b"".join(struct.pack("<ff", *uv) for uv in uvs)
    table = 16
    header = b"CrCh" + struct.pack("<III", 0x746, 1, table)
    entry = struct.pack("<HHIII", 0x1016, 0x800, 1, len(payload), table + 16)
    return header + entry + payload


def fake_glb(path, count=3):
    positions = b"".join(struct.pack("<fff", i, 0, 0) for i in range(count))
    doc = {"asset": {"version": "2.0"}, "buffers": [{"byteLength": len(positions)}],
           "bufferViews": [{"buffer": 0, "byteOffset": 0, "byteLength": len(positions)}],
           "accessors": [{"bufferView": 0, "componentType": 5126, "count": count, "type": "VEC3"}],
           "meshes": [{"primitives": [{"attributes": {"POSITION": 0}}, {"attributes": {"POSITION": 0}}]}]}
    _write_glb(path, doc, positions)


def test_reads_float_texcoords():
    assert read_texcoords(fake_skin()) == UVS


def test_adds_uvs_to_every_primitive(tmp_path):
    glb, skin = tmp_path / "boar.glb", tmp_path / "boar.skin"
    fake_glb(glb)
    skin.write_bytes(fake_skin())
    assert inject_skin_uvs(glb, skin)
    doc, binary = _read_glb(glb)
    accessor = doc["meshes"][0]["primitives"][1]["attributes"]["TEXCOORD_0"]
    view = doc["bufferViews"][doc["accessors"][accessor]["bufferView"]]
    data = binary[view["byteOffset"]:view["byteOffset"] + view["byteLength"]]
    assert [struct.unpack_from("<ff", data, i * 8) for i in range(3)] == UVS
    assert doc["buffers"][0]["byteLength"] == len(binary)
    json.dumps(doc)


def test_leaves_mismatched_vertex_counts_alone(tmp_path):
    glb, skin = tmp_path / "boar.glb", tmp_path / "boar.skin"
    fake_glb(glb, count=5)
    skin.write_bytes(fake_skin())
    assert not inject_skin_uvs(glb, skin)
