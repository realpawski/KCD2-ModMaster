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


def test_catalog_cache_is_rebuilt_when_archives_change(tmp_path):
    game = _fake_game(tmp_path / "game")
    cache = tmp_path / "cache.json"
    assert len(game_catalog.load(game, cache)["assets"]) == 2
    with zipfile.ZipFile(game / "Data" / "Extra.pak", "w") as z:
        z.writestr("Objects/props/crate.cgf", b"")
    assert len(game_catalog.load(game, cache)["assets"]) == 3
