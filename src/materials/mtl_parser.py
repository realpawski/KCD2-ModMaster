"""KCD2 .mtl material definition parser and texture dependency resolver."""
from __future__ import annotations

import logging
import os
import posixpath
import re
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from archives.pak import PakArchive
from materials.dds_combiner import combine_cryengine_dds

log = logging.getLogger(__name__)


@dataclass
class SubMaterialInfo:
    id: int  # 0-based index in MTL
    name: str
    shader: str = "Illum"
    surface_type: str = ""
    diffuse_color: tuple[float, float, float] = (1.0, 1.0, 1.0)
    specular_color: tuple[float, float, float] = (0.04, 0.04, 0.04)
    shininess: float = 255.0
    opacity: float = 1.0
    alpha_test: float = 0.0
    source_attributes: dict[str, str] = field(default_factory=dict)
    is_proxy: bool = False
    textures: dict[str, str] = field(default_factory=dict)  # Map (e.g. "Diffuse") -> virtual or relative file
    resolved_textures: dict[str, str] = field(default_factory=dict)  # Map -> local filename on disk
    public_params: dict[str, str] = field(default_factory=dict)


@dataclass
class MTLDefinition:
    mtl_vpath: str
    submaterials: list[SubMaterialInfo] = field(default_factory=list)
    flags: str = ""
    vert_modif_type: str = "0"


def parse_mtl_xml(xml_content: str | bytes, mtl_vpath: str = "") -> MTLDefinition:
    """Parses CryEngine / KCD2 XML material definitions with full hierarchy."""
    if isinstance(xml_content, bytes):
        xml_content = xml_content.decode("utf-8", errors="replace")

    root = ET.fromstring(xml_content)
    flags = root.attrib.get("MtlFlags", "")
    vert_modif = root.attrib.get("vertModifType", "0")

    submats: list[SubMaterialInfo] = []

    # Check for <SubMaterials> child or root <Material> entries
    sub_container = root.find("SubMaterials")
    mat_nodes = []
    if sub_container is not None:
        mat_nodes = [c for c in sub_container if c.tag in ("Material", "SubMaterial")]
    if not mat_nodes and root.tag in ("Material", "SubMaterial"):
        mat_nodes = [root]

    for idx, elem in enumerate(mat_nodes):
        name = elem.attrib.get("Name", f"SubMtl_{idx}")
        shader = elem.attrib.get("Shader", "Illum")
        surface = elem.attrib.get("SurfaceType", "")

        def parse_vec3(val: str, default: tuple[float, float, float]) -> tuple[float, float, float]:
            try:
                parts = [float(x.strip()) for x in val.split(",")]
                if len(parts) >= 3:
                    return (parts[0], parts[1], parts[2])
            except Exception:
                pass
            return default

        diffuse = parse_vec3(elem.attrib.get("Diffuse", "1,1,1"), (1.0, 1.0, 1.0))
        specular = parse_vec3(elem.attrib.get("Specular", "0.04,0.04,0.04"), (0.04, 0.04, 0.04))

        try:
            shininess = float(elem.attrib.get("Shininess", "255"))
        except ValueError:
            shininess = 255.0

        try:
            opacity = float(elem.attrib.get("Opacity", "1"))
        except ValueError:
            opacity = 1.0

        is_proxy = (
            "proxy" in name.lower()
            or "shadowproxy" in name.lower()
            or shader.lower() == "nodraw"
            or (diffuse[0] < 0.1 and diffuse[1] > 0.8 and diffuse[2] < 0.1)
        )

        textures: dict[str, str] = {}
        for t in elem.iter("Texture"):
            m_type = t.attrib.get("Map", "Diffuse")
            f_path = t.attrib.get("File", "").strip()
            if f_path and f_path.lower() != "nearest_cubemap" and not f_path.startswith("$"):
                textures[m_type] = f_path

        pub_params: dict[str, str] = {}
        params_elem = elem.find("PublicParams")
        if params_elem is not None:
            pub_params = dict(params_elem.attrib)

        submats.append(SubMaterialInfo(
            id=idx,
            name=name,
            shader=shader,
            surface_type=surface,
            diffuse_color=diffuse,
            specular_color=specular,
            shininess=shininess,
            opacity=opacity,
            alpha_test=float(elem.attrib.get("AlphaTest", "0")),
            source_attributes=dict(elem.attrib),
            is_proxy=is_proxy,
            textures=textures,
            public_params=pub_params,
        ))

    return MTLDefinition(
        mtl_vpath=mtl_vpath,
        submaterials=submats,
        flags=flags,
        vert_modif_type=vert_modif,
    )


def resolve_and_stage_textures(
    mtl_def: MTLDefinition,
    index: Any,
    dest_dir: Path,
    conn=None,
) -> tuple[int, int, list[str]]:
    """Resolves and extracts combined DDS textures for an MTL into dest_dir.

    Returns: (total_textures_referenced, resolved_count, missing_list)
    """
    dest_dir.mkdir(parents=True, exist_ok=True)
    total_refs = 0
    resolved_count = 0
    missing: list[str] = []

    for submat in mtl_def.submaterials:
        submat.resolved_textures.clear()
        for slot, f_path in submat.textures.items():
            total_refs += 1
            clean = f_path.replace("\\", "/").strip()
            if clean.lower().endswith(".tif"):
                clean_dds = clean[:-4] + ".dds"
            elif clean.lower().endswith(".dds"):
                clean_dds = clean
            else:
                clean_dds = clean + ".dds"

            # Determine virtual path candidate
            if clean_dds.startswith("./") or "/" not in clean_dds:
                dds_vpath = posixpath.normpath(
                    posixpath.join(posixpath.dirname(mtl_def.mtl_vpath), clean_dds)
                )
            else:
                dds_vpath = posixpath.normpath(clean_dds)

            dds_hits = index.find_by_vpath(dds_vpath, conn=conn)
            if not dds_hits:
                # Fallback to case-insensitive basename search
                base = posixpath.basename(dds_vpath)
                matches, _ = index.search(base, type_group="Textures", conn=conn)
                dds_hits = [m for m in matches if m.filename.lower() == base.lower()]

            if dds_hits:
                dds_row = dds_hits[0]
                target_file = dest_dir / dds_row.filename
                if not target_file.is_file():
                    with PakArchive(dds_row.archive_path) as dpak:
                        base_data = dpak.read(dds_row.vpath)
                    parts = index.texture_parts(dds_row.vpath, conn=conn)
                    parts_data = []
                    for p in parts:
                        ext = p.filename.split(".")[-1]
                        if ext.isdigit():
                            with PakArchive(p.archive_path) as ppak:
                                parts_data.append((int(ext), ppak.read(p.vpath)))

                    combined = combine_cryengine_dds(base_data, parts_data)
                    with open(target_file, "wb") as f:
                        f.write(combined)

                # DDNA gloss is a separate BC4 stream: .dds.a plus .dds.Na.
                # Reuse the dependency index and existing mip combiner, including
                # for cached RGB textures created by older bridge versions.
                if slot in ("Bumpmap", "Normal"):
                    all_parts = index.texture_parts(dds_row.vpath, conn=conn)
                    alpha = next((p for p in all_parts if p.filename.lower().endswith(".dds.a")), None)
                    if alpha:
                        gloss_name = dds_row.filename + ".gloss.dds"
                        gloss_file = dest_dir / gloss_name
                        if not gloss_file.is_file():
                            with PakArchive(alpha.archive_path) as apak:
                                alpha_data = apak.read(alpha.vpath)
                            # CryEngine's attached alpha header omits DDS magic.
                            if alpha_data[:4] != b"DDS ":
                                alpha_data = b"DDS " + alpha_data
                            alpha_parts = []
                            for part in all_parts:
                                match = re.search(r"\.dds\.(\d+)a$", part.filename, re.I)
                                if match:
                                    with PakArchive(part.archive_path) as apak:
                                        alpha_parts.append((int(match.group(1)), apak.read(part.vpath)))
                            gloss_file.write_bytes(combine_cryengine_dds(alpha_data, alpha_parts))
                        submat.resolved_textures["Gloss"] = gloss_name
                submat.resolved_textures[slot] = dds_row.filename
                resolved_count += 1
            else:
                missing.append(clean_dds)
                log.info("Texture unresolvable: %s (vpath: %s)", clean_dds, dds_vpath)

    return total_refs, resolved_count, missing
