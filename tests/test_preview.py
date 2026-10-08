"""Tests for 3D preview system, LODs, cache, and GLB loading."""
from pathlib import Path
import numpy as np
import pytest

from preview.cache import PreviewCache, PreviewMetadata, compute_asset_hash
from preview.lods import extract_base_stem, find_lod_family, LodFamily
from preview.gltf_loader import calculate_smooth_normals
from preview.converter import extract_cgf_material_name, is_clip_volume_material
from database.index import AssetRow


def test_is_clip_volume_material_detects_real_clipvolume_marker():
    assert is_clip_volume_material("objects/intermediates/clipvolumes/clipvolumes")
    assert is_clip_volume_material("Objects/Intermediates/ClipVolumes/ClipVolumes")
    assert not is_clip_volume_material(None)
    assert not is_clip_volume_material("")
    assert not is_clip_volume_material("objects/manmade/structures/living/houses/house_1s_4r_d_mirrored")


def test_extract_cgf_material_name_handles_non_cgf_bytes():
    assert extract_cgf_material_name(b"not a cgf file") is None
    assert extract_cgf_material_name(b"") is None
    assert extract_cgf_material_name(b"CrCh") is None  # header present but truncated


def test_extract_base_stem():
    base, lod = extract_base_stem("polearm_pile_a.cgf")
    assert base == "polearm_pile_a"
    assert lod == 0

    base, lod = extract_base_stem("polearm_pile_a_lod1.cgf")
    assert base == "polearm_pile_a"
    assert lod == 1

    base, lod = extract_base_stem("polearm_pile_a_lod2.cgf")
    assert base == "polearm_pile_a"
    assert lod == 2

    base, lod = extract_base_stem("helmet_iron_lod3.skin")
    assert base == "helmet_iron"
    assert lod == 3


def test_preview_cache(tmp_path: Path):
    cache = PreviewCache(tmp_path)
    hash_key = compute_asset_hash("Objects/weapons/sword.cgf", "Objects-part0.pak", 12345)
    assert not cache.has_preview(hash_key)

    dummy_glb = tmp_path / "dummy.glb"
    dummy_glb.write_bytes(b"glTF_dummy_content")

    stored_glb = cache.store_glb(hash_key, dummy_glb)
    assert stored_glb.is_file()

    meta = PreviewMetadata(
        vpath="Objects/weapons/sword.cgf",
        filename="sword.cgf",
        archive_name="Objects-part0.pak",
        file_size=12345,
        triangles=500,
        vertices=300,
        dim_x=0.15,
        dim_y=1.10,
        dim_z=0.08,
        bounds_min=[-0.07, 0.0, -0.04],
        bounds_max=[0.08, 1.10, 0.04],
        lods=[{"lod": 0, "label": "LOD 0"}],
        created_at=1234567.0,
    )
    cache.save_metadata(hash_key, meta)

    assert cache.has_preview(hash_key)
    loaded_meta = cache.get_metadata(hash_key)
    assert loaded_meta is not None
    assert loaded_meta.triangles == 500
    assert loaded_meta.dim_y == 1.10


def test_calculate_smooth_normals():
    pos = np.array([
        [0.0, 0.0, 0.0],
        [1.0, 0.0, 0.0],
        [1.0, 1.0, 0.0],
        [0.0, 1.0, 0.0],
    ], dtype=np.float32)
    indices = np.array([0, 1, 2, 0, 2, 3], dtype=np.uint32)

    normals = calculate_smooth_normals(pos, indices)
    assert normals.shape == (4, 3)
    for norm in normals:
        assert norm[2] > 0.99


def test_viewport_geometry_lifecycle():
    from PySide6.QtWidgets import QApplication
    from preview.gltf_loader import MeshGeometry
    from ui.preview.viewport_3d import ModelViewport3D

    app = QApplication.instance() or QApplication([])

    vp = ModelViewport3D()
    vp.resize(400, 300)

    positions = np.array([
        [-0.5, 0.0, -0.5],
        [0.5, 0.0, -0.5],
        [0.5, 1.0, -0.5],
        [-0.5, 1.0, -0.5],
    ], dtype=np.float32)
    normals = np.zeros_like(positions)
    normals[:, 2] = 1.0
    indices = np.array([0, 1, 2, 0, 2, 3], dtype=np.uint32)

    geom = MeshGeometry(
        positions=positions,
        normals=normals,
        indices=indices,
        uvs=None,
        bounds_min=np.array([-0.5, 0.0, -0.5]),
        bounds_max=np.array([0.5, 1.0, 0.5]),
        center=np.array([0.0, 0.5, 0.0]),
        dim=np.array([1.0, 1.0, 1.0]),
        triangles=2,
        vertices=4,
    )

    received_dims = []
    vp.dimensions_updated.connect(lambda dx, dy, dz, t, v: received_dims.append((dx, dy, dz, t, v)))

    vp.set_geometry(geom)
    assert len(received_dims) == 1
    assert received_dims[0] == (1.0, 1.0, 1.0, 2, 4)

    vp.set_mode(0)
    assert vp.mode == 0
    vp.set_mode(1)
    assert vp.mode == 1
    vp.set_mode(2)
    assert vp.mode == 2
    vp.set_mode(3)
    assert vp.mode == 3

    vp.toggle_grid(False)
    assert not vp.show_grid
    vp.toggle_ground(False)
    assert not vp.show_ground

    vp.close()


def test_combine_cryengine_dds():
    from preview.converter import combine_cryengine_dds

    fake_header = bytearray(148)
    fake_header[84:88] = b"DX10"
    fake_tail = b"TAIL_MIPS" * 70  # 630 bytes
    base_data = bytes(fake_header + fake_tail)

    part1_data = b"MIP_1_DATA_" * 100
    part2_data = b"MIP_2_DATA_" * 200

    parts = [(1, part1_data), (2, part2_data)]

    combined = combine_cryengine_dds(base_data, parts)

    assert combined[:148] == fake_header
    assert combined[148 : 148 + len(part2_data)] == part2_data
    offset_p1 = 148 + len(part2_data)
    assert combined[offset_p1 : offset_p1 + len(part1_data)] == part1_data
    offset_tail = offset_p1 + len(part1_data)
    assert combined[offset_tail:] == fake_tail
    assert len(combined) == 148 + len(part2_data) + len(part1_data) + len(fake_tail)


def test_preview_cache_version_invalidation():
    from preview.cache import compute_asset_hash, CACHE_VERSION

    h1 = compute_asset_hash("Objects/characters/animals/boar/boar.cgf", "Characters.pak", 888)
    assert h1.isalnum()
    assert len(h1) == 16
    assert CACHE_VERSION >= 2

