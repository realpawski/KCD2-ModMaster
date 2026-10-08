"""Regression tests for the DDS and semantic conversion faults found in KCD2."""
import importlib.util
from pathlib import Path
import struct
import numpy as np
import pytest

ADDON = Path(__file__).resolve().parents[1]/'src/blender/addon/KCD2_ModMaster_Bridge'


def module(name):
    spec = importlib.util.spec_from_file_location(name, ADDON/(name+'.py'))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


decoder = module('normal_decoder')
adapter = module('material_adapter')


def block(a, b, indices):
    bits = sum(int(v) << (3*i) for i, v in enumerate(indices))
    return bytes((a & 255, b & 255))+bits.to_bytes(6, 'little')


def dds(tmp_path, fmt, payload, width=4, height=4):
    header = bytearray(148)
    header[:4] = b'DDS '
    struct.pack_into('<I', header, 4, 124)
    struct.pack_into('<II', header, 12, height, width)
    header[84:88] = b'DX10'
    struct.pack_into('<I', header, 128, fmt)
    p = tmp_path/'fixture.dds';p.write_bytes(header+payload)
    return p


def test_signed_endpoints_and_interpolation():
    b = block(127, -127, list(range(8))*2)
    result = decoder.decode_bc4_blocks(np.frombuffer(b,np.uint8), signed=True)[0]
    np.testing.assert_allclose(result[:8], [1,-1,5/7,3/7,1/7,-1/7,-3/7,-5/7], atol=1e-6)


def test_signed_six_entry_mode_and_minus_128():
    b = block(-128, 127, list(range(8))*2)
    result = decoder.decode_bc4_blocks(np.frombuffer(b,np.uint8), signed=True)[0]
    np.testing.assert_allclose(result[:8], [-1,1,-.6,-.2,.2,.6,-1,1], atol=1e-6)


def test_actual_kcd2_swizzle_signed_range_and_z(tmp_path):
    path = dds(tmp_path, 84, block(0,0,[0]*16)+block(64,64,[0]*16))
    xyz = decoder.decode_normal(path)*2-1
    np.testing.assert_allclose(xyz[:,:,0],64/127,atol=1e-6)
    np.testing.assert_allclose(xyz[:,:,1],0,atol=1e-6)
    np.testing.assert_allclose(np.linalg.norm(xyz,axis=-1),1,atol=1e-6)
    assert xyz[:,:,2].min()>.8


def test_gloss_bc4_is_scalar_not_normal_alpha(tmp_path):
    path = dds(tmp_path,80,block(255,0,[0,1]*8))
    gloss,fmt=decoder.read_bc_dds(path)
    assert fmt==80 and gloss.shape==(4,4,1)
    np.testing.assert_array_equal(gloss[0,:,0],[1,0,1,0])


def test_truncated_top_mip_fails_instead_of_falling_back(tmp_path):
    with pytest.raises(ValueError,match='Incomplete'):
        decoder.decode_normal(dds(tmp_path,84,b'\0'*8))


def test_joint_color_conversion_distinguishes_wood_and_metal():
    base,metal=adapter.spec_gloss_to_principled(np.array([[.3,.15,.05],[0,0,0]]),np.array([[.04,.04,.04],[.7,.65,.6]]))
    assert metal[0]<1e-5 and metal[1]>.95
    assert np.isfinite(base).all() and ((base>=0)&(base<=1)).all()


def test_shader_semantics_prevent_metallic_tissue():
    assert adapter.is_dielectric_shader({'shader':'Hair'})
    assert adapter.is_dielectric_shader({'shader':'Eye'})
    assert adapter.is_dielectric_shader({'shader':'Illum','source_attributes':{'StringGenMask':'%NORMAL_MAP%SUBSURFACE_SCATTERING'}})
    assert not adapter.is_dielectric_shader({'shader':'Illum','name':'poleaxe'})


def test_source_ior_is_not_a_principled_socket():
    result=adapter.preview_parameters({'public_params':{'IOR':'1000'}})
    assert result['IOR']==1.5
    with pytest.raises(ValueError,match='Shininess'):
        adapter.preview_parameters({'shininess':1000})


def test_hair_shader_smoothness_is_not_illum_gloss():
    assert adapter.preview_parameters({'shader':'Hair','shininess':255})['Roughness']==pytest.approx(.1)
    assert adapter.preview_parameters({'shader':'Eye','public_params':{'CorneaSmoothness':'.898'}})['Roughness']==pytest.approx(.102)


def test_mtl_preserves_alpha_and_original_parameters():
    from materials.mtl_parser import parse_mtl_xml
    m=parse_mtl_xml('<Material Name="cards" Shader="Hair" AlphaTest="0.59" Opacity="0.75" MtlFlags="526466"><PublicParams IOR="1000"/></Material>').submaterials[0]
    assert m.alpha_test==.59 and m.opacity==.75
    assert m.source_attributes['MtlFlags']=='526466' and m.public_params['IOR']=='1000'


def test_cached_normal_still_stages_attached_gloss(tmp_path,monkeypatch):
    from types import SimpleNamespace
    from materials import mtl_parser
    normal=tmp_path/'test_ddna.dds';normal.write_bytes(b'cached RGB remains intact')
    header=bytearray(148);header[:4]=b'DDS ';header[84:88]=b'DX10'
    struct.pack_into('<II',header,12,8,8);struct.pack_into('<I',header,128,80)
    content={'test_ddna.dds.a':bytes(header[4:])+b'L'*8,'test_ddna.dds.1a':b'H'*32}
    class Pak:
        def __init__(self,*args): pass
        def __enter__(self): return self
        def __exit__(self,*args): pass
        def read(self,path): return content[path]
    monkeypatch.setattr(mtl_parser,'PakArchive',Pak)
    row=lambda name:SimpleNamespace(filename=name,vpath=name,archive_path='archive')
    class Index:
        def find_by_vpath(self,*args,**kwargs):return [row('test_ddna.dds')]
        def texture_parts(self,*args,**kwargs):return [row(k) for k in content]
    m=mtl_parser.parse_mtl_xml('<Material><Textures><Texture Map="Bumpmap" File="test_ddna.tif"/></Textures></Material>')
    assert mtl_parser.resolve_and_stage_textures(m,Index(),tmp_path)==(1,1,[])
    gloss=tmp_path/m.submaterials[0].resolved_textures['Gloss']
    assert gloss.read_bytes()==bytes(header)+b'H'*32+b'L'*8
    assert normal.read_bytes()==b'cached RGB remains intact'


def test_rebuild_reads_refreshed_material_metadata(tmp_path):
    import json
    metadata=module('metadata')
    folder=tmp_path/'metadata';folder.mkdir()
    disk={'asset_id':'animal','materials':[{'alpha_test':.59}]}
    (folder/'.modmaster_asset.json').write_text(json.dumps(disk))
    scene={'modmaster_meta_json':json.dumps({'asset_id':'animal','workspace_dir':str(tmp_path),'materials':[]})}
    assert metadata.get_active_asset_metadata(scene)['materials']==disk['materials']


def test_extract_cgf_material_name():
    from preview.converter import extract_cgf_material_name
    header = struct.pack("<4sIII", b"CrCh", 0x746, 1, 16)
    name_bytes = b"Objects/characters/animals/horse/horse_saddle_pickable_001a.mtl\x00"
    chunk_entry = struct.pack("<IIII", 0x1014, 1, len(name_bytes), 32)
    cgf_data = header + chunk_entry + name_bytes
    extracted = extract_cgf_material_name(cgf_data)
    assert extracted == "Objects/characters/animals/horse/horse_saddle_pickable_001a"


def test_generic_dielectric_roughness_fallback():
    from materials.semantics import classify_kcd2_material
    desc = classify_kcd2_material(
        name="custom_wood_or_stone",
        shader="Illum",
        surface_type="mat_wood",
        shininess=255.0,
        specular_color=(0.23, 0.23, 0.23),
    )
    assert desc.roughness >= 0.70
    assert desc.metallic == 0.0
    assert desc.specular_f0[0] == pytest.approx(0.04, abs=0.01)


def test_uv_diagnostic_formatting():
    from materials.semantics import format_uv_diagnostic
    report = format_uv_diagnostic(
        asset="horse_saddle_001a.cgf",
        primitive=0,
        material="saddle",
        texture="horse_seat_diff.dds",
        texture_semantic="DIFFUSE",
        available_uv_sets="TEXCOORD_0",
        selected_uv_set="TEXCOORD_0",
        uv_range="[0.003, 1.000]",
        wrap_mode="REPEAT",
        texture_dimensions="4096x4096",
    )
    assert "[UV DIAGNOSTIC]" in report
    assert "horse_saddle_001a.cgf" in report
    assert "TEXCOORD_0" in report

