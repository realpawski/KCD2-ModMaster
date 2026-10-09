"""Bodies a creature can use: the game's AI entity classes with their skeleton and a template soul."""
from __future__ import annotations

import json
import re
import zipfile
from dataclasses import asdict, dataclass, field
from pathlib import Path
from xml.etree import ElementTree as ET

from creatures.model import TEMPERAMENTS
from runtime_tools.animations import _game_files, _read, resolve_skeleton

CACHE_VERSION = 2
SOUL_TABLE = re.compile(r"Libs/Tables/rpg/soul(__[^/]*)?\.xml$")


@dataclass
class BaseBody:
    entity_class: str
    archetype: str
    model: str
    skeleton: str
    template: dict[str, str] = field(default_factory=dict)
    temperament: str = ""
    # How the game dresses this body: its ClothingConfig row, the race/gender of its component tree and the
    # equipment part the body skin occupies. A custom look replaces exactly that skin.
    clothing: dict[str, str] = field(default_factory=dict)
    race: str = ""
    gender: str = ""
    equipment_part: str = ""


def _attrs(row: str) -> dict[str, str]:
    return dict(re.findall(r'(\w+)="([^"]*)"', row))


def _stamp(game: Path) -> list:
    paks = [game / "Data" / "Scripts.pak", game / "Data" / "Tables.pak"]
    return [[p.name, p.stat().st_size, int(p.stat().st_mtime)] for p in paks if p.is_file()]


def _templates(tables: Path) -> dict[str, dict[str, str]]:
    """First soul of each archetype, preferring the generic animal and base tables."""
    with zipfile.ZipFile(tables) as z:
        names = z.namelist()
        archetypes = {}
        for row in re.findall(r"<soul_archetype [^>]*/>", z.read("Libs/Tables/rpg/soul_archetype.xml").decode("utf-8", "replace")):
            a = _attrs(row)
            archetypes[a.get("soul_archetype_id")] = a.get("soul_archetype_name", "")
        order = sorted((n for n in names if SOUL_TABLE.search(n) and "test" not in n.lower()),
                       key=lambda n: (not n.endswith(("soul__animal.xml", "soul.xml")), n))
        templates: dict[str, dict[str, str]] = {}
        for name in order:
            for row in re.findall(r"<soul [^>]*/>", z.read(name).decode("utf-8", "replace")):
                a = _attrs(row)
                archetype = archetypes.get(a.get("soul_archetype_id"), "")
                if archetype and archetype not in templates and a.get("brain_id"):
                    templates[archetype] = a
    return templates


def _clothing(tables: Path) -> tuple[dict[str, dict[str, str]], dict[str, tuple[str, str, str]]]:
    """ClothingConfig rows by name, and body name -> (race, gender, equipment part)."""
    with zipfile.ZipFile(tables) as z:
        names = set(z.namelist())
        configs = {}
        if "Libs/Tables/Character/ClothingConfig.xml" in names:
            root = ET.fromstring(z.read("Libs/Tables/Character/ClothingConfig.xml"))
            configs = {c.get("Name"): dict(c.attrib) for c in root.iter("ClothingConfig") if c.get("Name")}
        bodies = {}
        if "Libs/Tables/Character/CharacterComponent.xml" in names:
            root = ET.fromstring(z.read("Libs/Tables/Character/CharacterComponent.xml"))
            for top in root.iter("CharacterComponents"):
                for component in top:
                    _walk_bodies(component, component.get("Race", ""), component.get("Gender", ""), "", bodies)
    return configs, bodies


def _walk_bodies(node, race: str, gender: str, part: str, out: dict) -> None:
    elements = node.find("Elements")
    if elements is not None:
        for skin in elements.iter("SkinElement"):
            part = skin.get("EquipmentPart") or part
    if node.tag == "Body" and node.get("Name"):
        out[node.get("Name")] = (race, gender, part)
    derived = node.find("DerivedComponents")
    for child in derived if derived is not None else []:
        _walk_bodies(child, race, gender, part, out)


def _scan(game: Path) -> list[BaseBody]:
    files = _game_files(game)
    templates = _templates(game / "Data" / "Tables.pak")
    configs, body_parts = _clothing(game / "Data" / "Tables.pak")
    bodies = []
    with zipfile.ZipFile(game / "Data" / "Scripts.pak") as z:
        scripts = [n for n in z.namelist() if n.startswith("Scripts/Entities/AI/") and n.count("/") == 3 and n.endswith(".lua")]
        for script in sorted(scripts):
            entity_class = script.rsplit("/", 1)[1][:-4]
            # Inventory dummies and the AI-less NPC exist for menus and tests, not for the world.
            if entity_class.startswith("InventoryDummy") or entity_class == "NPC_NAI":
                continue
            source = z.read(script).decode("utf-8", "replace")
            model = re.search(r'fileModel\s*=\s*"([^"]+)"', source)
            archetype = re.search(r'defaultSoulArchetype\s*=\s*"([^"]+)"', source)
            archetype = archetype.group(1) if archetype else entity_class
            if not model or archetype not in templates:
                continue
            skeleton = ""
            data = _read(files, model.group(1))
            if model.group(1).lower().endswith(".cdf") and data:
                try:
                    node = ET.fromstring(data).find("Model")
                    skeleton = node.get("File", "") if node is not None else ""
                except ET.ParseError:
                    pass
            config_name = re.search(r'esClothingConfig\s*=\s*"([^"]+)"', source)
            clothing = configs.get(config_name.group(1), {}) if config_name else {}
            race, gender, part = body_parts.get(clothing.get("DefaultBody", ""), ("", "", ""))
            if clothing and not part:
                # Some bodies are defined outside the component tree; their race shares the skin slot.
                race, gender = clothing.get("Race", ""), clothing.get("Gender", "")
                part = next((p for r, _g, p in body_parts.values() if r == race and p), "")
            bodies.append(BaseBody(entity_class, archetype, model.group(1), skeleton,
                                   templates[archetype], TEMPERAMENTS.get(entity_class, ""),
                                   clothing, race, gender, part))
    return bodies


def load_bodies(game: Path, cache: Path) -> list[BaseBody]:
    game = Path(game)
    try:
        data = json.loads(cache.read_text(encoding="utf-8"))
        if data.get("version") == CACHE_VERSION and data.get("stamp") == _stamp(game):
            return [BaseBody(**b) for b in data["bodies"]]
    except (OSError, ValueError, TypeError, KeyError):
        pass
    bodies = _scan(game)
    cache.parent.mkdir(parents=True, exist_ok=True)
    cache.write_text(json.dumps({"version": CACHE_VERSION, "stamp": _stamp(game),
                                 "bodies": [asdict(b) for b in bodies]}), encoding="utf-8")
    return bodies


def same_skeleton(a: str, b: str) -> bool:
    return bool(a) and a.lower().replace("\\", "/") == b.lower().replace("\\", "/")


def bodies_for_skeleton(bodies: list[BaseBody], skeleton: str, game: Path | None = None) -> list[BaseBody]:
    """Bodies whose animations fit a model's skeleton; an older .skin reference is resolved first."""
    if skeleton and not skeleton.lower().endswith(".chr") and game:
        skeleton = resolve_skeleton(Path(game), skeleton) or skeleton
    return [b for b in bodies if same_skeleton(b.skeleton, skeleton)]
