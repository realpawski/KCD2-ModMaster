"""Metadata management for KCD2 ModMaster Blender Bridge.

Handles .modmaster_asset.json reading/writing and Blender custom properties.
"""
from __future__ import annotations

import json
import logging
import time
from pathlib import Path
from typing import Any

log = logging.getLogger("KCD2_ModMaster_Bridge.metadata")

BRIDGE_VERSION = "1.2.0"


def default_asset_metadata(
    asset_id: str,
    asset_name: str,
    vpath: str,
    archive_name: str,
    workspace_dir: str,
    interchange_file: str,
    blend_file: str,
    export_file: str = "",
    dae_export_file: str = "",
    project_name: str = "Default Project",
) -> dict[str, Any]:
    """Generates the standardized .modmaster_asset.json structure."""
    return {
        "version": BRIDGE_VERSION,
        "asset_id": asset_id,
        "asset_name": asset_name,
        "virtual_path": vpath,
        "source_archive": archive_name,
        "project": project_name,
        "workspace_dir": str(workspace_dir),
        "source_dir": str(Path(workspace_dir) / "source"),
        "textures_dir": str(Path(workspace_dir) / "textures"),
        "blend_file": str(blend_file),
        "interchange_file": str(interchange_file),
        "export_dir": str(Path(workspace_dir) / "export"),
        "export_file": str(export_file or (Path(workspace_dir) / "export" / f"{asset_name}_exported.glb")),
        "dae_export_file": str(dae_export_file or (Path(workspace_dir) / "export" / f"{asset_name}_exported.dae")),
        "status": "unmodified",
        "created_at": time.time(),
        "last_exported": None,
        "blender_version": "",
    }


def load_asset_metadata(meta_path: str | Path) -> dict[str, Any] | None:
    """Safely loads metadata from a .modmaster_asset.json file."""
    p = Path(meta_path)
    if not p.is_file():
        return None
    try:
        with open(p, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception as e:
        log.warning("Could not read asset metadata %s: %s", meta_path, e)
        return None


def save_asset_metadata(meta_path: str | Path, data: dict[str, Any]) -> bool:
    """Safely writes metadata to a .modmaster_asset.json file."""
    p = Path(meta_path)
    try:
        p.parent.mkdir(parents=True, exist_ok=True)
        tmp = p.with_suffix(".tmp")
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2)
        tmp.replace(p)
        return True
    except Exception as e:
        log.warning("Could not save asset metadata %s: %s", meta_path, e)
        return False


def tag_blender_entities(
    scene: Any,
    collection: Any,
    objects: list[Any],
    metadata: dict[str, Any],
) -> None:
    """Tags Blender scene, collection, and objects with persistent custom properties."""
    asset_id = metadata.get("asset_id", "")
    vpath = metadata.get("virtual_path", "")
    project = metadata.get("project", "Default Project")
    workspace = metadata.get("workspace_dir", "")
    meta_json = json.dumps(metadata)

    if scene:
        scene["modmaster_project"] = project
        scene["modmaster_active_asset"] = metadata.get("asset_name", "")
        scene["modmaster_asset_id"] = asset_id
        scene["modmaster_workspace"] = workspace
        scene["modmaster_meta_json"] = meta_json

    mtl_path = metadata.get("mtl_path", "")

    if collection:
        collection["modmaster_asset_id"] = asset_id
        collection["modmaster_virtual_path"] = vpath
        collection["modmaster_workspace"] = workspace
        collection["modmaster_meta_json"] = meta_json

    for obj in objects:
        if obj:
            obj["modmaster_asset_id"] = asset_id
            obj["modmaster_virtual_path"] = vpath
            obj["kcd2_source_path"] = vpath
            obj["kcd2_asset_id"] = asset_id
            obj["kcd2_mtl_path"] = mtl_path
            if obj.type == "MESH":
                obj["kcd2_submesh_count"] = len(obj.material_slots)


def get_active_asset_metadata(scene: Any) -> dict[str, Any] | None:
    """Retrieves active asset metadata from Blender scene custom properties."""
    if not scene:
        return None
    raw = scene.get("modmaster_meta_json")
    if raw:
        try:
            meta = json.loads(raw)
            # Texture Sync updates disk metadata while an existing .blend keeps
            # its old scene JSON. Rebuild reads current material data only.
            workspace = meta.get("workspace_dir")
            if workspace:
                disk = load_asset_metadata(Path(workspace) / "metadata" / ".modmaster_asset.json")
                if disk and disk.get("asset_id") == meta.get("asset_id"):
                    for key in ("materials", "textures_dir", "mtl_path", "material_schema_version"):
                        if key in disk: meta[key] = disk[key]
            return meta
        except Exception:
            pass
    return None
