"""Spawn catalog of the installed game, read from its archives and cached per user."""
from __future__ import annotations

import json
import re
import uuid
import xml.etree.ElementTree as ET
import zipfile
from pathlib import Path

CATALOG_VERSION = 4
HUMAN_ARCHETYPES = ("NPC", "NPC_Female", "NPC_Child", "Hero", "Hero_female")
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


def _attrs(row: str) -> dict:
    return dict(re.findall(r'(\w+)="([^"]*)"', row))


def _entity_classes(game: Path) -> set[str]:
    try:
        with zipfile.ZipFile(game / "Data" / "Scripts.pak") as z:
            return {n.rsplit("/", 1)[1][:-4] for n in z.namelist()
                    if n.startswith("Scripts/Entities/AI/") and n.count("/") == 3 and n.endswith(".lua")}
    except (OSError, zipfile.BadZipFile):
        return set()


def _souls(tables: Path, classes: set[str]) -> dict:
    """Spawnable NPCs and animals: one entry per soul plus a random one per archetype that has souls."""
    def entity_class(archetype: str) -> str:
        if archetype in classes:
            return archetype
        return "NPC" if archetype in HUMAN_ARCHETYPES else ""

    souls, archetypes = {}, {}
    with zipfile.ZipFile(tables) as z:
        names = z.namelist()
        if "Libs/Tables/rpg/soul_archetype.xml" in names:
            for row in re.findall(r"<soul_archetype [^>]*/>", z.read("Libs/Tables/rpg/soul_archetype.xml").decode("utf-8", "replace")):
                a = _attrs(row)
                archetypes[a.get("soul_archetype_id")] = a.get("soul_archetype_name", "")
        for name in sorted(names):
            if not re.search(r"Libs/Tables/rpg/soul(__[^/]*)?\.xml$", name) or "test" in name.lower():
                continue
            for row in re.findall(r"<soul [^>]*/>", z.read(name).decode("utf-8", "replace")):
                a = _attrs(row)
                try:
                    guid = str(uuid.UUID(a.get("soul_id", "")))
                except ValueError:
                    continue
                archetype = archetypes.get(a.get("soul_archetype_id"), "")
                if archetype in ("Hero", "Hero_female") or not entity_class(archetype):
                    continue
                souls["soul:" + guid] = {
                    "id": "soul:" + guid, "name": a.get("soul_name", guid),
                    "category": "npcs" if archetype in HUMAN_ARCHETYPES else "animals",
                    "spawn_type": "soul", "soul_guid": guid, "archetype": archetype,
                    "entity_class": entity_class(archetype),
                    "status": "installed_game_database", "source": "base_game"}
    assets = {}
    for archetype in sorted({s["archetype"] for s in souls.values()}):
        assets["soul:" + archetype] = {
            "id": "soul:" + archetype, "name": f"Random {archetype.replace('_', ' ')}",
            "category": "npcs" if archetype in HUMAN_ARCHETYPES else "animals", "spawn_type": "soul",
            "archetype": archetype, "entity_class": entity_class(archetype),
            "status": "installed_game_database", "source": "base_game"}
    assets.update(souls)
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
    assets.update(_souls(tables, _entity_classes(game)))
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
