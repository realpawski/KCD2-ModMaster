"""Persistent application configuration (JSON in %APPDATA%\\KCD2ModMaster)."""
from __future__ import annotations

import json
import logging
import os
from dataclasses import asdict, dataclass, field, fields
from pathlib import Path

log = logging.getLogger(__name__)


def app_data_dir() -> Path:
    base = os.environ.get("APPDATA") or str(Path.home())
    p = Path(base) / "KCD2ModMaster"
    p.mkdir(parents=True, exist_ok=True)
    return p


def default_workspace() -> Path:
    return Path.home() / "Documents" / "KCD2 ModMaster" / "Workspace"


@dataclass
class Settings:
    game_dir: str = ""
    tools_dir: str = ""
    blender_exe: str = ""
    workspace_dir: str = field(default_factory=lambda: str(default_workspace()))
    include_engine_paks: bool = True
    include_level_paks: bool = False
    include_media_paks: bool = False
    extract_companions: bool = True
    ask_extract_destination: bool = False
    show_virtual_path: bool = False
    show_texture_parts: bool = False
    window_geometry: str = ""
    browser_splitter_sizes: list[int] = field(default_factory=lambda: [520, 1000, 360])
    console_splitter_sizes: list[int] = field(default_factory=lambda: [720, 160])
    sidebar_compact: bool = False
    console_collapsed: bool = True
    default_author: str = ""
    check_updates_on_start: bool = True
    skipped_update: str = ""
    last_run_version: str = ""

    _path: Path | None = field(default=None, repr=False, compare=False)

    @classmethod
    def load(cls, path: Path | None = None) -> "Settings":
        path = path or (app_data_dir() / "config.json")
        s = cls()
        if path.exists():
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
                names = {f.name for f in fields(cls) if not f.name.startswith("_")}
                for k, v in data.items():
                    if k in names:
                        setattr(s, k, v)
            except (OSError, ValueError) as e:
                log.warning("Could not read settings file %s (%s). Using defaults.", path, e)
        s._path = path
        return s

    def save(self) -> None:
        path = self._path or (app_data_dir() / "config.json")
        data = {k: v for k, v in asdict(self).items() if not k.startswith("_")}
        tmp = path.with_suffix(".tmp")
        tmp.write_text(json.dumps(data, indent=2), encoding="utf-8")
        tmp.replace(path)

    @property
    def workspace(self) -> Path:
        return Path(self.workspace_dir or default_workspace())

    def workspace_sub(self, name: str) -> Path:
        p = self.workspace / name
        p.mkdir(parents=True, exist_ok=True)
        return p

    def ensure_workspace(self) -> None:
        for sub in ("extracted", "projects", "cache", "previews", "builds"):
            self.workspace_sub(sub)

    @property
    def database_path(self) -> Path:
        return self.workspace_sub("cache") / "asset_index.sqlite"
