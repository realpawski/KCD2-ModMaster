import json
import struct
import xml.etree.ElementTree as ET
import zipfile

import pytest

from compiler import compiled_models, cry_compile, item_model_path
from mods.project import ModManager
from runtime_tools.manager import RuntimeManager


def fake_cgf(material="Objects/modmaster/hat/hat", subs=("hat_purple", "body_plain")) -> bytes:
    names = b"".join(s.encode() + b"\0" for s in subs)
    chunk = material.encode().ljust(128, b"\0") + struct.pack("<i", len(subs)) + b"\xff\xff\xff\xff" * len(subs) + names
    table = 16
    data_offset = table + 16
    header = b"CrCh" + struct.pack("<III", 0x746, 1, table)
    entry = struct.pack("<HHIII", 0x1014, 0x802, 1, len(chunk), data_offset)
    return header + entry + chunk


def test_reads_material_library_and_slots():
    cc = cry_compile()
    assert cc.read_cgf_materials(fake_cgf()) == ("Objects/modmaster/hat/hat", ["hat_purple", "body_plain"])
    with pytest.raises(cc.CompileError):
        cc.read_cgf_materials(b"glTF....")


def test_mtl_keeps_slot_order_and_falls_back_to_white(tmp_path):
    cc = cry_compile()
    path = cc.write_mtl(tmp_path / "hat.mtl", [
        {"name": "hat_purple", "textures": {"Diffuse": "Objects/modmaster/hat/textures/hat_purple_diff.dds",
                                             "Bumpmap": "Objects/modmaster/hat/textures/hat_purple_ddna.dds"}},
        {"name": "body & fur", "diffuse": (0.5, 0.25, 0.1)},
    ])
    subs = ET.parse(path).getroot().find("SubMaterials")
    first, second = list(subs)
    assert [first.get("Name"), second.get("Name")] == ["hat_purple", "body & fur"]
    assert first.get("StringGenMask") == "%NORMAL_MAP"
    assert second.find("Textures/Texture").get("File") == cc.WHITE
    assert second.get("Diffuse") == "0.5,0.25,0.1"


def test_finds_rc_from_tools_folder(tmp_path):
    cc = cry_compile()
    rc = tmp_path / "KCD2Mod" / "Tools" / "rc" / "rc.exe"
    rc.parent.mkdir(parents=True)
    rc.write_bytes(b"")
    assert cc.find_rc(tmp_path / "KCD2Mod") == rc
    assert cc.model_paths("hat") == ("Objects/modmaster/hat/hat", "Objects/modmaster/hat/textures")
    assert cc.slug("Boar with Wizard Hat!") == "boar_with_wizard_hat"


def _compiled_asset(workspace, asset_id="wizard_hat"):
    folder = workspace / "Assets" / asset_id
    (folder / "metadata").mkdir(parents=True)
    (folder / "metadata" / ".modmaster_asset.json").write_text(json.dumps(
        {"asset_id": asset_id, "asset_name": "Wizard Hat", "workspace_dir": str(folder)}), encoding="utf-8")
    model = folder / "compiled" / "Objects" / "modmaster" / asset_id / f"{asset_id}.cgf"
    model.parent.mkdir(parents=True)
    model.write_bytes(fake_cgf())
    model.with_suffix(".mtl").write_text("<Material/>", encoding="utf-8")
    (model.parent / "textures").mkdir()
    (model.parent / "textures" / "hat_diff.dds").write_bytes(b"DDS ")
    return folder


@pytest.fixture
def manager(tmp_path):
    game = tmp_path / "game"
    (game / "Data").mkdir(parents=True)
    (game / "Bin").mkdir()
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    return RuntimeManager(game, workspace)


def test_compiled_asset_is_packed_and_spawnable(manager):
    folder = _compiled_asset(manager.workspace)
    assert compiled_models(folder) == ["Objects/modmaster/wizard_hat/wizard_hat.cgf"]
    assert item_model_path(compiled_models(folder)[0]) == "modmaster/wizard_hat/wizard_hat.cgf"
    mods = ModManager(manager.workspace)
    project = mods.create_mod("Hat Mod", "hat_mod")
    project.assign_asset("wizard_hat")
    built = manager.build_project(project)
    with zipfile.ZipFile(built / "Data" / "hat_mod.pak") as z:
        names = set(z.namelist())
    assert {"Objects/modmaster/wizard_hat/wizard_hat.cgf", "Objects/modmaster/wizard_hat/wizard_hat.mtl",
            "Objects/modmaster/wizard_hat/textures/hat_diff.dds"} <= names
    entry = json.loads((built / "modmaster_assets.json").read_text(encoding="utf-8"))
    prop = entry["assets"][0]
    assert prop["spawn_type"] == "static_prop" and prop["name"] == "Wizard Hat"
    assert prop["model_path"] == "Objects/modmaster/wizard_hat/wizard_hat.cgf"


def test_uncompiled_asset_blocks_build_with_a_clear_message(manager):
    folder = manager.workspace / "Assets" / "boar_hat"
    (folder / "metadata").mkdir(parents=True)
    (folder / "metadata" / ".modmaster_asset.json").write_text(json.dumps(
        {"asset_id": "boar_hat", "asset_name": "Boar with hat", "workspace_dir": str(folder)}), encoding="utf-8")
    project = ModManager(manager.workspace).create_mod("Boar", "boar_mod")
    project.assign_asset("boar_hat")
    with pytest.raises(ValueError, match="Boar with hat has no compiled model yet"):
        manager.build_project(project)


def fake_skin_with_bones(bones):
    record = b""
    for name, rows in bones.items():
        bone = bytearray(584)
        bone[296:296 + 48] = struct.pack("<12f", *rows)
        bone[344:344 + len(name)] = name.encode()
        record += bytes(bone)
    table = 16
    return b"CrCh" + struct.pack("<III", 0x746, 1, table) + struct.pack("<HHIII", 0x2000, 0x800, 1, len(record), 32) + record


def test_reads_game_bone_matrices():
    root = [1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1, 0]
    head = [0, 0, 1, 0, 0.844, 0.537, 0, 0.542, -0.537, 0.844, 0, 0.577]
    bones = cry_compile().read_bone_matrices(fake_skin_with_bones({"Animal_Pig": root, "Head": head}))
    assert list(bones) == ["Animal_Pig", "Head"]
    assert bones["Head"][7] == pytest.approx(0.542) and bones["Animal_Pig"] == root


def test_character_definition_points_at_game_skeleton(tmp_path):
    cc = cry_compile()
    path = cc.write_cdf(tmp_path / "boar.cdf", "objects/characters/animals/boar/skeleton_pig_01.chr",
                        "Objects/modmaster/boar/boar.skin", "Objects/modmaster/boar/boar.mtl")
    root = ET.parse(path).getroot()
    assert root.find("Model").get("File").endswith("skeleton_pig_01.chr")
    attachment = root.find("AttachmentList/Attachment")
    assert attachment.get("Type") == "CA_SKIN" and attachment.get("Binding").endswith("boar.skin")


def test_rigged_asset_is_packed_as_animated_character(manager):
    folder = manager.workspace / "Assets" / "pig"
    (folder / "metadata").mkdir(parents=True)
    (folder / "metadata" / ".modmaster_asset.json").write_text(json.dumps(
        {"asset_id": "pig", "asset_name": "Pig", "workspace_dir": str(folder)}), encoding="utf-8")
    base = folder / "compiled" / "Objects" / "modmaster" / "pig"
    base.mkdir(parents=True)
    (base / "pig.skin").write_bytes(b"CrCh")
    cry_compile().write_cdf(base / "pig.cdf", "objects/x/skeleton.chr", "Objects/modmaster/pig/pig.skin",
                            "Objects/modmaster/pig/pig.mtl")
    assert compiled_models(folder) == ["Objects/modmaster/pig/pig.cdf"]
    assert compiled_models(folder, (".cgf",)) == []
    project = ModManager(manager.workspace).create_mod("Pigs", "pigs")
    project.assign_asset("pig")
    entry = json.loads((manager.build_project(project) / "modmaster_assets.json").read_text())["assets"][0]
    assert entry["model_path"] == "Objects/modmaster/pig/pig.cdf" and "animation" in entry


def test_substance_exports_are_matched_to_their_materials():
    from pathlib import Path

    from compiler import cry_compile
    cc = cry_compile()
    files = [Path(n) for n in ("boar_hair_BaseColor.png", "boar_hair_Normal.png", "boar_hair_Roughness.png",
                               "Jacket_Base_Base_Color.png", "Jacket_Base_Normal_DirectX.png",
                               "Jacket_Base_Metallic.png", "other_Height.png", "readme.txt")]
    matched = cc.match_substance_textures(files, ["boar_hair [ModMaster]", "Jacket_Base", "unused"])
    assert set(matched) == {"boar_hair [ModMaster]", "Jacket_Base"}
    assert matched["boar_hair [ModMaster]"]["roughness"].name == "boar_hair_Roughness.png"
    assert matched["Jacket_Base"]["normal"].name == "Jacket_Base_Normal_DirectX.png"
    assert matched["Jacket_Base"]["base"].name == "Jacket_Base_Base_Color.png"


def test_rgba_tiff_keeps_its_alpha_channel(tmp_path):
    from PIL import Image

    from compiler import cry_compile
    pixels = bytes([10, 20, 30, 40]) * 4 + bytes([200, 100, 50, 250]) * 4
    path = cry_compile().write_tiff_rgba(tmp_path / "t.tif", 4, 2, pixels)
    with Image.open(path) as image:
        assert image.mode == "RGBA" and image.size == (4, 2)
        assert image.getpixel((0, 0)) == (10, 20, 30, 40) and image.getpixel((3, 1)) == (200, 100, 50, 250)


def test_painter_texture_sets_keep_the_modmaster_suffix():
    from pathlib import Path

    from compiler import cry_compile
    files = [Path("boar_eye [ModMaster]_BaseColor.png"), Path("boar_eye [ModMaster]_Normal.png")]
    matched = cry_compile().match_substance_textures(files, ["boar_eye [ModMaster]", "hair_cards [ModMaster]"])
    assert set(matched) == {"boar_eye [ModMaster]"}
    assert matched["boar_eye [ModMaster]"]["base"].name == "boar_eye [ModMaster]_BaseColor.png"


def test_painter_plugin_is_installed_next_to_an_existing_painter_profile(tmp_path):
    from compiler import cry_compile
    cc = cry_compile()
    profile = tmp_path / "OneDrive" / "Documents" / "Adobe" / "Adobe Substance 3D Painter"
    profile.mkdir(parents=True)
    target = cc.install_painter_plugin(tmp_path)
    assert target == profile / "python" / "plugins" / "kcd2_modmaster.py"
    assert "export_for_modmaster" in target.read_text(encoding="utf-8")
    assert cc.install_painter_plugin(tmp_path) == target
