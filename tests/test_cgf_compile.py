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
