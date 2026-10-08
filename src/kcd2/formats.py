"""KCD2 file types and the path-based asset classes shown in the UI."""
from __future__ import annotations

import re
from pathlib import PurePosixPath

# split texture mip chunks: name.dds.1 .. .dds.8, alpha: name.dds.a, .dds.1a ..
_TEX_PART_RE = re.compile(r"\.dds\.(\d+a?|a)$", re.I)

TYPE_GROUPS: dict[str, tuple[str, ...]] = {
    "CGF": ("cgf",),
    "CGFM": ("cgfm",),
    "CGA": ("cga",),
    "SKIN": ("skin",),
    "CHR": ("chr", "chrparams"),
    "MTL": ("mtl",),
    "Textures": ("dds", "tif", "png", "jpg"),
    "XML / Tables": ("xml", "tbl", "xsd"),
    "Scripts": ("lua", "ent"),
    "Animations": ("caf", "dba", "anm", "bspace", "comb", "adb", "animevents"),
}

EXT_LABELS = {
    "cgf": "Static mesh (CGF)",
    "cgfm": "Mesh data (CGFM)",
    "cga": "Animated geometry (CGA)",
    "skin": "Skinned mesh (SKIN)",
    "chr": "Character skeleton (CHR)",
    "chrparams": "Character params (XML)",
    "mtl": "Material (MTL, XML)",
    "dds": "Texture (DDS)",
    "dds-part": "Texture mip chunk",
    "tif": "Texture source (TIF)",
    "xml": "XML",
    "tbl": "Table (binary)",
    "lua": "Lua script",
    "caf": "Animation (CAF)",
    "dba": "Animation database (DBA)",
}

ASSET_CLASSES = ("Characters", "Weapons", "Armor", "Buildings", "Props")


def split_ext(vpath: str) -> tuple[str, bool]:
    """Return (extension-without-dot lowercased, is_texture_part)."""
    if _TEX_PART_RE.search(vpath):
        return "dds-part", True
    suf = PurePosixPath(vpath).suffix.lower()
    return suf[1:] if suf else "", False


def file_category(ext: str) -> str:
    for group, exts in TYPE_GROUPS.items():
        if ext in exts:
            return group
    if ext == "dds-part":
        return "Texture parts"
    return "Other"


def asset_class(vpath_lower: str) -> str:
    """Heuristic classification from the virtual folder (not authoritative)."""
    p = vpath_lower
    if "/weapons/" in p or p.startswith("objects/manmade/weapons"):
        return "Weapons"
    if any(k in p for k in ("armor", "armour", "helmet", "/hoods/", "gambeson", "/gloves/")):
        return "Armor"
    if p.startswith("objects/characters/"):
        return "Characters"
    if any(k in p for k in (
        "objects/manmade/structures/",
        "hlods/structures/",
        "/structures/",
        "/houses/",
        "/castles/",
        "/fortresses/",
        "/buildings/",
    )):
        return "Buildings"
    if p.startswith(("objects/manmade/", "objects/natural/", "objects/quest_items/")):
        return "Props"
    return ""


def pretty_path(vpath: str) -> str:
    """'Objects/manmade/weapons/swords/x.cgf' -> 'Manmade / Weapons / Swords / x.cgf'."""
    parts = vpath.replace("\\", "/").split("/")
    if len(parts) > 1 and parts[0].lower() == "objects":
        parts = parts[1:]
    dirs = [d.replace("_", " ").strip().title() for d in parts[:-1]]
    return " / ".join(dirs + [parts[-1]])


def pretty_folder(vpath: str) -> str:
    """Folder part of pretty_path ('Manmade / Weapons / Swords')."""
    p = pretty_path(vpath)
    return p.rsplit(" / ", 1)[0] if " / " in p else ""


def mtl_texture_candidates(ref: str, mtl_vpath: str) -> list[str]:
    """Virtual paths where a texture referenced from an .mtl may live.

    Confirmed: .mtl references use .tif source names while the archives
    contain .dds with the same stem. Paths may be './relative' or rooted.
    """
    r = ref.replace("\\", "/").strip()
    if not r:
        return []
    if r.startswith("./") or r.startswith("../") or "/" not in r:
        base = PurePosixPath(mtl_vpath).parent
        joined = []
        for seg in (base / r).parts:
            if seg == "..":
                if joined:
                    joined.pop()
            elif seg != ".":
                joined.append(seg)
        r = "/".join(joined)
    stem = r.rsplit(".", 1)[0] if "." in PurePosixPath(r).name else r
    out = [r]
    for e in (".dds", ".tif"):
        if stem + e != r:
            out.append(stem + e)
    return out
