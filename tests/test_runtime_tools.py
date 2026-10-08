"""Real format/ownership invariants, not an in-game acceptance substitute."""
import json
import xml.etree.ElementTree as ET
import zipfile
from pathlib import Path

import pytest

from mods.project import ModManager
from runtime_tools import RUNTIME_ID
from runtime_tools.manager import RuntimeManager
from runtime_tools.packaging import lua_literal, mod_id, pack_data, virtual_path


@pytest.fixture
def manager(tmp_path):
    game = tmp_path / "game"
    (game / "Data").mkdir(parents=True)
    (game / "Bin").mkdir()
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    return RuntimeManager(game, workspace)


def project(manager):
    return ModManager(manager.workspace).create_mod("Test & <PAWSKI>", "runtime_test")


def test_companion_xml_stored_pak_and_real_bootstrap(manager):
    built = manager.build_companion(manager.load_installed_registry())
    assert ET.parse(built / "mod.manifest").findtext("info/modid") == RUNTIME_ID
    with zipfile.ZipFile(built / "Data/modmaster_dev.pak") as z:
        assert "Scripts/Mods/kcd_modmaster_dev.lua" in z.namelist()
        assert b"ModMasterRegistry =" in z.read("Scripts/ModMaster/registry.lua")
        assert all(i.compress_type == zipfile.ZIP_STORED for i in z.infolist())
        assert z.read("Libs/UI/ModMasterMenu.swf")[:3] in (b"FWS", b"CWS")
        assert b'cursor="' in z.read("Libs/UI/UIElements/ModMasterMenu.xml")


def test_stale_native_ui_is_not_silently_installed(manager, tmp_path):
    import shutil
    copied = tmp_path / "bundled"
    shutil.copytree(manager.source, copied)
    manager.source = copied
    with (copied / "ui/ModMasterMenu.as").open("a") as f:
        f.write("\n// Changed source without compiling\n")
    with pytest.raises(ValueError, match="run tools/build_runtime_ui.py"):
        manager.sync()
    assert not (manager.mods / RUNTIME_ID).exists()


def test_install_status_content_drift_and_repair(manager):
    target = manager.sync()
    assert manager.status().state == "Installed"
    (target / "Data/modmaster_dev.pak").write_bytes(b"broken")
    assert manager.status().state == "Repair required"
    with pytest.raises(ValueError, match="Installed files changed"):
        manager.sync()
    manager.sync(repair=True)
    assert manager.status().state == "Installed"


def test_unrelated_mod_never_overwritten(manager):
    target = manager.mods / RUNTIME_ID
    target.mkdir(parents=True)
    (target / "precious.txt").write_text("user")
    with pytest.raises(ValueError, match="unowned"):
        manager.sync()
    assert (target / "precious.txt").read_text() == "user"


def test_extra_files_block_repair_and_uninstall(manager):
    target = manager.sync()
    (target / "user.lua").write_text("keep")
    with pytest.raises(ValueError, match="additional files"):
        manager.sync(repair=True)
    with pytest.raises(ValueError, match="additional files"):
        manager.uninstall()
    assert (target / "user.lua").is_file()


def test_uninstall_keeps_one_recoverable_copy(manager):
    target = manager.sync()
    manager.sync()
    manager.uninstall()
    assert not target.exists()
    assert (manager.state_root / "rollback" / RUNTIME_ID / "mod.manifest").is_file()
    manager.rollback()
    assert target.is_dir()


def test_manifest_is_xml_and_escapes_display_name(manager):
    p = project(manager)
    built = manager.build_project(p)
    assert ET.parse(built / "mod.manifest").findtext("info/name") == p.name


def test_glb_not_claimed_as_compiled_asset(manager):
    p = project(manager)
    p.assets = ["barrel"]
    with pytest.raises(ValueError, match="has no compiled model yet"):
        manager.build_project(p)
    p.assets = []
    (Path(p.project_dir) / "game/barrel.glb").write_bytes(b"glTF")
    with pytest.raises(ValueError, match="Uncompiled"):
        manager.build_project(p)


def test_compiled_dependency_validation(manager):
    p = project(manager)
    root = Path(p.project_dir)
    (root / "game/Objects/test").mkdir(parents=True)
    (root / "game/Objects/test/barrel.cgf").write_bytes(b"CrChF\x07")
    descriptor = {"format_version": 1, "assets": [{"id": "barrel", "model_path": "Objects/test/barrel.cgf",
                    "dependencies": ["Objects/test/barrel.cgfm"]}]}
    (root / "runtime_assets.json").write_text(json.dumps(descriptor))
    with pytest.raises(ValueError, match="Missing runtime dependency"):
        manager.build_project(p)
    (root / "game/Objects/test/barrel.cgfm").write_bytes(b"CrChF\x07")
    target = manager.build_install(p)
    assert target.is_dir()
    registry = manager.load_installed_registry()
    a = registry["mods"][0]["assets"][0]
    assert a["model_path"] == "Objects/test/barrel.cgf"
    assert a["status"] == "packaged_unverified"


def test_inventory_not_spawned_as_static_prop(manager):
    p = project(manager)
    (Path(p.project_dir) / "runtime_assets.json").write_text(json.dumps({"format_version": 1,
        "assets": [{"id": "sword", "spawn_type": "item", "model_path": "Objects/sword.cgf"}]}))
    with pytest.raises(ValueError, match="Only static_prop"):
        manager.build_project(p)


@pytest.mark.parametrize("value", ["../escape", "UPPER", "mod-foo", "mod2", "", "a/b"])
def test_unsafe_mod_ids(value):
    with pytest.raises(ValueError):
        mod_id(value)


@pytest.mark.parametrize("value", ["../escape.cgf", "C:/escape.cgf", "/abs.cgf", "foo/../../bar"])
def test_unsafe_virtual_paths(value):
    with pytest.raises(ValueError):
        virtual_path(value)


def test_lua_injection_is_data():
    value = '"}; System.RemoveEntity(1); --\n\\123'
    result = lua_literal(value)
    assert "\\034" in result and "\\010" in result and "\\092" in result
    assert result.startswith('"') and result.endswith('"')
    with pytest.raises(ValueError):
        lua_literal(float("nan"))


def test_case_collisions_rejected(tmp_path):
    with pytest.raises(ValueError, match="Duplicate"):
        pack_data(tmp_path / "empty", tmp_path / "test.pak", {"A.lua": b"a", "a.lua": b"b"})


def test_existing_load_order_preserved(manager):
    manager.mods.mkdir()
    order = manager.mods / "mod_order.txt"
    order.write_text("# user's order\nother_mod\n")
    manager.sync()
    assert order.read_text() == "# user's order\nother_mod\n" + RUNTIME_ID + "\n"
    manager.sync()
    assert order.read_text().count(RUNTIME_ID) == 1


def test_source_change_offers_update(manager):
    import shutil
    cloned = manager.workspace / "bundled"
    shutil.copytree(manager.source, cloned)
    manager.source = cloned
    manager.sync()
    (cloned / "version.json").write_text('{"changed":true}')
    assert manager.status().state == "Update available"
