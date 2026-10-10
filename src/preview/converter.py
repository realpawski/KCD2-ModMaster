"""Conversion pipeline: CGF/SKIN to GLB using official/toolkit KCD2-Convertor."""
from __future__ import annotations

import logging
import os
import posixpath
import re
import shutil
import struct
import subprocess
import time
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Callable

from archives.pak import PakArchive, PakError
from core.config import Settings
from core.tasks import UserFacingError
from database.index import AssetIndex, AssetRow
from preview.cache import (
    PreviewCache,
    PreviewMetadata,
    compute_asset_hash,
)
from preview.gltf_loader import MeshGeometry, load_glb
from preview.lods import find_lod_family
from materials.dds_combiner import combine_cryengine_dds
from materials.mtl_parser import parse_mtl_xml

log = logging.getLogger(__name__)


CONVERTER_MISSING = (
    "KCD2-Convertor.exe not found. It comes with the KCD2 Blender Toolkit add-on by Lune: install it in "
    "Blender (Edit > Preferences > Add-ons > Install from Disk), then try again. "
    "Alternatively copy KCD2-Convertor.exe into {tools}."
)


def converter_missing_message(settings: Settings | None = None) -> str:
    tools = settings.workspace / "tools" if settings else Path("<workspace>/tools")
    return CONVERTER_MISSING.format(tools=tools)


def _blender_roots(settings: Settings | None) -> list[Path]:
    roots = []
    appdata = os.environ.get("APPDATA", "")
    if appdata:
        roots.append(Path(appdata, "Blender Foundation", "Blender"))
    blender = getattr(settings, "blender_exe", "") if settings else ""
    if blender:
        # Portable Blender and add-ons installed next to the program live beside blender.exe.
        roots.append(Path(blender).parent)
    return roots


def find_converter_exe(settings: Settings | None = None) -> Path | None:
    """KCD2-Convertor.exe from the KCD2 Blender Toolkit, wherever Blender keeps the add-on, or the workspace."""
    if settings:
        own = settings.workspace / "tools" / "KCD2-Convertor.exe"
        if own.is_file():
            return own
    # Add-ons sit under scripts/addons; Blender 4.2+ extensions under extensions/<repo>; a zip
    # installed from GitHub adds one more folder level (KCD2-Blender-Toolkit-0.3.2/io_KCD2_Blender_Toolkit).
    patterns = ("*/scripts/addons/*/External/KCD2-Convertor/KCD2-Convertor.exe",
                "*/scripts/addons/*/*/External/KCD2-Convertor/KCD2-Convertor.exe",
                "*/extensions/*/*/External/KCD2-Convertor/KCD2-Convertor.exe",
                "*/extensions/*/*/*/External/KCD2-Convertor/KCD2-Convertor.exe")
    for root in _blender_roots(settings):
        if not root.is_dir():
            continue
        found = sorted((p for pattern in patterns for p in root.glob(pattern) if p.is_file()), reverse=True)
        if found:
            return found[0]
    return None


def extract_cgf_material_name(cgf_bytes: bytes) -> str | None:
    """Extracts embedded ChunkType_MtlName (0x1014 / 0x0014) from CryEngine CGF/CGFM data."""
    if len(cgf_bytes) < 16 or cgf_bytes[:4] != b"CrCh":
        return None
    try:
        ver, count, offset = struct.unpack_from("<III", cgf_bytes, 4)
        for i in range(count):
            entry = cgf_bytes[offset + i * 16 : offset + (i + 1) * 16]
            if len(entry) < 16:
                break
            c_type, c_ver, c_val1, c_val2 = struct.unpack("<IIII", entry)
            if (c_type & 0xFFFF) in (0x1014, 0x0014):
                file_off = c_val2
                size = c_val1
                if 0 <= file_off < len(cgf_bytes):
                    raw = cgf_bytes[file_off : file_off + size]
                    parts = [p.decode("latin1", errors="replace").strip() for p in raw.split(b"\x00") if p.strip()]
                    for p in parts:
                        if "/" in p or "\\" in p or len(p) > 2:
                            clean = p.replace("\\", "/").strip()
                            if clean.lower().endswith(".mtl"):
                                clean = clean[:-4]
                            return clean
    except Exception as e:
        log.debug("Error extracting CGF material name chunk: %s", e)
    return None


class PreviewGenerationError(UserFacingError):
    pass


# Material path embedded only by ClipVolumes. Many cv_*.cgf files are real
# building pieces, so the file name alone does not identify them.
_CLIPVOLUME_MATERIAL_MARKER = "intermediates/clipvolumes/clipvolumes"


def is_clip_volume_material(material_name: str | None) -> bool:
    if not material_name:
        return False
    return _CLIPVOLUME_MATERIAL_MARKER in material_name.lower()


def resolve_mtl_row(
    index: AssetIndex,
    row: AssetRow,
    conn=None,
    cgf_data: bytes | None = None,
) -> AssetRow | None:
    """Finds the most matching MTL material definition for a 3D asset."""
    stem = posixpath.splitext(row.filename)[0]

    if cgf_data is None and row.ext.lower() in ("cgf", "cgfm") and row.archive_path:
        try:
            with PakArchive(row.archive_path) as pak:
                cgf_data = pak.read(row.vpath)
        except Exception:
            pass

    if cgf_data:
        embedded_mtl = extract_cgf_material_name(cgf_data)
        if embedded_mtl:
            # 1a. Try exact virtual path + .mtl
            hits = index.find_by_vpath(embedded_mtl + ".mtl", conn=conn)
            if hits:
                return hits[0]

            # 1b. Try relative to CGF parent directory
            base_mtl = posixpath.basename(embedded_mtl)
            cand_vpath = posixpath.normpath(posixpath.join(posixpath.dirname(row.vpath), base_mtl + ".mtl"))
            hits = index.find_by_vpath(cand_vpath, conn=conn)
            if hits:
                return hits[0]

            # 1c. Try global search for basename
            matches, _ = index.search(base_mtl + ".mtl", type_group="Materials", conn=conn)
            for m in matches:
                if m.filename.lower() == (base_mtl + ".mtl").lower():
                    return m

    mtl_vpath = row.vpath.rsplit(".", 1)[0] + ".mtl"
    hits = index.find_by_vpath(mtl_vpath, conn=conn)
    if hits:
        return hits[0]

    clean_stem = re.sub(r"(_lod\d+|_dropmodel|_bundle)$", "", stem, flags=re.I)
    clean_vpath = posixpath.join(posixpath.dirname(row.vpath), clean_stem + ".mtl")
    hits = index.find_by_vpath(clean_vpath, conn=conn)
    if hits:
        return hits[0]

    parent_lower = posixpath.dirname(row.vpath).lower() + "/%.mtl"
    cur = conn.execute(
        "SELECT a.id FROM assets a WHERE a.vpath_lower LIKE ? AND a.ext = 'mtl'",
        (parent_lower,),
    )
    cand_ids = [r[0] for r in cur.fetchall()]
    if cand_ids:
        for cid in cand_ids:
            cand_row = index.get(cid, conn=conn)
            if cand_row and (clean_stem.lower() in cand_row.filename.lower() or stem.lower() in cand_row.filename.lower()):
                return cand_row

    global_matches, _ = index.search(f"{clean_stem}.mtl", type_group="Materials", conn=conn)
    for m in global_matches:
        if m.filename.lower() == f"{clean_stem}.mtl".lower():
            return m

    return None


def prepare_3d_preview(
    row: AssetRow,
    index: AssetIndex,
    settings: Settings,
    progress_cb: Callable[[str], None] | None = None,
    force_regenerate: bool = False,
    cancel_check: Callable[[], bool] | None = None,
) -> tuple[Path, MeshGeometry, PreviewMetadata]:
    """Prepares or retrieves a converted 3D GLB preview for an asset row with textures."""
    conv_exe = find_converter_exe(settings)
    if not conv_exe:
        raise PreviewGenerationError(converter_missing_message(settings))

    cache = PreviewCache(settings.workspace)
    hash_key = compute_asset_hash(row.vpath, row.archive_name, row.size)

    # If already cached and not forced, return cached directly
    if not force_regenerate and cache.has_preview(hash_key):
        glb_path = cache.get_glb_path(hash_key)
        meta = cache.get_metadata(hash_key)
        if glb_path and meta:
            if progress_cb:
                progress_cb("Loading cached preview...")
            try:
                geom = load_glb(glb_path, cached_materials=meta.materials, asset_vpath=row.vpath)
                return glb_path, geom, meta
            except Exception as e:
                log.warning("Cached GLB failed to load (%s), regenerating: %s", glb_path, e)

    # Cache miss or forced regeneration: stage and convert
    staging_dir = settings.workspace / "cache" / "staging" / hash_key
    staging_dir.mkdir(parents=True, exist_ok=True)

    try:
        if cancel_check and cancel_check():
            raise PreviewGenerationError(f"Preview for {row.filename} was cancelled.")

        if progress_cb:
            progress_cb(f"Extracting {row.filename}...")

        with PakArchive(row.archive_path) as pak:
            target_file = pak.extract(row.vpath, staging_dir)

        with index.connection(read_only=True) as conn:
            comps = index.companions(row, conn=conn)
            for comp in comps:
                if cancel_check and cancel_check():
                    raise PreviewGenerationError(f"Preview for {row.filename} was cancelled.")
                if comp.ext.lower() in ("cgfm", "skina"):
                    if progress_cb:
                        progress_cb(f"Resolving companion {comp.filename}...")
                    with PakArchive(comp.archive_path) as comp_pak:
                        comp_pak.extract(comp.vpath, staging_dir)

            cgf_bytes = target_file.read_bytes() if target_file.is_file() else None
            if cgf_bytes and row.ext.lower() in ("cgf", "cgfm"):
                embedded_name = extract_cgf_material_name(cgf_bytes)
                if is_clip_volume_material(embedded_name):
                    raise PreviewGenerationError(
                        f"{row.filename} is a CryEngine ClipVolume -- an invisible "
                        "indoor/outdoor culling boundary, not a renderable building "
                        "mesh. It has no real material by design, so there is nothing "
                        "to texture here. The actual visible structure is usually a "
                        "separate, differently-named asset in the same folder (often "
                        "without the 'cv_' prefix and trailing number)."
                    )
            mtl_row = resolve_mtl_row(index, row, conn=conn, cgf_data=cgf_bytes)
            mtl_file: Path | None = None
            mtl_def = None
            tex_total = 0
            tex_resolved = 0
            missing_textures: list[str] = []

            pak_cache: dict[str, PakArchive] = {}

            def get_pak(archive_path: str) -> PakArchive:
                if archive_path not in pak_cache:
                    pa = PakArchive(archive_path)
                    pa.open()
                    pak_cache[archive_path] = pa
                return pak_cache[archive_path]

            try:
                if mtl_row:
                    if progress_cb:
                        progress_cb(f"Resolving material {mtl_row.filename}...")
                    mtl_pak = get_pak(mtl_row.archive_path)
                    mtl_data = mtl_pak.read(mtl_row.vpath)
                    mtl_file = staging_dir / mtl_row.filename
                    with open(mtl_file, "wb") as f:
                        f.write(mtl_data)

                    try:
                        mtl_def = parse_mtl_xml(mtl_data, mtl_vpath=mtl_row.vpath)
                    except Exception as e:
                        log.warning("Failed to parse MTL definition %s: %s", mtl_row.filename, e)

                    # Parse MTL XML for texture dependencies
                    try:
                        root = ET.fromstring(mtl_data)
                        seen_vpaths: set[str] = set()

                        for tex in root.iter("Texture"):
                            f_attr = tex.attrib.get("File", "").strip()
                            map_type = tex.attrib.get("Map", "")
                            if not f_attr or f_attr.lower() == "nearest_cubemap" or f_attr.startswith("$"):
                                continue

                            tex_total += 1
                            clean = f_attr.replace("\\", "/").strip()
                            if clean.lower().endswith(".tif"):
                                clean_dds = clean[:-4] + ".dds"
                            elif clean.lower().endswith(".dds"):
                                clean_dds = clean
                            else:
                                clean_dds = clean + ".dds"

                            # Determine virtual path
                            if clean_dds.startswith("./") or "/" not in clean_dds:
                                dds_vpath = posixpath.normpath(
                                    posixpath.join(posixpath.dirname(mtl_row.vpath), clean_dds)
                                )
                            else:
                                dds_vpath = posixpath.normpath(clean_dds)

                            if dds_vpath in seen_vpaths:
                                continue
                            seen_vpaths.add(dds_vpath)

                            # The preview renderer ignores auxiliary maps.
                            clean_lower = clean.lower()
                            if any(x in clean_lower for x in ("_displ.", "_dt.", "_dtmask.", "_height.")) or map_type in ("Detail", "Displacement", "Heightmap"):
                                continue

                            # Bounds GLB baking time on large master materials.
                            if tex_resolved >= 32:
                                continue

                            dds_hits = index.find_by_vpath(dds_vpath, conn=conn)
                            if not dds_hits:
                                # Try case-insensitive basename search
                                base = posixpath.basename(dds_vpath)
                                matches, _ = index.search(base, type_group="Textures", conn=conn)
                                dds_hits = [m for m in matches if m.filename.lower() == base.lower()]

                            if dds_hits:
                                dds_row = dds_hits[0]
                                # Extract base .dds using cached archive
                                base_pak = get_pak(dds_row.archive_path)
                                base_data = base_pak.read(dds_row.vpath)

                                # Extract all split mip parts (.dds.1, .dds.2, etc.)
                                parts = index.texture_parts(dds_row.vpath, conn=conn)
                                parts_data = []
                                for p in parts:
                                    ext = p.filename.split(".")[-1]
                                    if ext.isdigit():
                                        part_pak = get_pak(p.archive_path)
                                        parts_data.append((int(ext), part_pak.read(p.vpath)))

                                combined_dds = combine_cryengine_dds(base_data, parts_data)
                                with open(staging_dir / dds_row.filename, "wb") as f:
                                    f.write(combined_dds)

                                tex_resolved += 1
                            else:
                                missing_textures.append(clean_dds)
                                log.info("Texture not resolved: %s (vpath: %s)", clean_dds, dds_vpath)

                    except Exception as e:
                        log.warning("Failed to parse MTL XML %s: %s", mtl_row.filename, e)
            finally:
                for pa in pak_cache.values():
                    try:
                        pa.close()
                    except Exception:
                        pass

            if cancel_check and cancel_check():
                raise PreviewGenerationError(f"Preview for {row.filename} was cancelled.")

            if progress_cb:
                progress_cb("Converting geometry and baking textures to GLB...")

            cmd = [str(conv_exe), str(target_file), "-glb"]
            if mtl_file and mtl_file.is_file():
                cmd.extend([
                    "-material", str(mtl_file),
                    "-objectdir", str(staging_dir),
                    "-embedtextures",
                ])

            proc = subprocess.run(
                cmd,
                capture_output=True,
                text=False,
                cwd=str(staging_dir),
                timeout=120,
            )
            stdout_str = proc.stdout.decode("utf-8", errors="replace") if proc.stdout else ""
            stderr_str = proc.stderr.decode("utf-8", errors="replace") if proc.stderr else ""

            if proc.returncode != 0:
                log.warning("KCD2-Convertor failed. Output:\n%s\nStderr:\n%s", stdout_str, stderr_str)
                raise PreviewGenerationError(
                    f"KCD2-Convertor failed with code {proc.returncode}:\n{stderr_str or stdout_str}"
                )

            # Find generated .glb file (supports nested output paths)
            expected_glb = target_file.with_suffix(".glb")
            if not expected_glb.is_file():
                glbs = list(staging_dir.rglob("*.glb"))
                if glbs:
                    expected_glb = glbs[0]
                else:
                    raise PreviewGenerationError(
                        f"Conversion completed, but no .glb output was generated in:\n{staging_dir}\n"
                        f"Converter output:\n{stdout_str}"
                    )

            if progress_cb:
                progress_cb("Parsing 3D mesh geometry and textures...")

            geom = load_glb(expected_glb, mtl_def=mtl_def, asset_vpath=row.vpath)

            # Discover related LODs from database using read-only thread connection
            lod_family = find_lod_family(index, row, conn=conn)
            lods_summary = []
            for it in lod_family.lods:
                lods_summary.append({
                    "lod": it.level,
                    "label": it.label,
                    "filename": it.row.filename,
                    "vpath": it.row.vpath,
                    "archive_name": it.row.archive_name,
                    "size": it.row.size,
                })

        materials_summary = [
            {
                "name": m.name,
                "kcd2_submaterial_id": m.kcd2_submaterial_id,
                "shader_type": m.shader_type,
                "surface_type": m.surface_type,
                "material_family": m.material_family,
                "roughness": m.roughness,
                "metallic": m.metallic,
                "specular_f0": list(m.specular_f0),
                "ior": m.ior,
                "alpha_mode": m.alpha_mode,
                "alpha_cutoff": m.alpha_cutoff,
                "double_sided": m.double_sided,
                "is_hidden": m.is_hidden,
                "is_proxy": m.is_proxy,
                "normal_semantic": m.normal_semantic,
                "diagnostic_report": m.diagnostic_report,
                "fallback_reason": m.fallback_reason,
            }
            for m in geom.materials
        ]

        final_glb = cache.store_glb(hash_key, expected_glb)
        metadata = PreviewMetadata(
            vpath=row.vpath,
            filename=row.filename,
            archive_name=row.archive_name,
            file_size=row.size,
            triangles=geom.triangles,
            vertices=geom.vertices,
            dim_x=float(geom.dim[0]),
            dim_y=float(geom.dim[1]),
            dim_z=float(geom.dim[2]),
            bounds_min=[float(x) for x in geom.bounds_min],
            bounds_max=[float(x) for x in geom.bounds_max],
            lods=lods_summary,
            created_at=time.time(),
            textures_resolved=tex_resolved,
            textures_total=tex_total,
            missing_textures=missing_textures,
            materials=materials_summary,
        )
        cache.save_metadata(hash_key, metadata)

        return final_glb, geom, metadata

    finally:
        # Clean up staging directory
        shutil.rmtree(staging_dir, ignore_errors=True)
