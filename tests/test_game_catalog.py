import zipfile

from runtime_tools import game_catalog

GUID = "3d8b22ef-a1ad-49ab-a306-07d76aae1048"


def _fake_game(root):
    data = root / "Data"
    data.mkdir(parents=True)
    with zipfile.ZipFile(data / "Tables.pak", "w") as z:
        z.writestr("Libs/Tables/item/item.xml",
                   f'<database><ItemClasses><MeleeWeapon Id="{GUID}" Name="swordTest"/>'
                   '<Armor Id="not-a-guid" Name="broken"/></ItemClasses></database>')
    with zipfile.ZipFile(data / "Objects.pak", "w") as z:
        z.writestr("Objects/props/barrel.cgf", b"")
        z.writestr("Objects/props/barrel.mtl", b"")
    return root


def test_catalog_lists_items_and_models(tmp_path):
    data = game_catalog.build(_fake_game(tmp_path / "game"))
    ids = {a["id"]: a for a in data["assets"]}
    assert ids["item:" + GUID]["category"] == "weapons"
    assert ids["model:Objects/props/barrel.cgf"]["spawn_type"] == "static_prop"
    assert len(ids) == 2


def test_souls_carry_their_entity_class_and_random_entries_need_souls(tmp_path):
    game = _fake_game(tmp_path / "game")
    boar, villager = "11111111-0000-0000-0000-000000000001", "11111111-0000-0000-0000-000000000002"
    with zipfile.ZipFile(game / "Data" / "Tables.pak", "a") as z:
        z.writestr("Libs/Tables/rpg/soul_archetype.xml",
                   '<soul_archetype soul_archetype_id="1" soul_archetype_name="Boar"/>'
                   '<soul_archetype soul_archetype_id="2" soul_archetype_name="NPC_Female"/>'
                   '<soul_archetype soul_archetype_id="3" soul_archetype_name="Hen"/>')
        z.writestr("Libs/Tables/rpg/soul__animal.xml", f'<soul soul_id="{boar}" soul_name="animal_boar" soul_archetype_id="1"/>')
        z.writestr("Libs/Tables/rpg/soul.xml", f'<soul soul_id="{villager}" soul_name="villager" soul_archetype_id="2"/>')
    with zipfile.ZipFile(game / "Data" / "Scripts.pak", "w") as z:
        z.writestr("Scripts/Entities/AI/Boar.lua", "")
        z.writestr("Scripts/Entities/AI/NPC.lua", "")
    ids = {a["id"]: a for a in game_catalog.build(game)["assets"]}
    assert ids["soul:" + boar]["entity_class"] == "Boar"
    assert ids["soul:" + villager]["entity_class"] == "NPC" and ids["soul:" + villager]["category"] == "npcs"
    assert ids["soul:Boar"]["name"] == "Random Boar" and "soul_guid" not in ids["soul:Boar"]
    assert "soul:Hen" not in ids


def test_catalog_cache_is_rebuilt_when_archives_change(tmp_path):
    game = _fake_game(tmp_path / "game")
    cache = tmp_path / "cache.json"
    assert len(game_catalog.load(game, cache)["assets"]) == 2
    with zipfile.ZipFile(game / "Data" / "Extra.pak", "w") as z:
        z.writestr("Objects/props/crate.cgf", b"")
    assert len(game_catalog.load(game, cache)["assets"]) == 3
