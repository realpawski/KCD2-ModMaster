"""Game files for creatures: a split soul table and the in-game menu entries."""
from __future__ import annotations

import uuid
from xml.sax.saxutils import quoteattr

from creatures.gamedata import BaseBody
from creatures.model import CreatureDefinition, attitude

ERROR, WARNING = "error", "warning"


def soul_table_path(mod_id: str) -> str:
    return f"Libs/Tables/rpg/soul__{mod_id}.xml"


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
        if c.model_path:
            skeleton = models.get(c.model_path)
            if skeleton is None:
                issues.append((ERROR, c.name, f"Its model {c.model_path} is not exported. Export the asset as "
                               "Rigged from Blender, or pick the game's own look."))
            elif skeleton and not same_skeleton(skeleton, body.skeleton):
                issues.append((WARNING, c.name, f"The model's skeleton differs from the {c.base_class} body, so "
                               "its animations may look broken."))
    return issues
