"""Persistence of the item definitions that belong to one mod project."""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from items.models import GameItemDefinition, slug

ITEMS_DIR = "items"


@dataclass
class StoredItem:
    item: GameItemDefinition
    path: Path
    asset_dir: Path | None = None


class ModItemStore:
    """Items live in <mod>/items/*.json. Items defined on a workspace asset before
    format 2 stay where they are and are found through the mod's assigned assets."""

    def __init__(self, project, workspace: Path):
        self.project = project
        self.workspace = Path(workspace)
        self.root = Path(project.project_dir) / ITEMS_DIR

    def list(self) -> list[StoredItem]:
        result: list[StoredItem] = []
        if self.root.is_dir():
            for path in sorted(self.root.glob("*.json")):
                item = GameItemDefinition.load_from_file(path)
                if item:
                    result.append(StoredItem(item, path, self.asset_dir_for(item)))
        for asset_id in getattr(self.project, "assets", []) or []:
            asset_dir = self.workspace / "Assets" / asset_id
            for path in (asset_dir / "metadata" / ".modmaster_item.json", asset_dir / ".modmaster_item.json"):
                item = GameItemDefinition.load_from_file(path)
                if item:
                    if not item.workspace_asset_id:
                        item.workspace_asset_id = asset_id
                    result.append(StoredItem(item, path, asset_dir))
                    break
        result.sort(key=lambda s: (s.item.display_name or s.item.name).lower())
        return result

    def asset_dir_for(self, item: GameItemDefinition) -> Path | None:
        if not item.workspace_asset_id:
            return None
        return self.workspace / "Assets" / item.workspace_asset_id

    def items(self) -> list[GameItemDefinition]:
        return [s.item for s in self.list()]

    def unique_item_id(self, wanted: str) -> str:
        base = slug(wanted)
        taken = {s.item.item_id for s in self.list()}
        candidate, n = base, 2
        while candidate in taken:
            candidate = f"{base}_{n}"
            n += 1
        return candidate

    def path_for(self, item: GameItemDefinition) -> Path:
        for stored in self.list():
            if stored.item.item_id == item.item_id:
                return stored.path
        return self.root / f"{item.item_id}.json"

    def save(self, item: GameItemDefinition) -> Path:
        path = self.path_for(item)
        item.save_to_file(path)
        return path

    def delete(self, item: GameItemDefinition) -> None:
        path = self.path_for(item)
        if path.parent == self.root and path.is_file():
            path.unlink()
        elif path.is_file():
            path.rename(path.with_suffix(".json.removed"))
