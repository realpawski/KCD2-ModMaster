"""Item catalog, definition, validation and build tests against a miniature game install."""
import json
import xml.etree.ElementTree as ET
import zipfile
from pathlib import Path

import pytest

from items.gamedata import ItemCatalog
from items.generator import (
    build_localization_pak,
    generate_inventory_preset_xml,
    generate_item_xml,
    localization_filename,
)
from items.models import MODE_OVERRIDE, GameItemDefinition, new_item_from_base
from items.store import ModItemStore
from items.validator import errors_only, validate_game_item, validate_mod_items
from mods.project import ModManager
from runtime_tools.manager import RuntimeManager

XSD = """<?xml version="1.0" encoding="UTF-8"?>
<xs:schema xmlns:xs="http://www.w3.org/2001/XMLSchema">
  <xs:element name="MeleeWeapon"><xs:complexType>
    <xs:sequence><xs:element minOccurs="0" ref="Phase"/></xs:sequence>
    <xs:attribute name="Attack" use="required" type="xs:decimal"/>
    <xs:attribute name="Class" use="required" type="xs:integer"/>
    <xs:attribute name="IsBreakable" use="required" type="xs:boolean"/>
    <xs:attribute name="IconId" use="required" type="xs:NCName"/>
    <xs:attribute name="Id" use="required"/>
    <xs:attribute name="IsQuestItem" type="xs:boolean"/>
    <xs:attribute name="Model"/>
    <xs:attribute name="Name" use="required" type="xs:NCName"/>
    <xs:attribute name="Price" use="required" type="xs:integer"/>
    <xs:attribute name="UIInfo" type="xs:NCName"/>
    <xs:attribute name="UIName" type="xs:NCName"/>
    <xs:attribute name="Weight" use="required" type="xs:decimal"/>
  </xs:complexType></xs:element>
  <xs:element name="Armor"><xs:complexType>
    <xs:attribute name="DefenseSlash" use="required" type="xs:integer"/>
    <xs:attribute name="DefenseStab" use="required" type="xs:integer"/>
    <xs:attribute name="IconId" use="required" type="xs:NCName"/>
    <xs:attribute name="Id" use="required"/>
    <xs:attribute name="Name" use="required" type="xs:NCName"/>
    <xs:attribute name="Price" use="required" type="xs:integer"/>
    <xs:attribute name="UIName" type="xs:NCName"/>
    <xs:attribute name="Weight" use="required" type="xs:decimal"/>
  </xs:complexType></xs:element>
</xs:schema>"""

ITEMS = """<?xml version="1.0" encoding="us-ascii"?>
<database name="barbora"><ItemClasses version="8">
  <MeleeWeapon Attack="141" Class="4" IsBreakable="true" IconId="longswordBroad" IsQuestItem="true"
    Model="manmade/weapons/swords_long/long_sword_broad.cgf" Price="28544" Weight="2.9"
    UIName="ui_nm_longsword_broad" UIInfo="ui_in_longsword_broad"
    Id="3858560f-cf48-436f-8815-4426003288fb" Name="longswordBroad" />
  <MeleeWeapon Attack="20" Class="5" IsBreakable="false" IconId="mace" Price="10" Weight="1.5"
    UIName="ui_nm_mace" Id="196be21b-6d21-4dd6-84e4-c95ecd2092a7" Name="maceTraining">
    <Phase Order="1" Model="manmade/weapons/maces/mace_phase.cgf" />
  </MeleeWeapon>
  <Armor DefenseSlash="40" DefenseStab="55" IconId="gambeson" Price="900" Weight="4"
    UIName="ui_nm_gambeson" Id="0027df44-5f9c-4c92-9f81-a83ca124c4a8" Name="GambesonShort01" />
</ItemClasses></database>"""

STRINGS = """<Table>
<Row><Cell>ui_nm_longsword_broad</Cell><Cell>Broad longsword</Cell><Cell>Broad longsword</Cell></Row>
<Row><Cell>ui_in_longsword_broad</Cell><Cell>A wide blade.</Cell><Cell>A wide blade.</Cell></Row>
<Row><Cell>ui_nm_mace</Cell><Cell>Training mace</Cell><Cell>Training mace</Cell></Row>
<Row><Cell>ui_nm_gambeson</Cell><Cell>Short gambeson</Cell><Cell>Short gambeson</Cell></Row>
</Table>"""


@pytest.fixture
def game(tmp_path):
    root = tmp_path / "kcd2"
    (root / "Data").mkdir(parents=True)
    (root / "Localization").mkdir()
    with zipfile.ZipFile(root / "Data/Tables.pak", "w") as z:
        z.writestr("Libs/Tables/item/item.xsd", XSD)
        z.writestr("Libs/Tables/item/item.xml", ITEMS)
    with zipfile.ZipFile(root / "Localization/English_xml.pak", "w") as z:
        z.writestr("text_ui_items.xml", STRINGS)
    return root


@pytest.fixture
def catalog(game, tmp_path):
    return ItemCatalog.load(game, tmp_path / "cache")


def test_catalog_reads_schema_rows_and_names(catalog):
    assert set(catalog.types()) == {"MeleeWeapon", "Armor"}
    sword = catalog.by_name("longswordBroad")
    assert sword.display == "Broad longsword" and sword.info == "A wide blade."
    spec = catalog.schema("MeleeWeapon").attrs["Attack"]
    assert spec.required and spec.numeric == "int" and spec.hi == 141
    assert catalog.schema("MeleeWeapon").attrs["IsBreakable"].is_bool
    assert "<Phase" in catalog.by_name("maceTraining").children
    assert [i.name for i in catalog.search("broad", "MeleeWeapon")] == ["longswordBroad"]


def test_catalog_cache_round_trip(game, tmp_path):
    first = ItemCatalog.load(game, tmp_path / "c")
    second = ItemCatalog.load(game, tmp_path / "c")
    assert len(first.items) == len(second.items) == 3
    assert second.schema("Armor").attrs["DefenseStab"].numeric == "int"


def test_new_item_clones_every_attribute_with_fresh_identity(catalog):
    base = catalog.by_name("longswordBroad")
    item = new_item_from_base(base, "hero_sword", "Hero Sword")
    assert item.guid != base.guid and item.name == "hero_sword"
    assert item.attributes["Model"] == base.attrs["Model"]
    assert item.attributes["IsQuestItem"] == "false"
    assert item.ui_name == "ui_nm_hero_sword" and item.description == "A wide blade."
    assert not errors_only(validate_game_item(item, catalog, "my_mod"))


def test_override_keeps_vanilla_identity_and_text(catalog):
    base = catalog.by_name("GambesonShort01")
    item = new_item_from_base(base, "tough_gambeson", "", mode=MODE_OVERRIDE)
    item.attributes["DefenseStab"] = "200"
    assert item.guid == base.guid and item.name == "GambesonShort01" and not item.write_text
    issues = validate_game_item(item, catalog, "my_mod")
    assert not errors_only(issues)
    assert any(i.check_name == "Balance" for i in issues)


def test_validation_blocks_what_would_break_the_database(catalog):
    base = catalog.by_name("longswordBroad")
    item = new_item_from_base(base, "bad", "Bad")
    item.attributes["Defense"] = "10"
    item.attributes["Attack"] = "lots"
    del item.attributes["Price"]
    item.attributes["IsBreakable"] = "yes"
    checks = {(i.check_name, i.attribute) for i in errors_only(validate_game_item(item, catalog, "m"))}
    assert ("Schema", "Defense") in checks
    assert ("Value", "Attack") in checks
    assert ("Schema", "Price") in checks
    assert ("Value", "IsBreakable") in checks


def test_new_item_must_not_reuse_vanilla_guid_or_name(catalog):
    base = catalog.by_name("longswordBroad")
    item = new_item_from_base(base, "longswordBroad", "Copy")
    item.guid = base.guid
    messages = [i.check_name for i in errors_only(validate_game_item(item, catalog, "m"))]
    assert messages.count("GUID") == 1 and messages.count("Name") == 1


def test_duplicates_inside_a_mod(catalog):
    base = catalog.by_name("longswordBroad")
    a = new_item_from_base(base, "same", "A")
    b = new_item_from_base(base, "same", "B")
    b.guid = a.guid
    assert len(validate_mod_items([a, b])) == 2


def test_missing_game_data_is_reported(catalog):
    item = new_item_from_base(catalog.by_name("longswordBroad"), "x", "X")
    assert errors_only(validate_game_item(item, None, "m"))[0].check_name == "Game data"


def test_item_xml_preserves_children_and_identity(catalog):
    mace = new_item_from_base(catalog.by_name("maceTraining"), "spiked", "Spiked")
    root = ET.fromstring(generate_item_xml([mace], "m").split("\n", 1)[1])
    row = root.find("ItemClasses/MeleeWeapon")
    assert row.get("Id") == mace.guid and row.get("Name") == "spiked"
    assert row.find("Phase").get("Order") == "1"


def test_localization_uses_mod_scoped_filename(catalog, tmp_path):
    item = new_item_from_base(catalog.by_name("longswordBroad"), "hero", "Hero Sword", "Shiny.")
    override = new_item_from_base(catalog.by_name("GambesonShort01"), "g", "", mode=MODE_OVERRIDE)
    pak = tmp_path / "English_xml.pak"
    assert build_localization_pak([item, override], pak, "my_mod")
    with zipfile.ZipFile(pak) as z:
        assert z.namelist() == [localization_filename("my_mod")] == ["text__my_mod.xml"]
        text = z.read("text__my_mod.xml").decode()
    assert "Hero Sword" in text and "Shiny." in text and "Short gambeson" not in text
    assert not build_localization_pak([override], tmp_path / "none.pak", "my_mod")


def test_player_inventory_preset(catalog):
    item = new_item_from_base(catalog.by_name("longswordBroad"), "gift", "Gift")
    assert generate_inventory_preset_xml([item]) is None
    item.add_to_player_inventory = True
    xml = generate_inventory_preset_xml([item])
    preset = ET.fromstring(xml.split("\n", 1)[1]).find("InventoryPresets/InventoryPreset")
    assert preset.get("Name") == "inventory_player_henry"
    assert preset.find("PresetItem").get("Name") == "gift"


def test_v1_definition_migrates_without_changing_guid(tmp_path):
    legacy = {
        "item_id": "minecraft_sword", "guid": "3d8b22ef-a1ad-49ab-a306-07d76aae1048",
        "name": "minecraft_sword", "ui_name": "ui_nm_minecraft_sword", "display_name": "Minecraft Sword",
        "ui_info": "ui_in_minecraft_sword", "description": "Square.", "item_type": "MeleeWeapon",
        "item_class": 4, "sub_class": 11, "model_path": "manmade/weapons/swords_long/minecraft_sword.cgf",
        "attack": 141.0, "attack_mod_stab": 1.05, "weight": 2.9, "price": 28544, "is_breakable": True,
        "template_id": "longswordBroad", "workspace_asset_id": "minecraft_sword",
    }
    path = tmp_path / ".modmaster_item.json"
    path.write_text(json.dumps(legacy))
    item = GameItemDefinition.load_from_file(path)
    assert item.guid == legacy["guid"]
    assert item.attributes["Attack"] == "141"
    assert item.attributes["AttackModStab"] == "1.05"
    assert item.attributes["IsBreakable"] == "true"
    assert item.model_path.endswith("minecraft_sword.cgf") and item.uses_custom_model
    item.save_to_file(path)
    assert json.loads(path.read_text())["format_version"] == 2


def test_store_lists_project_and_legacy_asset_items(tmp_path, catalog):
    workspace = tmp_path / "ws"
    project = ModManager(workspace).create_mod("Store Mod", "store_mod")
    store = ModItemStore(project, workspace)
    item = new_item_from_base(catalog.by_name("longswordBroad"), store.unique_item_id("Hero Sword"), "Hero")
    store.save(item)
    assert store.unique_item_id("Hero Sword") == "hero_sword_2"
    legacy_dir = workspace / "Assets" / "old_sword"
    GameItemDefinition("old_sword", "", "old_sword", "Old").save_for_asset(legacy_dir)
    project.assign_asset("old_sword")
    names = [s.item.item_id for s in store.list()]
    assert names == ["hero_sword", "old_sword"]
    store.delete(item)
    assert [s.item.item_id for s in store.list()] == ["old_sword"]


def test_add_item_dialog_opens_and_offers_compiled_models(tmp_path, catalog, qapp):
    from ui.dialogs.new_item_dialog import NewItemDialog

    workspace = tmp_path / "ws"
    target = workspace / "Assets" / "diamond_sword" / "compiled" / "Objects" / "modmaster" / "diamond_sword"
    target.mkdir(parents=True)
    (target / "diamond_sword.cgf").write_bytes(b"CrCh" + b"\0" * 16)
    meta = workspace / "Assets" / "diamond_sword" / "metadata" / ".modmaster_asset.json"
    meta.parent.mkdir(parents=True)
    meta.write_text(json.dumps({"asset_id": "diamond_sword", "asset_name": "diamond_sword"}))
    project = ModManager(workspace).create_mod("Swords", "swords")
    dlg = NewItemDialog(catalog, ModItemStore(project, workspace), workspace)
    offered = [dlg.cb_model.itemText(i) for i in range(dlg.cb_model.count())]
    assert any("diamond_sword" in text for text in offered)


def test_build_packs_items_localization_and_preset(game, tmp_path, catalog):
    workspace = tmp_path / "ws"
    workspace.mkdir()
    project = ModManager(workspace).create_mod("Arms Mod", "arms_mod")
    store = ModItemStore(project, workspace)

    sword = new_item_from_base(catalog.by_name("longswordBroad"), "hero_sword", "Hero Sword", "Shiny.")
    sword.attributes["Attack"] = "180"
    sword.add_to_player_inventory = True
    store.save(sword)
    armor = new_item_from_base(catalog.by_name("GambesonShort01"), "g", "", mode=MODE_OVERRIDE)
    store.save(armor)

    asset_id = "custom_blade"
    (workspace / "Assets" / asset_id / "source").mkdir(parents=True)
    (workspace / "Assets" / asset_id / "source" / "custom_blade.cgf").write_bytes(b"CrChF\x07geometry")
    custom = new_item_from_base(catalog.by_name("longswordBroad"), "custom_blade", "Custom Blade")
    custom.attributes["Model"] = "manmade/weapons/swords_long/custom_blade.cgf"
    custom.workspace_asset_id = asset_id
    store.save(custom)

    built = RuntimeManager(game, workspace).build_project(project)
    with zipfile.ZipFile(built / "Data/arms_mod.pak") as z:
        names = set(z.namelist())
        table = z.read("Libs/Tables/item/item__arms_mod.xml").decode()
        preset = z.read("Libs/Tables/item/InventoryPreset__arms_mod.xml").decode()
    assert "Objects/manmade/weapons/swords_long/custom_blade.cgf" in names
    assert "Objects/manmade/weapons/swords_long/custom_blade.mtl" in names
    assert sword.guid in table and 'Attack="180"' in table and armor.guid in table
    assert 'Name="hero_sword"' in preset
    with zipfile.ZipFile(built / "Localization/English_xml.pak") as z:
        assert "Hero Sword" in z.read("text__arms_mod.xml").decode()
    assert not (built / "Localization/German_xml.pak").exists()
    registry = json.loads((built / "modmaster_assets.json").read_text())
    categories = {a["id"]: a["category"] for a in registry["assets"]}
    assert categories == {"item:hero_sword": "weapons", "item:g": "armor", "item:custom_blade": "weapons"}
    ids = [a["id"] for a in registry["assets"]]
    assert len(ids) == len(set(ids))


def test_item_and_prop_of_one_asset_keep_separate_menu_entries(tmp_path, catalog):
    from runtime_tools.manager import RuntimeManager

    item = new_item_from_base(catalog.by_name("longswordBroad"), "diamond_sword", "Diamond Sword")
    entry = RuntimeManager._item_registry_entry(item)
    assert entry["id"] == "item:diamond_sword" and entry["spawn_type"] == "inventory_item"
    assert any(i.check_name == "Model" for i in validate_game_item(item, catalog, "swords"))
    item.workspace_asset_id = "diamond_sword"
    assert not any(i.check_name == "Model" for i in validate_game_item(item, catalog, "swords"))


def test_build_refuses_invalid_items(game, tmp_path, catalog):
    workspace = tmp_path / "ws"
    workspace.mkdir()
    project = ModManager(workspace).create_mod("Broken", "broken_mod")
    item = new_item_from_base(catalog.by_name("longswordBroad"), "broken", "Broken")
    item.attributes["NotAnAttribute"] = "1"
    ModItemStore(project, workspace).save(item)
    with pytest.raises(ValueError, match="NotAnAttribute"):
        RuntimeManager(game, workspace).build_project(project)
