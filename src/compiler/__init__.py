"""Compiled game files of workspace assets, as written by Export to KCD2 in Blender."""
from __future__ import annotations

import importlib.util
from functools import lru_cache
from pathlib import Path

COMPILED = "compiled"
_MODULE = Path(__file__).resolve().parents[1] / "blender" / "addon" / "KCD2_ModMaster_Bridge" / "cry_compile.py"


@lru_cache(maxsize=1)
def cry_compile():
    """The add-on's compiler module; it has no Blender imports, so it loads here too."""
    spec = importlib.util.spec_from_file_location("modmaster_cry_compile", _MODULE)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def compiled_files(asset_dir: Path) -> dict[str, Path]:
    """Game path -> file for everything under the asset's compiled folder."""
    root = Path(asset_dir) / COMPILED
    if not root.is_dir():
        return {}
    return {p.relative_to(root).as_posix(): p for p in sorted(root.rglob("*")) if p.is_file()}


def compiled_models(asset_dir: Path) -> list[str]:
    """Game paths of the compiled .cgf models in an asset."""
    return [path for path, file in compiled_files(asset_dir).items()
            if path.lower().endswith(".cgf") and file.read_bytes()[:4] == b"CrCh"]


def item_model_path(game_path: str) -> str:
    """Item tables store models relative to Objects/."""
    return game_path[len("Objects/"):] if game_path.lower().startswith("objects/") else game_path
