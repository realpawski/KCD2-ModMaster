"""Game files for creatures: a split soul table and the in-game menu entries."""
from __future__ import annotations

import uuid
from xml.sax.saxutils import quoteattr

from creatures.gamedata import BaseBody
from creatures.model import CreatureDefinition, attitude

ERROR, WARNING = "error", "warning"


def soul_table_path(mod_id: str) -> str:
    return f"Libs/Tables/rpg/soul__{mod_id}.xml"


def clothing_table_path(mod_id: str) -> str:
    return f"Libs/Tables/Character/ClothingConfig__{mod_id}.xml"


def component_table_path(mod_id: str) -> str:
    return f"Libs/Tables/Character/CharacterComponent__{mod_id}.xml"


def clothing_name(mod_id: str, creature: CreatureDefinition) -> str:
    return f"{mod_id}_{creature.creature_id}"


def custom_look(creature: CreatureDefinition, body: BaseBody) -> bool:
    """Animals are dressed through one body skin, which a custom model can replace; people are assembled
    from many clothing parts, so they keep the game look."""
    return bool(creature.model_path) and not creature.is_human and bool(body.clothing and body.equipment_part)


def _database(inner: list[str]) -> str:
    return "\n".join(['<?xml version="1.0" encoding="us-ascii"?>',
                      '<database xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance" name="barbora" '
                      'xsi:noNamespaceSchemaLocation="../database.xsd">', *inner, "</database>", ""])


def generate_clothing_xml(mod_id: str, looks: list[tuple[CreatureDefinition, BaseBody]]) -> str:
    rows = []
    for creature, body in looks:
        row = {k: v for k, v in body.clothing.items()
               if k not in ("Name", "DefaultBody", "DefaultHair", "DefaultBeard", "DefaultHead")}
        row["Name"] = clothing_name(mod_id, creature)
        row["DefaultBody"] = clothing_name(mod_id, creature) + "_body"
        rows.append("\t\t<ClothingConfig " + " ".join(f"{k}={quoteattr(v)}" for k, v in row.items()) + " />")
    return _database(['\t<ClothingConfigs version="1">', *rows, "\t</ClothingConfigs>"])


def generate_component_xml(mod_id: str, looks: list[tuple[CreatureDefinition, BaseBody, str, str, str]]) -> str:
    """looks: (creature, body, folder under Objects/Characters/, skin file, material file)."""
    rows = []
    for creature, body, folder, skin, material in looks:
        name = clothing_name(mod_id, creature)
        rows += [f"\t\t<Component Name={quoteattr(name)} Race={quoteattr(body.race)} "
                 f"Gender={quoteattr(body.gender or 'NotDefined')} FilePath={quoteattr(folder)}>",
                 "\t\t\t<DerivedComponents>",
                 f"\t\t\t\t<Body Name={quoteattr(name + '_body')}>",
                 f"\t\t\t\t\t<Elements><SkinElement EquipmentPart={quoteattr(body.equipment_part)} BodyLayerId=\"0\" "
                 f"Model={quoteattr(skin)} Material={quoteattr(material)} /></Elements>",
                 "\t\t\t\t</Body>", "\t\t\t</DerivedComponents>", "\t\t</Component>"]
    return _database(['\t<CharacterComponents version="6">', *rows, "\t</CharacterComponents>"])


def soul_name(mod_id: str, creature: CreatureDefinition) -> str:
    return f"{mod_id}_{creature.creature_id}"


def soul_row(mod_id: str, creature: CreatureDefinition, body: BaseBody) -> dict[str, str]:
    # The template keeps brain, social and soul class of the base body; behaviour and identity are ours.
    row = dict(body.template)
    row.update({
        "soul_id": creature.soul_guid,
        "soul_name": soul_name(mod_id, creature),
        "factionName": attitude(creature.base_class, creature.attitude).faction,
        "combat_level": f"{max(0.0, min(1.0, creature.combat_level)):g}",
    })
    return row


def generate_soul_xml(mod_id: str, creatures: list[CreatureDefinition], bodies: dict[str, BaseBody]) -> str:
    lines = ['<?xml version="1.0" encoding="us-ascii"?>',
             '<database xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance" name="barbora" '
             'xsi:noNamespaceSchemaLocation="../database.xsd">',
             '\t<souls version="2">']
    for creature in creatures:
        row = soul_row(mod_id, creature, bodies[creature.base_class])
        attrs = " ".join(f"{k}={quoteattr(v)}" for k, v in sorted(row.items()))
        lines.append(f"\t\t<soul {attrs} />")
    lines += ["\t</souls>", "</database>", ""]
    return "\n".join(lines)


def registry_entry(mod_id: str, creature: CreatureDefinition, body: BaseBody) -> dict:
    entry = {"id": "creature:" + creature.creature_id, "name": creature.name,
             "category": "npcs" if creature.is_human else "animals", "spawn_type": "soul",
             "soul_guid": creature.soul_guid, "archetype": body.archetype, "entity_class": body.entity_class,
             "health": int(creature.health), "stats": creature.stats(),
             "status": "packaged_unverified", "source": "compiled_custom"}
    if creature.model_path:
        entry["model_path"] = creature.model_path
        if custom_look(creature, body):
            entry["clothing_config"] = clothing_name(mod_id, creature)
    return entry


def validate(creatures: list[CreatureDefinition], bodies: dict[str, BaseBody],
             models: dict[str, str]) -> list[tuple[str, str, str]]:
    """(severity, creature name, message); models maps a compiled .cdf path to its skeleton."""
    from creatures.gamedata import same_skeleton

    issues = []
    seen = set()
    for c in creatures:
        try:
            uuid.UUID(c.soul_guid)
        except ValueError:
            issues.append((ERROR, c.name, "Its soul id is damaged; delete and recreate the creature."))
        if c.soul_guid in seen:
            issues.append((ERROR, c.name, "Two creatures share one soul id; duplicate creatures need a new one."))
        seen.add(c.soul_guid)
        body = bodies.get(c.base_class)
        if body is None:
            issues.append((ERROR, c.name, f"The game has no '{c.base_class}' body."))
            continue
        if not 1 <= c.health <= 10000:
            issues.append((ERROR, c.name, "Health must be between 1 and 10000."))
        for name, value in c.stats().items():
            if value > 30:
                issues.append((WARNING, c.name, f"{name.title()} {value} is above the game's maximum of 30."))
        if c.model_path and c.is_human:
            issues.append((WARNING, c.name, "Custom models work for animals; people keep their game look."))
        if c.model_path:
            skeleton = models.get(c.model_path)
            if skeleton is None:
                issues.append((ERROR, c.name, f"Its model {c.model_path} is not exported. Export the asset as "
                               "Rigged from Blender, or pick the game's own look."))
            elif skeleton and not same_skeleton(skeleton, body.skeleton):
                issues.append((WARNING, c.name, f"The model's skeleton differs from the {c.base_class} body, so "
                               "its animations may look broken."))
    return issues
