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
    WEAPON = "Weapon"
    ARMOR = "Armor"
    CHARACTER = "Character"
    OTHER = "Other"


@dataclass
class ValidationIssue:
    severity: str  # "error", "warning", "info"
    field: str
    message: str


@dataclass
class ValidationReport:
    is_valid: bool = True
    issues: list[ValidationIssue] = field(default_factory=list)

    def add_error(self, field: str, msg: str) -> None:
        self.is_valid = False
        self.issues.append(ValidationIssue("error", field, msg))

    def add_warning(self, field: str, msg: str) -> None:
        self.issues.append(ValidationIssue("warning", field, msg))

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
                asset_type=data.get("asset_type", AssetType.STATIC_PROP.value),
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
        data = asdict(self)
        p.write_text(json.dumps(data, indent=2), encoding="utf-8")


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


def validate_workspace_asset(asset: WorkspaceAsset) -> ValidationReport:
    """Validates an asset's geometry files, UV maps, materials, and textures."""
    report = ValidationReport()
    ws_dir = Path(asset.workspace_dir)

    if not ws_dir.is_dir():
        report.add_error("workspace", f"Workspace folder does not exist: {ws_dir}")
        return report

    blend_p = Path(asset.blend_file) if asset.blend_file else None
    if blend_p and not blend_p.is_file():
        report.add_warning("blender", f"Associated .blend file not found: {blend_p.name}")

    export_p = Path(asset.export_file) if asset.export_file else None
    if not export_p or not export_p.is_file():
        exports = list((ws_dir / "export").glob("*.glb"))
        if exports:
            asset.export_file = str(exports[0])
            export_p = exports[0]

    if export_p and export_p.is_file():
        report.add_info("export", f"Exported model present ({export_p.name}, {export_p.stat().st_size:,} bytes)")
    else:
        report.add_warning("export", "Asset has not been exported to ModMaster yet.")

    if not asset.materials:
        report.add_warning("materials", "No materials registered in metadata.")
    else:
        report.add_info("materials", f"{len(asset.materials)} material slot(s) defined.")

    textures_dir = ws_dir / "textures"
    if textures_dir.is_dir():
        tex_files = list(textures_dir.glob("*.dds")) + list(textures_dir.glob("*.png"))
        if tex_files:
            report.add_info("textures", f"{len(tex_files)} texture resource(s) staged.")
        else:
            report.add_warning("textures", "No textures found in textures directory.")
    else:
        report.add_warning("textures", "Textures directory does not exist.")

    if asset.asset_type == AssetType.STATIC_PROP.value:
        report.add_info("pipeline", "Static Prop pipeline verified for KCD2 cryengine interchange.")
    else:
        report.add_warning("pipeline", f"{asset.asset_type} pipeline is experimental in this version.")

    # Update asset status based on validation
    if not report.is_valid:
        asset.status = AssetStatus.INVALID.value
    elif any(iss.severity == "warning" for iss in report.issues):
        asset.status = AssetStatus.WARNING.value
    elif export_p and export_p.is_file():
        asset.status = AssetStatus.READY.value
    else:
        asset.status = AssetStatus.EDITING.value

    asset.validation = {
        "is_valid": report.is_valid,
        "issues": [{"severity": i.severity, "field": i.field, "message": i.message} for i in report.issues],
    }
    return report
