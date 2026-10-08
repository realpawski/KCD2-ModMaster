"""Preview cache manager.

Stores converted models and metadata in:
    <workspace>/cache/previews/<asset_hash>/
"""
from __future__ import annotations

import hashlib
import json
import logging
import shutil
from dataclasses import asdict, dataclass, field
from pathlib import Path

log = logging.getLogger(__name__)


@dataclass
class PreviewMetadata:
    vpath: str
    filename: str
    archive_name: str
    file_size: int
    triangles: int
    vertices: int
    dim_x: float  # width in meters
    dim_y: float  # height in meters
    dim_z: float  # depth in meters
    bounds_min: list[float]  # [x, y, z]
    bounds_max: list[float]  # [x, y, z]
    lods: list[dict]  # list of { "lod": 0, "filename": "...", "vpath": "...", "tris": 1234, "verts": 567 }
    created_at: float
    textures_resolved: int = 0
    textures_total: int = 0
    missing_textures: list[str] = field(default_factory=list)
    materials: list[dict] = field(default_factory=list)


CACHE_VERSION: int = 4


def compute_asset_hash(vpath: str, archive_name: str, file_size: int) -> str:
    """Stable hash representing a unique asset revision.
    Includes CACHE_VERSION to invalidate old cached models when pipeline updates."""
    raw = f"v{CACHE_VERSION}|{vpath.lower().strip()}|{archive_name.lower().strip()}|{file_size}"
    return hashlib.sha1(raw.encode("utf-8")).hexdigest()[:16]


class PreviewCache:
    def __init__(self, workspace_root: Path):
        self.root = Path(workspace_root) / "cache" / "previews"
        self.root.mkdir(parents=True, exist_ok=True)

    def cache_dir(self, hash_key: str) -> Path:
        d = self.root / hash_key
        d.mkdir(parents=True, exist_ok=True)
        return d

    def has_preview(self, hash_key: str) -> bool:
        d = self.root / hash_key
        glb = d / "model.glb"
        meta = d / "metadata.json"
        return glb.is_file() and meta.is_file() and glb.stat().st_size > 0

    def get_glb_path(self, hash_key: str) -> Path | None:
        p = self.root / hash_key / "model.glb"
        return p if p.is_file() else None

    def get_metadata(self, hash_key: str) -> PreviewMetadata | None:
        p = self.root / hash_key / "metadata.json"
        if not p.is_file():
            return None
        try:
            data = json.loads(p.read_text(encoding="utf-8"))
            data.setdefault("textures_resolved", 0)
            data.setdefault("textures_total", 0)
            data.setdefault("missing_textures", [])
            data.setdefault("materials", [])
            return PreviewMetadata(**data)
        except Exception as e:
            log.warning("Failed to parse cached metadata %s: %s", p, e)
            return None

    def save_metadata(self, hash_key: str, meta: PreviewMetadata) -> None:
        p = self.cache_dir(hash_key) / "metadata.json"
        p.write_text(json.dumps(asdict(meta), indent=2), encoding="utf-8")

    def store_glb(self, hash_key: str, source_glb: Path) -> Path:
        dest = self.cache_dir(hash_key) / "model.glb"
        shutil.copyfile(source_glb, dest)
        return dest

    def clear(self) -> int:
        count = 0
        if self.root.exists():
            for child in self.root.iterdir():
                if child.is_dir():
                    shutil.rmtree(child, ignore_errors=True)
                    count += 1
        return count
