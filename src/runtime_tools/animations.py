"""Animation names a game skeleton can play, read from its .chrparams and animation databases."""
from __future__ import annotations

import fnmatch
import re
import zipfile
from pathlib import Path
from xml.etree import ElementTree as ET


def _game_files(game: Path) -> dict[str, tuple[Path, str]]:
    files: dict[str, tuple[Path, str]] = {}
    for pak in sorted((game / "Data").glob("*.pak")):
        try:
            with zipfile.ZipFile(pak) as z:
                for name in z.namelist():
                    files.setdefault(name.lower().replace("\\", "/"), (pak, name))
        except (OSError, zipfile.BadZipFile):
            continue
    return files


def _read(files: dict, path: str) -> bytes | None:
    hit = files.get(path.lower().replace("\\", "/"))
    if not hit:
        return None
    with zipfile.ZipFile(hit[0]) as z:
        return z.read(hit[1])


def animation_names(game: Path, skeleton: str) -> list[str]:
    files = _game_files(Path(game))
    params = _read(files, skeleton.rsplit(".", 1)[0] + ".chrparams")
    if not params:
        return []
    try:
        root = ET.fromstring(params)
    except ET.ParseError:
        return []
    names: set[str] = set()
    for anim in root.iter("Animation"):
        path = (anim.get("path") or "").replace("\\", "/").lower()
        if anim.get("name") == "$TracksDatabase" and path:
            for name in fnmatch.filter(files, path):
                data = _read(files, name) or b""
                names.update(m.decode().rsplit("/", 1)[-1][:-4]
                             for m in re.findall(rb"[A-Za-z0-9_/\\.]+\.caf", data))
    return sorted(names)


def default_animation(names: list[str]) -> str:
    for preference in ("relaxed_idle", "idle_loop", "idle"):
        hits = [n for n in names if preference in n.lower() and "to_" not in n.lower()]
        if hits:
            return min(hits, key=len)
    return names[0] if names else ""


def resolve_skeleton(game: Path, model: str, files: dict | None = None) -> str:
    """The .chr skeleton for a model path; a .skin is looked up through the game's .cdf files."""
    if model.lower().endswith(".chr") or not model:
        return model
    files = files if files is not None else _game_files(Path(game))
    folder = model.lower().replace("\\", "/").rsplit("/", 1)[0] + "/"
    target = model.lower().replace("\\", "/")
    candidates = sorted(name for name in files if name.startswith(folder) and name.endswith(".cdf"))
    for name in candidates:
        try:
            root = ET.fromstring(_read(files, name) or b"")
        except ET.ParseError:
            continue
        bindings = [(a.get("Binding") or "").lower().replace("\\", "/") for a in root.iter("Attachment")]
        model_node = root.find("Model")
        if target in bindings and model_node is not None and model_node.get("File"):
            return model_node.get("File")
    chrs = sorted(name for name in files if name.startswith(folder) and name.endswith(".chr")
                  and "skeleton" in name.rsplit("/", 1)[-1])
    return files[chrs[0]][1] if chrs else ""
