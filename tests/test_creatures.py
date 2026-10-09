import json
import re
import zipfile

import pytest

from creatures import generator
from creatures.gamedata import BaseBody, bodies_for_skeleton, load_bodies
from creatures.model import CreatureDefinition
from creatures.store import CreatureStore
from mods.project import ModManager
from runtime_tools.manager import RuntimeManager
from workspace.asset_model import AssetType, WorkspaceAsset, list_workspace_assets, validate_workspace_asset

BOAR = BaseBody("Boar", "Boar", "objects/characters/animals/boar/boar.cdf",
                "objects/characters/animals/boar/skeleton_pig_01.chr",
                {"brain_id": "7f6a8b2d-9b2b-4500-9f7b-fc8f3a135029", "soul_archetype_id": "14", "soul_class_id": "16",
                 "social_class_id": "8", "factionName": "animal_wild", "soul_name": "animal_boar",
                 "soul_id": "9988bac0-35be-4e4c-b1af-2fc16c4168c2"}, "Grazes and roams.")
NPC = BaseBody("NPC", "NPC", "Objects/Characters/humans/male/skeleton/male.cdf",
               "objects/characters/humans/male/skeleton/male.chr",
               {"brain_id": "11111111-2222-3333-4444-555555555555", "soul_archetype_id": "0", "factionName": "x"})
BODIES = {"Boar": BOAR, "NPC": NPC}
MODEL = "Objects/modmaster/wizard_boar/wizard_boar.cdf"


def _game(root):
    data = root / "Data"
    data.mkdir(parents=True)
    with zipfile.ZipFile(data / "Scripts.pak", "w") as z:
        z.writestr("Scripts/Entities/AI/Boar.lua", 'Boar = { defaultSoulArchetype = "Boar", Properties = { '
                   'fileModel = "objects/characters/animals/boar/boar.cdf" } }')
        z.writestr("Scripts/Entities/AI/InventoryDummyDog.lua", 'X = { Properties = { fileModel = "dog.cdf" } }')
        z.writestr("Scripts/Entities/AI/Raven.lua", 'Raven = { Properties = { fileModel = "raven.cdf" } }')
    with zipfile.ZipFile(data / "Tables.pak", "w") as z:
        z.writestr("Libs/Tables/rpg/soul_archetype.xml",
                   '<soul_archetype soul_archetype_id="14" soul_archetype_name="Boar" />')
        z.writestr("Libs/Tables/rpg/soul__animal.xml", '<soul brain_id="b" soul_archetype_id="14" '
                   'soul_id="9988bac0-35be-4e4c-b1af-2fc16c4168c2" soul_name="animal_boar" factionName="animal_wild" />')
    with zipfile.ZipFile(data / "Characters.pak", "w") as z:
        z.writestr("objects/characters/animals/boar/boar.cdf",
                   '<CharacterDefinition><Model File="objects/characters/animals/boar/skeleton_pig_01.chr"/></CharacterDefinition>')
    return root


def test_bodies_come_from_entity_scripts_with_skeleton_and_template(tmp_path):
    game = _game(tmp_path / "game")
    bodies = load_bodies(game, tmp_path / "cache.json")
    assert [b.entity_class for b in bodies] == ["Boar"]  # dummies and souls-less classes are left out
    assert bodies[0].skeleton == "objects/characters/animals/boar/skeleton_pig_01.chr"
    assert bodies[0].template["soul_name"] == "animal_boar"
    assert load_bodies(game, tmp_path / "cache.json")[0].entity_class == "Boar"
    matches = bodies_for_skeleton(bodies, "Objects/Characters/Animals/Boar/skeleton_pig_01.chr")
    assert [b.entity_class for b in matches] == ["Boar"]


def test_soul_row_keeps_the_template_brain_and_sets_behaviour():
    c = CreatureDefinition("guard_boar", "Guard Boar", "Boar", attitude="hostile", combat_level=0.8)
    xml = generator.generate_soul_xml("wizard_mod", [c], BODIES)
    row = dict(re.findall(r'(\w+)="([^"]*)"', re.search(r"<soul [^>]*/>", xml).group(0)))
    assert row["soul_id"] == c.soul_guid and row["soul_name"] == "wizard_mod_guard_boar"
    assert row["factionName"] == "animal_wild_enemy" and row["combat_level"] == "0.8"
    assert row["brain_id"] == BOAR.template["brain_id"] and row["soul_archetype_id"] == "14"
    assert generator.soul_table_path("wizard_mod") == "Libs/Tables/rpg/soul__wizard_mod.xml"


def test_human_attitudes_use_human_factions():
    c = CreatureDefinition("bandit", "Bandit", "NPC", attitude="hostile")
    row = generator.soul_row("m", c, NPC)
    assert row["factionName"] == "eventNPCs_enemies"
    assert generator.registry_entry("m", c, NPC)["category"] == "npcs"


def test_registry_entry_carries_model_and_changed_stats_only():
    c = CreatureDefinition("b", "Wizard Boar", "Boar", model_path=MODEL, health=250, strength=12)
    entry = generator.registry_entry("m", c, BOAR)
    assert entry["spawn_type"] == "soul" and entry["entity_class"] == "Boar" and entry["model_path"] == MODEL
    assert entry["health"] == 250 and entry["stats"] == {"strength": 12}


def test_validation_catches_missing_models_and_wrong_skeletons():
    c = CreatureDefinition("b", "Wizard Boar", "Boar", model_path=MODEL)
    assert generator.validate([c], BODIES, {})[0][0] == generator.ERROR
    wolfish = {MODEL: "objects/characters/animals/dog/dog.chr"}
    assert generator.validate([c], BODIES, wolfish)[0][0] == generator.WARNING
    assert generator.validate([c], BODIES, {MODEL: BOAR.skeleton}) == []
    twin = CreatureDefinition("b2", "Twin", "Boar", soul_guid=c.soul_guid)
    assert any("share one soul" in m for _s, _n, m in generator.validate([c, twin], BODIES, {}))


def test_build_packs_soul_table_and_menu_entries(tmp_path, monkeypatch):
    game = tmp_path / "game"
    (game / "Data").mkdir(parents=True)
    (game / "Bin").mkdir()
    workspace = tmp_path / "ws"
    workspace.mkdir()
    project = ModManager(workspace).create_mod("Beasts", "beasts")
    CreatureStore(project).save(CreatureDefinition("angry_boar", "Angry Boar", "Boar", attitude="hostile", health=300))
    manager = RuntimeManager(game, workspace)
    monkeypatch.setattr(manager, "creature_bodies", lambda: BODIES)
    built = manager.build_project(project)
    with zipfile.ZipFile(built / "Data/beasts.pak") as z:
        assert "animal_wild_enemy" in z.read("Libs/Tables/rpg/soul__beasts.xml").decode()
    entries = json.loads((built / "modmaster_assets.json").read_text())["assets"]
    boar = next(e for e in entries if e["id"] == "creature:angry_boar")
    assert boar["health"] == 300 and boar["entity_class"] == "Boar"


def _rigged_asset(root, rigged_meta: bool):
    asset_dir = root / "Assets" / "wizard_boar"
    (asset_dir / "metadata").mkdir(parents=True)
    meta = {"asset_id": "wizard_boar", "asset_name": "wizard_boar", "skeleton": "boar.skin", "parts": [1]}
    if rigged_meta:
        meta["rigged"] = True
    (asset_dir / "metadata" / ".modmaster_asset.json").write_text(json.dumps(meta))
    return asset_dir


def test_rigged_assets_are_labelled_and_saving_keeps_blender_fields(tmp_path):
    asset_dir = _rigged_asset(tmp_path, rigged_meta=True)
    asset = list_workspace_assets(tmp_path)[0]
    assert asset.asset_type == AssetType.RIGGED.value
    asset.save()
    data = json.loads((asset_dir / "metadata" / ".modmaster_asset.json").read_text())
    assert data["skeleton"] == "boar.skin" and data["parts"] == [1] and data["rigged"] is True


def test_compiled_character_counts_as_rigged_even_without_the_flag(tmp_path):
    asset_dir = _rigged_asset(tmp_path, rigged_meta=False)
    target = asset_dir / "compiled" / "Objects" / "modmaster" / "wizard_boar"
    target.mkdir(parents=True)
    (target / "wizard_boar.cdf").write_text("<CharacterDefinition/>")
    assert list_workspace_assets(tmp_path)[0].asset_type == AssetType.RIGGED.value


def test_validation_explains_each_missing_step(tmp_path):
    asset_dir = _rigged_asset(tmp_path, rigged_meta=True)
    asset = list_workspace_assets(tmp_path)[0]
    report = validate_workspace_asset(asset, mods=[])
    actions = {i.field: i.action for i in report.issues}
    assert actions["export"] == "open_blender" and actions["mods"] == "add_to_mod"
    assert asset.status == "WARNING" and all(i.fix for i in report.issues if i.severity == "warning")
    target = asset_dir / "compiled" / "Objects" / "modmaster" / "wizard_boar"
    target.mkdir(parents=True)
    for name in ("wizard_boar.cdf", "wizard_boar.mtl", "textures/a_diff.dds"):
        (target / name).parent.mkdir(parents=True, exist_ok=True)
        (target / name).write_text("x")
    (asset_dir / "blender").mkdir()
    (asset_dir / "blender" / "wizard_boar.blend").write_text("x")
    asset.blend_file = str(asset_dir / "blender" / "wizard_boar.blend")
    report = validate_workspace_asset(asset, mods=["Beasts"])
    assert asset.status == "READY", [i.message for i in report.issues]


def test_store_round_trip_and_unique_ids(tmp_path):
    project = ModManager(tmp_path).create_mod("Store", "store_mod")
    store = CreatureStore(project)
    store.save(CreatureDefinition("wolf", "Wolf"))
    assert store.unique_id("Wolf") == "wolf_2"
    assert store.list()[0].name == "Wolf"
    store.delete(store.list()[0])
    assert store.list() == []


@pytest.mark.parametrize("value", [0, 10001])
def test_health_range_is_enforced(value):
    c = CreatureDefinition("b", "B", "Boar", health=value)
    assert any(s == generator.ERROR for s, _n, _m in generator.validate([c], BODIES, {}))
