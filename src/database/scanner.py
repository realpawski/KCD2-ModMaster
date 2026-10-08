"""Scans KCD2 .pak archives into the SQLite index (runs in a worker thread)."""
from __future__ import annotations

import logging
import time
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from pathlib import Path

from archives.pak import PakArchive, PakError
from core.config import Settings
from core.tasks import TaskContext, UserFacingError
from database.index import AssetIndex
from kcd2.formats import asset_class, file_category, split_ext

log = logging.getLogger(__name__)

MEDIA_PREFIXES = ("videos", "ipl_videos", "music", "sounds")
MTL_MAX_BYTES = 2 * 1024 * 1024


@dataclass
class PakSource:
    path: Path
    group: str


def collect_paks(settings: Settings) -> list[PakSource]:
    game = Path(settings.game_dir)
    data = game / "Data"
    if not data.is_dir():
        raise UserFacingError(
            f"Could not find the KCD2 Data folder.\n\nExpected:\n{data}\n\n"
            "Open Settings to update your KCD2 installation path."
        )
    out: list[PakSource] = []
    for p in sorted(data.glob("*.pak")):
        if not settings.include_media_paks and p.name.lower().startswith(MEDIA_PREFIXES):
            continue
        out.append(PakSource(p, "Data"))
    if settings.include_level_paks:
        for p in sorted((data / "Levels").rglob("*.pak")):
            out.append(PakSource(p, f"Levels/{p.parent.name}"))
    if settings.include_engine_paks:
        for p in sorted((game / "Engine").glob("*.pak")):
            out.append(PakSource(p, "Engine"))
    return out


def _parse_mtl_textures(data: bytes) -> list[tuple[str, str, str]]:
    """Return (texture file, Map slot, owning sub-material name). Plain XML confirmed."""
    root = ET.fromstring(data)
    out = []

    def walk(el, owner):
        name = el.get("Name") or owner
        for tex_parent in el.findall("Textures"):
            for t in tex_parent.findall("Texture"):
                f = t.get("File")
                if f:
                    out.append((f, t.get("Map", ""), name or ""))
        for sub in el.findall("SubMaterials"):
            for m in sub.findall("Material"):
                walk(m, m.get("Name", ""))

    walk(root, root.get("Name", ""))
    return out


def scan(ctx: TaskContext, settings: Settings, force: bool = False) -> dict:
    t0 = time.time()
    paks = collect_paks(settings)
    if not paks:
        raise UserFacingError("No .pak archives found to scan. Check the KCD2 path in Settings.")
    idx = AssetIndex(settings.database_path)
    try:
        current = {str(p.path) for p in paks}
        removed = idx.remove_archives_not_in(current)
        scanned = skipped = total_entries = mtl_ok = mtl_fail = 0
        for i, src in enumerate(paks):
            ctx.progress(i, len(paks), f"Scanning {src.path.name}")
            st = src.path.stat()
            rec = idx.archive_record(str(src.path))
            if rec and not force and rec[1] == st.st_size and abs((rec[2] or 0) - st.st_mtime) < 1e-3:
                skipped += 1
                continue
            try:
                with PakArchive(src.path) as pak:
                    aid = idx.replace_archive(str(src.path), src.path.name, src.group, st.st_size, st.st_mtime)
                    rows, mtls = [], []
                    for e in pak.entries():
                        ext, is_part = split_ext(e.vpath)
                        low = e.vpath.lower()
                        rows.append((aid, e.vpath, low, e.vpath.rsplit("/", 1)[-1], ext,
                                     file_category(ext), asset_class(low), e.size, e.csize, int(is_part)))
                    idx.conn.executemany(
                        "INSERT INTO assets(archive_id, vpath, vpath_lower, filename, ext, category, asset_class, "
                        "size, csize, is_part) VALUES(?,?,?,?,?,?,?,?,?,?)", rows)
                    idx.conn.execute("UPDATE archives SET entry_count=? WHERE id=?", (len(rows), aid))
                    total_entries += len(rows)
                    # parse material texture references (.mtl is plain XML – confirmed)
                    for asset_id, vpath, size in idx.conn.execute(
                        "SELECT id, vpath, size FROM assets WHERE archive_id=? AND ext='mtl'", (aid,)
                    ).fetchall():
                        if size > MTL_MAX_BYTES:
                            continue
                        try:
                            for f, slot, owner in _parse_mtl_textures(pak.read(vpath)):
                                mtls.append((asset_id, "texture", f, slot, owner))
                            mtl_ok += 1
                        except (ET.ParseError, PakError, UnicodeError):
                            mtl_fail += 1
                    idx.conn.executemany(
                        "INSERT INTO asset_refs(asset_id, kind, ref, detail, owner) VALUES(?,?,?,?,?)", mtls)
                idx.conn.commit()
                scanned += 1
                log.info("Indexed %s (%d entries)", src.path.name, len(rows))
            except PakError as e:
                idx.conn.rollback()
                log.error("Skipped %s: %s", src.path.name, e)
        idx.set_meta("last_scan", time.strftime("%Y-%m-%d %H:%M"))
        idx.set_meta("game_dir", settings.game_dir)
        idx.conn.commit()
        ctx.progress(len(paks), len(paks), "Scan complete")
        result = {
            "archives": len(paks), "scanned": scanned, "skipped": skipped, "removed": removed,
            "entries": total_entries, "mtl_parsed": mtl_ok, "mtl_failed": mtl_fail,
            "seconds": round(time.time() - t0, 1), **idx.stats(),
        }
        return result
    finally:
        idx.close()
