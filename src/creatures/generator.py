"""Game files for creatures: a split soul table and the in-game menu entries."""
from __future__ import annotations

import uuid
from xml.sax.saxutils import quoteattr

from creatures.gamedata import BaseBody
from creatures.model import CreatureDefinition, attitude

ERROR, WARNING = "error", "warning"


def soul_table_path(mod_id: str) -> str:
    return f"Libs/Tables/rpg/soul__{mod_id}.xml"


CLOTHING_TABLE = "Libs/Tables/Character/ClothingConfig.xml"
COMPONENT_TABLE = "Libs/Tables/Character/CharacterComponent.xml"


def clothing_name(mod_id: str, creature: CreatureDefinition) -> str:
    return f"{mod_id}_{creature.creature_id}"


def custom_look(creature: CreatureDefinition, body: BaseBody) -> bool:
    """Animals are dressed through a clothing config whose body skin a custom model can replace. People
    ignore such a config, and loading the model over them froze and crashed the game, so they keep the game look."""
    return bool(creature.model_path) and not creature.is_human and bool(body.clothing and body.equipment_part)


def look_rows(mod_id: str, creature: CreatureDefinition, body: BaseBody, folder: str, skin: str,
              material: str) -> dict[str, str]:
    """The ClothingConfig row and CharacterComponent that dress a creature in its own skin.

    The game only patches database tables from mods, not the character tables, so the in-game menu mod
    ships these rows merged into full copies of both tables."""
    name = clothing_name(mod_id, creature)
    row = {k: v for k, v in body.clothing.items()
           if k not in ("Name", "DefaultBody", "DefaultHair", "DefaultBeard", "DefaultHead", "DefaultClothingPreset")}
    row.update({"Name": name, "DefaultBody": name + "_body"})
    part = body.equipment_part
    if creature.is_human:
        # A person made in Blender is one complete mesh: no game head, hair or default outfit on top.
        row["HeadIsNeeded"] = "false"
        part = "torso"
    clothing = "<ClothingConfig " + " ".join(f"{k}={quoteattr(v)}" for k, v in row.items()) + " />"
    component = (f"<Component Name={quoteattr(name)} Race={quoteattr(body.race)} "
                 f"Gender={quoteattr(body.gender or 'NotDefined')} FilePath={quoteattr(folder)}>"
                 f"<DerivedComponents><Body Name={quoteattr(name + '_body')}><Elements>"
                 f"<SkinElement EquipmentPart={quoteattr(part)} BodyLayerId=\"0\" "
                 f"Model={quoteattr(skin)} Material={quoteattr(material)} /></Elements></Body></DerivedComponents>"
                 "</Component>")
    return {"name": name, "clothing": clothing, "component": component}


def merge_looks(clothing_xml: str, component_xml: str, looks: list[dict]) -> tuple[str, str]:
    """Adds the rows of every look to the game's tables; rows that are not exactly one element are refused."""
    from xml.etree import ElementTree as ET

    clothing_rows, component_rows = [], []
    for look in looks:
        clothing, component = ET.fromstring(look["clothing"]), ET.fromstring(look["component"])
        if clothing.tag != "ClothingConfig" or component.tag != "Component":
            raise ValueError(f"Creature look {look.get('name')} is malformed")
        clothing_rows.append("\t\t" + look["clothing"])
        component_rows.append("\t\t" + look["component"])
    if not looks:
        return clothing_xml, component_xml
    close_clothing = clothing_xml.rindex("</ClothingConfigs>")
    close_component = component_xml.rindex("</CharacterComponents>")
    return (clothing_xml[:close_clothing] + "\n".join(clothing_rows) + "\n\t" + clothing_xml[close_clothing:],
            component_xml[:close_component] + "\n".join(component_rows) + "\n\t" + component_xml[close_component:])


def soul_name(mod_id: str, creature: CreatureDefinition) -> str:
    return f"{mod_id}_{creature.creature_id}"


def soul_row(mod_id: str, creature: CreatureDefinition, body: BaseBody) -> dict[str, str]:
    # The template keeps social and soul class of the base body, and its brain unless the attitude brings one.
    row = dict(body.template)
    row.update({
        "soul_id": creature.soul_guid,
        "soul_name": soul_name(mod_id, creature),
        "factionName": attitude(creature.base_class, creature.attitude).faction,
        "combat_level": f"{max(0.0, min(1.0, creature.combat_level)):g}",
    })
    brain = attitude(creature.base_class, creature.attitude).brain
    if brain:
        row["brain_id"] = brain
    if creature.is_human and custom_look(creature, body):
        # The character name picks a game face and outfit, which would cover the creature's own model.
        row.pop("skald_character_name", None)
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


def registry_entry(mod_id: str, creature: CreatureDefinition, body: BaseBody, gaits: dict | None = None) -> dict:
    entry = {"id": "creature:" + creature.creature_id, "name": creature.name,
             "category": "npcs" if creature.is_human else "animals", "spawn_type": "soul",
             "soul_guid": creature.soul_guid, "archetype": body.archetype, "entity_class": body.entity_class,
             "health": int(creature.health), "stats": creature.stats(),
             "status": "packaged_unverified", "source": "compiled_custom"}
    if creature.attitude in ("companion", "ally"):
        entry["follow"] = True
        if gaits and not creature.is_human:
            entry["gaits"] = dict(gaits)
    if creature.attitude in ("companion", "ally", "domestic", "neutral"):
        entry["calm"] = True
    if custom_look(creature, body):
        entry["model_path"] = creature.model_path
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
            issues.append((WARNING, c.name, "People keep the game look for now; your own model works on animals."))
        if c.model_path:
            skeleton = models.get(c.model_path)
            if skeleton is None:
                issues.append((ERROR, c.name, f"Its model {c.model_path} is not exported. Export the asset as "
                               "Rigged from Blender, or pick the game's own look."))
            elif skeleton and not same_skeleton(skeleton, body.skeleton):
                issues.append((WARNING, c.name, f"The model's skeleton differs from the {c.base_class} body, so "
                               "its animations may look broken."))
    return issues
