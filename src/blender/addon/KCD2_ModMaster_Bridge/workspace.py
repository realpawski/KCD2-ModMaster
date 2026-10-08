"""Workspace path resolution and explorer helpers for Blender Bridge."""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path


def open_folder_in_explorer(folder_path: str | Path) -> bool:
    """Opens the specified directory in the OS file manager (Windows Explorer)."""
    p = Path(folder_path)
    if not p.exists():
        try:
            p.mkdir(parents=True, exist_ok=True)
        except Exception:
            return False

    if sys.platform == "win32":
        try:
            os.startfile(str(p))
            return True
        except Exception:
            try:
                subprocess.Popen(["explorer", str(p)])
                return True
            except Exception:
                return False
    return False


def get_asset_paths(workspace_dir: str | Path, asset_name: str) -> dict[str, Path]:
    """Returns standardized paths for an asset workspace."""
    ws = Path(workspace_dir)
    return {
        "root": ws,
        "source": ws / "source",
        "textures": ws / "textures",
        "blender": ws / "blender",
        "export": ws / "export",
        "metadata": ws / "metadata",
        "blend_file": ws / "blender" / f"{asset_name}.blend",
        "meta_file": ws / "metadata" / ".modmaster_asset.json",
        "interchange": ws / "source" / f"{asset_name}_interchange.glb",
        "export_glb": ws / "export" / f"{asset_name}_exported.glb",
        "export_dae": ws / "export" / f"{asset_name}_exported.dae",
    }
