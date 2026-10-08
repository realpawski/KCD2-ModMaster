"""Spawn catalog of the installed game, read from its archives and cached per user."""
from __future__ import annotations

import json
import uuid
import xml.etree.ElementTree as ET
import zipfile
from pathlib import Path

CATALOG_VERSION = 2
WEAPON_TAGS = ("MeleeWeapon", "MissileWeapon", "Ammo")
ARMOR_TAGS = ("Armor", "Helmet", "Hood")


def _archives(game: Path) -> list[Path]:
    return sorted((game / "Data").glob("*.pak")) + sorted((game / "Engine").glob("*.pak"))


def _stamp(game: Path) -> list:
    return [[p.name, p.stat().st_size, int(p.stat().st_mtime)] for p in _archives(game)]


def _items(tables: Path) -> dict:
    assets = {}
    with zipfile.ZipFile(tables) as z:
        for name in sorted(z.namelist()):
            if not (name.startswith("Libs/Tables/item/item") and name.endswith(".xml")):
                continue
            classes = ET.fromstring(z.read(name)).find("ItemClasses")
            if classes is None:
                continue
            for row in classes:
                try:
                    guid = str(uuid.UUID(row.get("Id", "")))
                except ValueError:
                    continue
                category = "weapons" if row.tag in WEAPON_TAGS else "armor" if row.tag in ARMOR_TAGS else "items"
                assets["item:" + guid] = {
                    "id": "item:" + guid, "name": row.get("Name", guid), "category": category,
                    "spawn_type": "inventory_item", "item_guid": guid, "status": "installed_game_database",
                    "source": "base_game", "database_type": row.tag,
                }
    return assets


def _models(game: Path) -> list[str]:
    models = set()
    for pak in _archives(game):
        try:
            with zipfile.ZipFile(pak) as z:
                names = z.namelist()
        except (OSError, zipfile.BadZipFile):
            continue
        for name in names:
            if name.lower().endswith(".cgf") and ":" not in name and ".." not in name:
                models.add(name.replace("\\", "/"))
    return sorted(models)


def build(game: Path) -> dict:
    tables = game / "Data" / "Tables.pak"
    if not tables.is_file():
        raise ValueError(f"Tables.pak not found in {game / 'Data'}")
    assets = _items(tables)
    for model in _models(game):
        assets["model:" + model] = {
            "id": "model:" + model, "name": Path(model).stem, "category": "props",
            "spawn_type": "static_prop", "model_path": model, "status": "installed_game_model",
            "source": "base_game",
        }
    return {"format_version": CATALOG_VERSION, "game": str(game), "stamp": _stamp(game),
            "assets": list(assets.values())}


def load(game: Path, cache: Path) -> dict:
    """Return the cached catalog, rebuilding it when the game files changed."""
    game = Path(game)
    try:
        data = json.loads(cache.read_text(encoding="utf-8"))
        if (data.get("format_version") == CATALOG_VERSION and data.get("game") == str(game)
                and data.get("stamp") == _stamp(game)):
            return data
    except (OSError, ValueError):
        pass
    data = build(game)
    cache.parent.mkdir(parents=True, exist_ok=True)
    cache.write_text(json.dumps(data, separators=(",", ":")), encoding="utf-8")
    return data
