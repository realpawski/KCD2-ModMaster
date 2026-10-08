"""Desktop draft registry. Runtime consumes only installed, owned build snapshots."""
from __future__ import annotations
import json
from pathlib import Path
from mods.project import ModManager
from workspace.asset_model import list_workspace_assets
from runtime_tools import REGISTRY_VERSION, RUNTIME_VERSION
from runtime_tools.packaging import read_spawn_descriptors

def generate_modmaster_registry(workspace_root: Path) -> dict:
    registry = {"format_version": REGISTRY_VERSION, "runtime_version": RUNTIME_VERSION, "mods": []}
    assets = {a.asset_id: a for a in list_workspace_assets(workspace_root)}
    for mod in ModManager(workspace_root).list_mods():
        try:
            declared = {a["id"]: a for a in read_spawn_descriptors(mod)}
            error = ""
        except (ValueError, KeyError, OSError) as exc:
            declared = {}; error = str(exc)
        entries = []
        for aid in mod.assets:
            asset = assets.get(aid)
            if aid in declared:
                entry = declared.pop(aid)
                entry["status"] = "build_and_install_required"
                entries.append(entry)
            elif asset:
                entries.append({"id": aid, "name": asset.name, "category": asset.asset_type,
                                "spawn_type": "unsupported", "status": error or "compiled_runtime_descriptor_required"})
        entries.extend(declared.values())
        registry["mods"].append({"id": mod.id, "name": mod.name, "version": mod.version,
                                 "author": mod.author, "assets": entries})
    output = workspace_root / "Mods/modmaster_registry.json"
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(registry, indent=2), encoding="utf-8")
    return registry
