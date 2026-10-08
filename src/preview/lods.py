"""LOD asset family grouping and detection."""
from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import PurePosixPath

from database.index import AssetIndex, AssetRow

_LOD_SUFFIX_RE = re.compile(r"_lod(\d+)$", re.IGNORECASE)


@dataclass
class LodItem:
    level: int  # 0 for base, 1 for lod1, etc.
    label: str  # "LOD 0", "LOD 1"
    row: AssetRow
    companion_row: AssetRow | None = None
    triangles: int = 0
    vertices: int = 0


@dataclass
class LodFamily:
    base_name: str
    lods: list[LodItem]  # sorted by level (0, 1, 2, ...)

    @property
    def has_multiple_lods(self) -> bool:
        return len(self.lods) > 1

    def get_lod(self, level: int) -> LodItem | None:
        for item in self.lods:
            if item.level == level:
                return item
        return None


def extract_base_stem(filename: str) -> tuple[str, int]:
    """Returns (base_stem_without_ext_or_lod, lod_level).

    Examples:
        'polearm_pile_a.cgf' -> ('polearm_pile_a', 0)
        'polearm_pile_a_lod1.cgf' -> ('polearm_pile_a', 1)
        'helmet_lod2.cgf' -> ('helmet', 2)
    """
    stem = PurePosixPath(filename).stem
    m = _LOD_SUFFIX_RE.search(stem)
    if m:
        base = stem[: m.start()]
        level = int(m.group(1))
        return base, level
    return stem, 0


def find_lod_family(index: AssetIndex, target_row: AssetRow, conn=None) -> LodFamily:
    """Finds all related LOD variants for a given 3D asset row."""
    ext = target_row.ext.lower()
    if ext not in ("cgf", "skin", "chr", "cga"):
        # For non-mesh assets, family is just the single item
        return LodFamily(target_row.filename, [LodItem(0, "LOD 0", target_row)])

    base_stem, current_level = extract_base_stem(target_row.filename)
    folder = target_row.vpath.rsplit("/", 1)[0] if "/" in target_row.vpath else ""

    # Look for candidate files in the same folder or with matching base stem
    # Base asset: {base_stem}.{ext}
    # LODs: {base_stem}_lod1.{ext}, {base_stem}_lod2.{ext}, etc.
    candidates, _ = index.search(base_stem, type_group=ext.upper(), limit=50, conn=conn)

    lod_map: dict[int, AssetRow] = {}
    for cand in candidates:
        cand_ext = cand.ext.lower()
        if cand_ext != ext:
            continue
        cand_stem, lvl = extract_base_stem(cand.filename)
        if cand_stem.lower() == base_stem.lower():
            # If in the same directory or unique match
            cand_folder = cand.vpath.rsplit("/", 1)[0] if "/" in cand.vpath else ""
            if not folder or cand_folder.lower() == folder.lower() or len(candidates) <= 6:
                lod_map[lvl] = cand

    # Ensure at least the target item is present
    if current_level not in lod_map:
        lod_map[current_level] = target_row

    items: list[LodItem] = []
    for lvl in sorted(lod_map.keys()):
        row = lod_map[lvl]
        comps = index.companions(row)
        cgfm_comp = next((c for c in comps if c.ext.lower() == (ext + "m")), None)
        items.append(
            LodItem(
                level=lvl,
                label=f"LOD {lvl}",
                row=row,
                companion_row=cgfm_comp,
            )
        )

    return LodFamily(base_stem, items)
