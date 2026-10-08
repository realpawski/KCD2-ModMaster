"""Mod Project System for KCD2 ModMaster.

Manages ModMaster mod projects, their filesystem structure, metadata,
asset assignments, and build staging.
"""
from __future__ import annotations

import json
import logging
import re
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

log = logging.getLogger(__name__)


def slugify_mod_id(name: str) -> str:
    """KCD2 mod IDs may only contain lowercase letters and underscores (KM-A-57)."""
    s = re.sub(r"[^a-z]+", "_", name.strip().lower())
    s = re.sub(r"_+", "_", s).strip("_")
    return s[:64] or "my_mod"


@dataclass
class ModProject:
    id: str
    name: str
    author: str = ""
    version: str = "0.1.0"
    description: str = ""
    assets: list[str] = field(default_factory=list)  # List of asset IDs assigned to this mod
    created_at: float = field(default_factory=time.time)
    updated_at: float = field(default_factory=time.time)
    project_dir: str = ""

    @classmethod
    def load(cls, project_dir: Path) -> ModProject | None:
        meta_file = project_dir / "modmaster.json"
        if not meta_file.is_file():
            return None
        try:
            data = json.loads(meta_file.read_text(encoding="utf-8"))
            return cls(
                id=data.get("id", project_dir.name),
                name=data.get("name", project_dir.name),
                author=data.get("author", ""),
                version=data.get("version", "0.1.0"),
                description=data.get("description", ""),
                assets=data.get("assets", []),
                created_at=data.get("created_at", time.time()),
                updated_at=data.get("updated_at", time.time()),
                project_dir=str(project_dir),
            )
        except Exception as e:
            log.warning("Could not load mod project from %s: %s", project_dir, e)
            return None

    def save(self) -> None:
        p_dir = Path(self.project_dir)
        p_dir.mkdir(parents=True, exist_ok=True)
        meta_file = p_dir / "modmaster.json"
        self.updated_at = time.time()
        data = asdict(self)
        meta_file.write_text(json.dumps(data, indent=2), encoding="utf-8")

    def ensure_structure(self) -> None:
        """Ensures standard mod project folders exist."""
        p_dir = Path(self.project_dir)
        for sub in ("assets", "game", "build", "logs"):
            (p_dir / sub).mkdir(parents=True, exist_ok=True)

    def assign_asset(self, asset_id: str) -> None:
        if asset_id not in self.assets:
            self.assets.append(asset_id)
            self.save()

    def remove_asset(self, asset_id: str) -> None:
        if asset_id in self.assets:
            self.assets.remove(asset_id)
            self.save()


class ModManager:
    """Manages mod projects across the ModMaster workspace."""

    def __init__(self, workspace_root: Path):
        self.workspace_root = workspace_root
        self.mods_root = workspace_root / "Mods"
        self.mods_root.mkdir(parents=True, exist_ok=True)

    def list_mods(self) -> list[ModProject]:
        results = []
        if not self.mods_root.is_dir():
            return results
        for item in self.mods_root.iterdir():
            if item.is_dir():
                mod = ModProject.load(item)
                if mod:
                    results.append(mod)
        return sorted(results, key=lambda m: m.updated_at, reverse=True)

    def get_mod(self, mod_id: str) -> ModProject | None:
        for m in self.list_mods():
            if m.id == mod_id:
                return m
        return None

    def create_mod(
        self,
        name: str,
        mod_id: str = "",
        author: str = "",
        version: str = "0.1.0",
        description: str = "",
    ) -> ModProject:
        final_id = slugify_mod_id(mod_id or name)
        project_dir = self.mods_root / final_id
        project_dir.mkdir(parents=True, exist_ok=True)

        mod = ModProject(
            id=final_id,
            name=name,
            author=author,
            version=version,
            description=description,
            project_dir=str(project_dir),
        )
        mod.ensure_structure()
        mod.save()
        return mod
