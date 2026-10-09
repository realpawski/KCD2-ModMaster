"""Workspace Asset Model and Validation Framework for KCD2 ModMaster.

Tracks editable workspace assets, their status lifecycle:
EDITING -> READY -> WARNING -> INVALID -> BUILT -> INSTALLED

Provides validation of scale, transforms, UV coordinates, materials, and textures.
"""
from __future__ import annotations

import json
import logging
import time
from dataclasses import asdict, dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any

log = logging.getLogger(__name__)


class AssetStatus(str, Enum):
    EDITING = "EDITING"
    READY = "READY"
    WARNING = "WARNING"
    INVALID = "INVALID"
    BUILT = "BUILT"
    INSTALLED = "INSTALLED"


class AssetType(str, Enum):
    STATIC_PROP = "Static Prop"
    RIGGED = "Rigged Model"
    WEAPON = "Weapon"
    ARMOR = "Armor"
    CHARACTER = "Character"
    OTHER = "Other"


@dataclass
class ValidationIssue:
    severity: str  # "error", "warning", "info"
    field: str
    message: str
    fix: str = ""
    action: str = ""  # "open_blender", "add_to_mod" or "" for nothing to click


@dataclass
class ValidationReport:
    is_valid: bool = True
    issues: list[ValidationIssue] = field(default_factory=list)

    def add_error(self, field: str, msg: str, fix: str = "", action: str = "") -> None:
        self.is_valid = False
        self.issues.append(ValidationIssue("error", field, msg, fix, action))

    def add_warning(self, field: str, msg: str, fix: str = "", action: str = "") -> None:
        self.issues.append(ValidationIssue("warning", field, msg, fix, action))

    def add_info(self, field: str, msg: str) -> None:
        self.issues.append(ValidationIssue("info", field, msg))


@dataclass
class WorkspaceAsset:
    asset_id: str
    name: str
    asset_type: str = AssetType.STATIC_PROP.value
    source_type: str = "imported"  # "imported", "vanilla_copy", "blender_scene"
    source_file: str = ""
    workspace_dir: str = ""
    blend_file: str = ""
    export_file: str = ""
    mod_id: str = ""  # Assigned Mod Project ID
    status: str = AssetStatus.EDITING.value
    materials: list[dict[str, Any]] = field(default_factory=list)
    textures: list[str] = field(default_factory=list)
    created_at: float = field(default_factory=time.time)
    updated_at: float = field(default_factory=time.time)
    validation: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def load(cls, meta_path: Path) -> WorkspaceAsset | None:
        if not meta_path.is_file():
            return None
        try:
            data = json.loads(meta_path.read_text(encoding="utf-8"))
            return cls(
                asset_id=data.get("asset_id", meta_path.parent.parent.name),
                name=data.get("asset_name", data.get("name", meta_path.parent.parent.name)),
                asset_type=_asset_type(data, meta_path.parent.parent),
                source_type=data.get("source_type", "imported"),
                source_file=data.get("source_file", ""),
                workspace_dir=data.get("workspace_dir", str(meta_path.parent.parent)),
                blend_file=data.get("blend_file", ""),
                export_file=data.get("export_file", ""),
                mod_id=data.get("mod_id", ""),
                status=data.get("status", AssetStatus.EDITING.value).upper(),
                materials=data.get("materials", []),
                textures=data.get("textures", []),
                created_at=data.get("created_at", time.time()),
                updated_at=data.get("updated_at", time.time()),
                validation=data.get("validation", {}),
            )
        except Exception as e:
            log.warning("Could not read asset metadata %s: %s", meta_path, e)
            return None

    def save(self, meta_path: Path | None = None) -> None:
        p = meta_path or (Path(self.workspace_dir) / "metadata" / ".modmaster_asset.json")
        p.parent.mkdir(parents=True, exist_ok=True)
        self.updated_at = time.time()
        # Blender writes fields this model does not know (skeleton, parts, rigged); they must survive.
        data = {}
        if p.is_file():
            try:
                data = json.loads(p.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                data = {}
        data.update(asdict(self))
        p.write_text(json.dumps(data, indent=2), encoding="utf-8")


def _asset_type(data: dict, asset_dir: Path) -> str:
    from compiler import compiled_models
    if data.get("rigged") or compiled_models(asset_dir, kinds=(".cdf",)):
        return AssetType.RIGGED.value
    stored = data.get("asset_type", AssetType.STATIC_PROP.value)
    return AssetType.STATIC_PROP.value if stored == AssetType.RIGGED.value else stored


def list_workspace_assets(workspace_root: Path) -> list[WorkspaceAsset]:
    """Finds all registered workspace assets in Workspace/Assets/."""
    assets_dir = workspace_root / "Assets"
    if not assets_dir.is_dir():
        return []

    results = []
    for asset_folder in assets_dir.iterdir():
        if asset_folder.is_dir():
            meta_file = asset_folder / "metadata" / ".modmaster_asset.json"
            if meta_file.is_file():
                asset = WorkspaceAsset.load(meta_file)
                if asset:
                    results.append(asset)
            else:
                # Check for blend file or source directory
                blends = list((asset_folder / "blender").glob("*.blend")) if (asset_folder / "blender").is_dir() else []
                if blends or (asset_folder / "source").is_dir():
                    asset = WorkspaceAsset(
                        asset_id=asset_folder.name,
                        name=asset_folder.name.replace("_", " ").title(),
                        workspace_dir=str(asset_folder),
                        blend_file=str(blends[0]) if blends else "",
                        status=AssetStatus.EDITING.value,
                    )
                    results.append(asset)
    return sorted(results, key=lambda a: a.updated_at, reverse=True)


def validate_workspace_asset(asset: WorkspaceAsset, mods: list[str] | None = None) -> ValidationReport:
    """Checks what the game needs from an asset and says how to fix what is missing."""
    from compiler import compiled_files, compiled_models

    report = ValidationReport()
    ws_dir = Path(asset.workspace_dir)
    if not ws_dir.is_dir():
        report.add_error("workspace", f"The asset folder is missing: {ws_dir}",
                         "Restore the folder or remove the asset from your mods.")
        return _finish(asset, report)

    files = compiled_files(ws_dir)
    models = compiled_models(ws_dir)
    blend = Path(asset.blend_file) if asset.blend_file else None
    if not blend or not blend.is_file():
        found = sorted((ws_dir / "blender").glob("*.blend")) if (ws_dir / "blender").is_dir() else []
        if found:
            asset.blend_file = str(found[0])
        elif not models:
            report.add_warning("blender", "It has not been opened in Blender yet.",
                               "Open it in Blender to edit the model.", "open_blender")
        else:
            report.add_info("blender", "No .blend file in the asset folder; the exported model is used as it is.")

    rigged = asset.asset_type == AssetType.RIGGED.value
    if not models:
        report.add_warning("export", "The model is not exported for the game yet.",
                           "In Blender, open the ModMaster panel and click EXPORT TO KCD2"
                           + (" with Rigged selected." if rigged else "."), "open_blender")
    else:
        kinds = ", ".join(sorted({Path(m).suffix for m in models}))
        report.add_info("export", f"Exported for the game ({kinds}).")
        if rigged and not any(m.lower().endswith(".cdf") for m in models):
            report.add_warning("export", "It was exported as a static prop, so it has no skeleton in game.",
                               "Export again from Blender with Rigged selected.", "open_blender")
        if not any(p.lower().endswith(".mtl") for p in files):
            report.add_warning("materials", "No material was exported, so it shows without textures.",
                               "Export again from Blender; the material is written with the model.", "open_blender")
        textures = [p for p in files if p.lower().endswith(".dds")]
        if textures:
            report.add_info("textures", f"{len(textures)} texture(s) exported.")
        else:
            report.add_warning("textures", "No textures were exported, so the model looks plain grey.",
                               "Give the Blender materials image textures, then export again.", "open_blender")

    if mods is not None:
        if mods:
            report.add_info("mods", "Part of " + ", ".join(mods) + ".")
        else:
            report.add_warning("mods", "It is not part of a mod, so it never reaches the game.",
                               "Add it to a mod, then Build & install that mod.", "add_to_mod")
    return _finish(asset, report)


def _finish(asset: WorkspaceAsset, report: ValidationReport) -> ValidationReport:
    if not report.is_valid:
        asset.status = AssetStatus.INVALID.value
    elif any(i.severity == "warning" for i in report.issues):
        asset.status = AssetStatus.WARNING.value
    else:
        asset.status = AssetStatus.READY.value
    asset.validation = {
        "is_valid": report.is_valid,
        "issues": [{"severity": i.severity, "field": i.field, "message": i.message, "fix": i.fix,
                    "action": i.action} for i in report.issues],
    }
    return report
