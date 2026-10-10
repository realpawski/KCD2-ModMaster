"""Creature definitions stored with a mod and the behaviour choices they offer."""
from __future__ import annotations

import json
import re
import uuid
from dataclasses import asdict, dataclass, field, fields
from pathlib import Path

HUMAN_CLASSES = ("NPC", "NPC_Female")


@dataclass(frozen=True)
class Attitude:
    key: str
    label: str
    description: str
    faction: str
    brain: str = ""  # a game brain replacing the body's own; empty keeps it


# Factions decide who a creature treats as friend or enemy; the body's own AI decides how it moves and fights.
ANIMAL_ATTITUDES = (
    Attitude("wild", "Wild", "Natural instincts of the base animal: prey flees from people, boars defend "
             "themselves when hurt, predators keep away from towns.", "animal_wild"),
    Attitude("neutral", "Indifferent", "Ignores people and Henry. Only reacts when it is attacked.", "animal_wild_neutral"),
    Attitude("domestic", "Domestic", "Belongs to the village like farm animals. People treat it as theirs and "
             "guards react when someone harms it.", "animal_home"),
    Attitude("hostile", "Hostile", "Attacks Henry on sight, like the wolves in the game.", "animal_wild_enemy"),
    Attitude("companion", "Friend of Henry", "Follows Henry on its own legs with the body's walk, trot and "
             "gallop and stays close. Its own instincts still decide when it fights.", "animalCompanions"),
)

HUMAN_ATTITUDES = (
    Attitude("villager", "Villager", "Friendly local. Talks, works and flees or calls the guards when "
             "threatened.", "eventNPCs_civilians_friends"),
    Attitude("civilian", "Neutral civilian", "Minds their own business and only fights back when attacked.",
             "civilians"),
    Attitude("hostile", "Hostile", "Attacks Henry on sight, like bandits.", "eventNPCs_enemies"),
    Attitude("ally", "Ally of Henry", "Follows Henry and fights on his side.", "players_friends"),
)

# How each game body behaves on its own; shown so the choice of base animal is informed.
TEMPERAMENTS = {
    "Boar": "Grazes and roams. Keeps its distance from people but charges hard when hurt or cornered.",
    "Wolf": "Pack predator. Roams, hunts and fights with bites and lunges.",
    "WildDog": "Feral dog. Roams in packs and bites when it attacks.",
    "Dog": "Village dog. Wanders, barks at strangers and bites when it fights.",
    "Hare": "Prey animal. Bolts away the moment it notices someone.",
    "RoeDeerBuck": "Prey animal. Flees quickly when it notices people.",
    "RoeDeerHind": "Prey animal. Flees quickly when it notices people.",
    "RedDeerStag": "Large deer. Flees from people.",
    "RedDeerDoe": "Large deer. Flees from people.",
    "Pig": "Farm animal. Calm, wanders and runs off when attacked.",
    "SheepEwe": "Farm animal. Calm, stays with the flock and runs off when attacked.",
    "SheepRam": "Farm animal. Calm, stays with the flock and runs off when attacked.",
    "CattleCow": "Farm animal. Slow and calm, moves away when attacked.",
    "CattleBull": "Large farm animal. Calm unless provoked.",
    "Horse": "Grazes and wanders. Can be ridden once it belongs to Henry.",
    "Raven": "Bird. Hops around and flies off when disturbed.",
    "NPC": "Man with a daily routine. Walks, works, talks and fights with weapons he carries.",
    "NPC_Female": "Woman with a daily routine. Walks, works and talks.",
}

STAT_NAMES = ("strength", "agility", "vitality")


def attitudes_for(base_class: str) -> tuple[Attitude, ...]:
    return HUMAN_ATTITUDES if base_class in HUMAN_CLASSES else ANIMAL_ATTITUDES


def attitude(base_class: str, key: str) -> Attitude:
    options = attitudes_for(base_class)
    return next((a for a in options if a.key == key), options[0])


def slug(text: str) -> str:
    value = re.sub(r"[^a-z0-9_]+", "_", text.lower()).strip("_")
    return value or "creature"


@dataclass
class CreatureDefinition:
    creature_id: str
    name: str
    base_class: str = "Boar"
    soul_guid: str = field(default_factory=lambda: str(uuid.uuid4()))
    workspace_asset_id: str = ""
    model_path: str = ""
    attitude: str = "wild"
    combat_level: float = 0.5
    health: int = 100
    strength: int = 0
    agility: int = 0
    vitality: int = 0

    @property
    def is_human(self) -> bool:
        return self.base_class in HUMAN_CLASSES

    def stats(self) -> dict[str, int]:
        """Stats that differ from the game default (0 keeps the soul's own value)."""
        return {name: getattr(self, name) for name in STAT_NAMES if getattr(self, name) > 0}

    def save(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(asdict(self), indent=2), encoding="utf-8")

    @classmethod
    def load(cls, path: Path) -> "CreatureDefinition | None":
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return None
        known = {f.name for f in fields(cls)}
        try:
            return cls(**{k: v for k, v in data.items() if k in known})
        except TypeError:
            return None
