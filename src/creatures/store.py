"""Creature definitions of one mod, stored as <mod>/creatures/*.json."""
from __future__ import annotations

from pathlib import Path

from creatures.model import CreatureDefinition, slug

CREATURES_DIR = "creatures"


class CreatureStore:
    def __init__(self, project):
        self.project = project
        self.root = Path(project.project_dir) / CREATURES_DIR

    def list(self) -> list[CreatureDefinition]:
        if not self.root.is_dir():
            return []
        found = [CreatureDefinition.load(p) for p in sorted(self.root.glob("*.json"))]
        return sorted((c for c in found if c), key=lambda c: c.name.lower())

    def unique_id(self, wanted: str) -> str:
        base = slug(wanted)
        taken = {c.creature_id for c in self.list()}
        candidate, n = base, 2
        while candidate in taken:
            candidate = f"{base}_{n}"
            n += 1
        return candidate

    def save(self, creature: CreatureDefinition) -> Path:
        path = self.root / f"{creature.creature_id}.json"
        creature.save(path)
        return path

    def delete(self, creature: CreatureDefinition) -> None:
        path = self.root / f"{creature.creature_id}.json"
        if path.is_file():
            path.unlink()
