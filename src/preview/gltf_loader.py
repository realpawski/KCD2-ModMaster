"""GLB (glTF 2.0 binary) parser and vertex buffer extractor."""
from __future__ import annotations

import json
import logging
import struct
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import numpy as np

log = logging.getLogger(__name__)


@dataclass
class MaterialInfo:
    name: str = "default"
    kcd2_submaterial_id: int = 0
    shader_type: str = "Illum"
    surface_type: str = ""
    material_family: str = "STANDARD_PBR"
    base_color: tuple[float, float, float, float] = (0.8, 0.8, 0.8, 1.0)
    diffuse_texture_bytes: bytes | None = None
    diffuse_texture_mime: str = "image/png"
    normal_texture_bytes: bytes | None = None
    normal_texture_mime: str = "image/png"
    specular_factor: tuple[float, float, float] = (0.04, 0.04, 0.04)
    glossiness_factor: float = 0.5
    roughness: float = 0.65
    metallic: float = 0.0
    specular_f0: tuple[float, float, float] = (0.04, 0.04, 0.04)
    ior: float = 1.5
    alpha_mode: str = "OPAQUE"  # "OPAQUE", "MASK", "BLEND"
    alpha_cutoff: float = 0.5
    double_sided: bool = False
    is_hidden: bool = False
    is_proxy: bool = False
    normal_semantic: str = "KCD2_DDNA"
    diagnostic_report: str = ""
    fallback_reason: str = ""


@dataclass
class PrimitivePart:
    index_start: int
    index_count: int
    material_idx: int = 0
    material_name: str = ""
    triangle_count: int = 0
    vertex_count: int = 0


@dataclass
class MeshGeometry:
    positions: np.ndarray  # (N, 3) float32
    normals: np.ndarray    # (N, 3) float32
    uvs: np.ndarray | None # (N, 2) float32 or None
    indices: np.ndarray    # (M,) uint32
    triangles: int
    vertices: int
    bounds_min: np.ndarray # (3,) float32
    bounds_max: np.ndarray # (3,) float32
    center: np.ndarray     # (3,) float32
    dim: np.ndarray        # (3,) float32 (dx, dy, dz)
    tangents: np.ndarray | None = None # (N, 4) float32 or None
    parts: list[PrimitivePart] = field(default_factory=list)
    materials: list[MaterialInfo] = field(default_factory=list)
    asset_vpath: str = ""


class GLTFLoaderError(Exception):
    pass


def load_glb(
    glb_path: str | Path,
    exclude_proxies: bool = True,
    mtl_def: Any = None,
    cached_materials: list[dict] | None = None,
    asset_vpath: str = "",
) -> MeshGeometry:
    """Parses a GLB file, extracting visual primitives, materials, and embedded textures."""
    path = Path(glb_path)
    if not path.is_file():
        raise GLTFLoaderError(f"GLB file not found: {path}")

    with open(path, "rb") as f:
        magic, version, total_len = struct.unpack("<4sII", f.read(12))
        if magic != b"glTF":
            raise GLTFLoaderError(f"Invalid GLB magic: {magic!r}")

        # Chunk 0: JSON
        c0_len, c0_type = struct.unpack("<I4s", f.read(8))
        if c0_type != b"JSON":
            raise GLTFLoaderError(f"Expected JSON chunk, got: {c0_type!r}")
        json_bytes = f.read(c0_len)
        gltf: dict[str, Any] = json.loads(json_bytes.decode("utf-8"))

        # Chunk 1: BIN
        c1_len, c1_type = struct.unpack("<I4s", f.read(8))
        if c1_type != b"BIN\x00":
            raise GLTFLoaderError(f"Expected BIN chunk, got: {c1_type!r}")
        bin_data = f.read(c1_len)

    accessors = gltf.get("accessors", [])
    buffer_views = gltf.get("bufferViews", [])
    meshes = gltf.get("meshes", [])
    nodes = gltf.get("nodes", [])

    # Extract embedded images from bufferViews
    images_raw = gltf.get("images", [])
    decoded_images: list[tuple[bytes, str]] = []
    for img in images_raw:
        bv_idx = img.get("bufferView")
        if bv_idx is not None and bv_idx < len(buffer_views):
            bv = buffer_views[bv_idx]
            offset = bv.get("byteOffset", 0)
            length = bv["byteLength"]
            mime = img.get("mimeType", "image/png")
            decoded_images.append((bin_data[offset : offset + length], mime))
        else:
            decoded_images.append((b"", ""))

    # Extract textures
    textures_raw = gltf.get("textures", [])

    # Extract materials
    materials_raw = gltf.get("materials", [])
    parsed_materials: list[MaterialInfo] = []

    from materials.semantics import (
        classify_kcd2_material,
        format_diagnostic_report,
    )

    for m_idx, mat in enumerate(materials_raw):
        m_name = mat.get("name", "material")
        pbr = mat.get("pbrMetallicRoughness", {})
        ext_spec = mat.get("extensions", {}).get("KHR_materials_pbrSpecularGlossiness", {})

        # Base color
        bc = pbr.get("baseColorFactor")
        if bc is None and "diffuseFactor" in ext_spec:
            bc = ext_spec.get("diffuseFactor")
        if bc is None:
            bc = [0.8, 0.8, 0.8, 1.0]
        if len(bc) == 3:
            bc = [*bc, 1.0]
        base_color = (float(bc[0]), float(bc[1]), float(bc[2]), float(bc[3]))

        # Diffuse texture
        diff_bytes: bytes | None = None
        diff_mime = "image/png"
        diff_tex_info = pbr.get("baseColorTexture")
        if diff_tex_info is None and "diffuseTexture" in ext_spec:
            diff_tex_info = ext_spec.get("diffuseTexture")

        if diff_tex_info is not None:
            t_idx = diff_tex_info.get("index")
            if t_idx is not None and t_idx < len(textures_raw):
                s_idx = textures_raw[t_idx].get("source")
                if s_idx is not None and s_idx < len(decoded_images):
                    diff_bytes, diff_mime = decoded_images[s_idx]

        # Normal texture
        norm_bytes: bytes | None = None
        norm_mime = "image/png"
        norm_tex_info = mat.get("normalTexture")
        if norm_tex_info is not None:
            t_idx = norm_tex_info.get("index")
            if t_idx is not None and t_idx < len(textures_raw):
                s_idx = textures_raw[t_idx].get("source")
                if s_idx is not None and s_idx < len(decoded_images):
                    norm_bytes, norm_mime = decoded_images[s_idx]

        spec_factor = tuple(float(x) for x in ext_spec.get("specularFactor", [0.04, 0.04, 0.04]))
        if len(spec_factor) == 3:
            spec_factor = (spec_factor[0], spec_factor[1], spec_factor[2])
        else:
            spec_factor = (0.04, 0.04, 0.04)

        gloss_factor = float(ext_spec.get("glossinessFactor", 0.5))
        alpha_mode = str(mat.get("alphaMode", "OPAQUE")).upper()
        alpha_cutoff = float(mat.get("alphaCutoff", 0.5))
        double_sided = bool(mat.get("doubleSided", False))

        # Check if source MTL submaterial info is available
        source_sub = None
        if mtl_def and hasattr(mtl_def, "submaterials") and mtl_def.submaterials:
            for s in mtl_def.submaterials:
                if s.name.lower() == m_name.lower():
                    source_sub = s
                    break
            if not source_sub and m_idx < len(mtl_def.submaterials):
                source_sub = mtl_def.submaterials[m_idx]

        # Check if cached material description dict is available
        cached_desc = None
        if cached_materials and m_idx < len(cached_materials):
            cached_desc = cached_materials[m_idx]

        if source_sub is not None:
            desc = classify_kcd2_material(
                name=source_sub.name,
                shader=source_sub.shader,
                surface_type=source_sub.surface_type,
                shininess=source_sub.shininess,
                specular_color=source_sub.specular_color,
                diffuse_color=source_sub.diffuse_color,
                opacity=source_sub.opacity,
                alpha_test=source_sub.alpha_test,
                textures=source_sub.textures,
                public_params=source_sub.public_params,
                source_attributes=source_sub.source_attributes,
                has_tangents=True,
                has_uvs=True,
                submaterial_id=m_idx,
                asset_name=asset_vpath,
            )
        elif cached_desc is not None:
            desc = classify_kcd2_material(
                name=cached_desc.get("name", m_name),
                shader=cached_desc.get("shader_type", "Illum"),
                surface_type=cached_desc.get("surface_type", ""),
                specular_color=cached_desc.get("specular_f0", spec_factor),
                diffuse_color=(base_color[0], base_color[1], base_color[2]),
                opacity=base_color[3],
                alpha_test=cached_desc.get("alpha_cutoff", alpha_cutoff),
                submaterial_id=m_idx,
                asset_name=asset_vpath,
            )
        else:
            desc = classify_kcd2_material(
                name=m_name,
                shader="Illum",
                specular_color=spec_factor,
                diffuse_color=(base_color[0], base_color[1], base_color[2]),
                opacity=base_color[3],
                alpha_test=alpha_cutoff if alpha_mode == "MASK" else 0.0,
                submaterial_id=m_idx,
                asset_name=asset_vpath,
            )

        final_alpha_mode = desc.alpha_mode if alpha_mode == "OPAQUE" and desc.alpha_mode == "MASK" else (desc.alpha_mode or alpha_mode)
        final_alpha_cutoff = desc.alpha_cutoff if alpha_mode == "OPAQUE" and desc.alpha_mode == "MASK" else alpha_cutoff
        final_double_sided = desc.double_sided or double_sided

        diag_report = format_diagnostic_report(
            desc=desc,
            source_mtl=mtl_def.mtl_vpath if mtl_def and hasattr(mtl_def, "mtl_vpath") else "embedded",
            diffuse_tex=f"embedded ({len(diff_bytes):,} B)" if diff_bytes else "none",
            normal_tex=f"embedded ({len(norm_bytes):,} B)" if norm_bytes else "none",
            tangent_status="valid (VEC4 from GLB)",
            uv_status="valid (TEXCOORD_0)",
        )

        final_roughness = cached_desc.get("roughness", desc.roughness) if cached_desc else desc.roughness
        final_metallic = cached_desc.get("metallic", desc.metallic) if cached_desc else desc.metallic
        final_specular_f0 = tuple(cached_desc.get("specular_f0", desc.specular_f0)) if cached_desc and "specular_f0" in cached_desc else desc.specular_f0
        final_is_hidden = cached_desc.get("is_hidden", desc.is_hidden) if cached_desc else desc.is_hidden
        final_is_proxy = cached_desc.get("is_proxy", desc.is_proxy) if cached_desc else desc.is_proxy

        parsed_materials.append(MaterialInfo(
            name=m_name,
            kcd2_submaterial_id=m_idx,
            shader_type=desc.shader_type,
            surface_type=desc.surface_type,
            material_family=desc.material_family,
            base_color=desc.base_color if final_is_hidden else base_color,
            diffuse_texture_bytes=diff_bytes,
            diffuse_texture_mime=diff_mime,
            normal_texture_bytes=norm_bytes,
            normal_texture_mime=norm_mime,
            specular_factor=spec_factor,
            glossiness_factor=gloss_factor,
            roughness=final_roughness,
            metallic=final_metallic,
            specular_f0=final_specular_f0,
            ior=desc.ior,
            alpha_mode=final_alpha_mode,
            alpha_cutoff=final_alpha_cutoff,
            double_sided=final_double_sided,
            is_hidden=final_is_hidden,
            is_proxy=final_is_proxy,
            normal_semantic=desc.normal_encoding,
            diagnostic_report=diag_report,
            fallback_reason=desc.fallback_reason,
        ))

    if not parsed_materials:
        parsed_materials.append(MaterialInfo(name="default"))

    # Identify node filters (e.g. shadow proxies or physics proxies)
    filtered_mesh_indices = set()
    if exclude_proxies and nodes:
        for node in nodes:
            name = node.get("name", "").lower()
            mesh_idx = node.get("mesh")
            if mesh_idx is not None and ("$physics" in name or "shadowproxy" in name or "proxy_" in name):
                filtered_mesh_indices.add(mesh_idx)

    # If all meshes were filtered out, don't filter
    if len(filtered_mesh_indices) >= len(meshes):
        filtered_mesh_indices.clear()

    def read_accessor(acc_idx: int) -> np.ndarray:
        acc = accessors[acc_idx]
        bv = buffer_views[acc["bufferView"]]
        offset = bv.get("byteOffset", 0) + acc.get("byteOffset", 0)
        count = acc["count"]
        comp_type = acc["componentType"]
        type_str = acc["type"]

        # Component types: 5120: BYTE, 5121: UBYTE, 5122: SHORT, 5123: USHORT, 5125: UINT, 5126: FLOAT
        dtype_map = {
            5120: np.int8,
            5121: np.uint8,
            5122: np.int16,
            5123: np.uint16,
            5125: np.uint32,
            5126: np.float32,
        }
        dtype = dtype_map.get(comp_type, np.float32)

        elem_count_map = {"SCALAR": 1, "VEC2": 2, "VEC3": 3, "VEC4": 4, "MAT4": 16}
        elems = elem_count_map.get(type_str, 1)

        total_elems = count * elems
        byte_len = total_elems * dtype().itemsize
        raw = bin_data[offset : offset + byte_len]
        arr = np.frombuffer(raw, dtype=dtype)
        if elems > 1:
            arr = arr.reshape((count, elems))
        return arr

    all_positions = []
    all_normals = []
    all_uvs = []
    all_tangents = []
    all_indices = []
    parts: list[PrimitivePart] = []
    accessor_vertex_offsets: dict[int, int] = {}
    current_total_vertices = 0
    total_indices_so_far = 0

    for m_idx, mesh in enumerate(meshes):
        if m_idx in filtered_mesh_indices:
            continue

        for prim in mesh.get("primitives", []):
            attrs = prim.get("attributes", {})
            pos_idx = attrs.get("POSITION")
            if pos_idx is None:
                continue

            # If this position accessor has already been added, reuse its base vertex offset
            if pos_idx in accessor_vertex_offsets:
                prim_vertex_offset = accessor_vertex_offsets[pos_idx]
                pos_count = accessors[pos_idx]["count"]
            else:
                prim_vertex_offset = current_total_vertices
                accessor_vertex_offsets[pos_idx] = prim_vertex_offset

                pos = read_accessor(pos_idx).astype(np.float32)
                pos_count = len(pos)
                norm_idx = attrs.get("NORMAL")
                if norm_idx is not None:
                    norm = read_accessor(norm_idx).astype(np.float32)
                else:
                    norm = np.zeros_like(pos)

                uv_idx = attrs.get("TEXCOORD_0")
                if uv_idx is not None:
                    uv = read_accessor(uv_idx).astype(np.float32)
                else:
                    uv = np.zeros((pos_count, 2), dtype=np.float32)

                tan_idx = attrs.get("TANGENT")
                if tan_idx is not None:
                    tang = read_accessor(tan_idx).astype(np.float32)
                else:
                    tang = None

                all_positions.append(pos)
                all_normals.append(norm)
                all_uvs.append(uv)
                all_tangents.append(tang)
                current_total_vertices += pos_count

            ind_idx = prim.get("indices")
            if ind_idx is not None:
                ind = read_accessor(ind_idx).astype(np.uint32)
            else:
                ind = np.arange(pos_count, dtype=np.uint32)

            mat_idx = prim.get("material", 0)
            if mat_idx is None or mat_idx >= len(parsed_materials):
                mat_idx = 0

            mat = parsed_materials[mat_idx]
            if exclude_proxies and (mat.is_proxy or mat.is_hidden):
                # Completely skip proxy or suppressed overlay geometry
                continue

            mat_name = mat.name

            parts.append(PrimitivePart(
                index_start=total_indices_so_far,
                index_count=len(ind),
                material_idx=mat_idx,
                material_name=mat_name,
                triangle_count=len(ind) // 3,
                vertex_count=pos_count,
            ))

            shifted_ind = ind + prim_vertex_offset
            all_indices.append(shifted_ind)
            total_indices_so_far += len(ind)

    if not all_positions or not all_indices:
        if exclude_proxies:
            # Everything was proxy or collision geometry: retry with proxies.
            return load_glb(
                glb_path,
                exclude_proxies=False,
                mtl_def=mtl_def,
                cached_materials=cached_materials,
                asset_vpath=asset_vpath,
            )
        raise GLTFLoaderError("No mesh geometry found in GLB.")

    final_pos = np.vstack(all_positions)
    final_norm = np.vstack(all_normals)
    final_uv = np.vstack(all_uvs) if all_uvs else None
    final_ind = np.concatenate(all_indices)

    # Compute bounding box
    bounds_min = np.min(final_pos, axis=0)
    bounds_max = np.max(final_pos, axis=0)
    center = (bounds_min + bounds_max) * 0.5
    dim = bounds_max - bounds_min

    # If normals are zero, calculate flat/smooth normals
    if np.all(final_norm == 0):
        final_norm = calculate_smooth_normals(final_pos, final_ind)

    # Resolve tangents: use embedded ones if available for all primitives, otherwise calculate
    if all_tangents and all(t is not None for t in all_tangents):
        final_tang = np.vstack(all_tangents)
    else:
        final_tang = calculate_tangents(final_pos, final_norm, final_uv, final_ind)

    return MeshGeometry(
        positions=final_pos,
        normals=final_norm,
        uvs=final_uv,
        tangents=final_tang,
        indices=final_ind,
        triangles=len(final_ind) // 3,
        vertices=len(final_pos),
        bounds_min=bounds_min,
        bounds_max=bounds_max,
        center=center,
        dim=dim,
        parts=parts,
        materials=parsed_materials,
        asset_vpath=asset_vpath,
    )


def calculate_smooth_normals(positions: np.ndarray, indices: np.ndarray) -> np.ndarray:
    """Computes vertex normals from triangles."""
    normals = np.zeros_like(positions)
    tris = indices.reshape(-1, 3)
    p0 = positions[tris[:, 0]]
    p1 = positions[tris[:, 1]]
    p2 = positions[tris[:, 2]]
    fnorm = np.cross(p1 - p0, p2 - p0)

    # Accumulate into vertex normals
    np.add.at(normals, tris[:, 0], fnorm)
    np.add.at(normals, tris[:, 1], fnorm)
    np.add.at(normals, tris[:, 2], fnorm)

    # Normalize
    lens = np.linalg.norm(normals, axis=1, keepdims=True)
    lens[lens == 0] = 1.0
    return (normals / lens).astype(np.float32)


def calculate_tangents(
    positions: np.ndarray,
    normals: np.ndarray,
    uvs: np.ndarray | None,
    indices: np.ndarray,
) -> np.ndarray:
    """Calculates smoothed per-vertex 4D tangents (T.xyz, handedness w)."""
    n_verts = len(positions)
    if uvs is None or len(uvs) != n_verts:
        # Fallback default unit tangent
        res = np.zeros((n_verts, 4), dtype=np.float32)
        res[:, 0] = 1.0
        res[:, 3] = 1.0
        return res

    tan1 = np.zeros((n_verts, 3), dtype=np.float32)
    tan2 = np.zeros((n_verts, 3), dtype=np.float32)
    tris = indices.reshape(-1, 3)

    v1 = positions[tris[:, 0]]
    v2 = positions[tris[:, 1]]
    v3 = positions[tris[:, 2]]

    w1 = uvs[tris[:, 0]]
    w2 = uvs[tris[:, 1]]
    w3 = uvs[tris[:, 2]]

    x1 = v2[:, 0] - v1[:, 0]
    x2 = v3[:, 0] - v1[:, 0]
    y1 = v2[:, 1] - v1[:, 1]
    y2 = v3[:, 1] - v1[:, 1]
    z1 = v2[:, 2] - v1[:, 2]
    z2 = v3[:, 2] - v1[:, 2]

    s1 = w2[:, 0] - w1[:, 0]
    s2 = w3[:, 0] - w1[:, 0]
    t1 = w2[:, 1] - w1[:, 1]
    t2 = w3[:, 1] - w1[:, 1]

    denom = s1 * t2 - s2 * t1
    denom = np.where(np.abs(denom) < 1e-8, 1e-8, denom)
    r = 1.0 / denom

    sdir = np.stack([
        (t2 * x1 - t1 * x2) * r,
        (t2 * y1 - t1 * y2) * r,
        (t2 * z1 - t1 * z2) * r,
    ], axis=-1)

    tdir = np.stack([
        (s1 * x2 - s2 * x1) * r,
        (s1 * y2 - s2 * y1) * r,
        (s1 * z2 - s2 * z1) * r,
    ], axis=-1)

    for i in range(3):
        np.add.at(tan1, tris[:, i], sdir)
        np.add.at(tan2, tris[:, i], tdir)

    # Gram-Schmidt orthogonalize
    n = normals
    t = tan1
    dot_nt = np.sum(n * t, axis=1, keepdims=True)
    t_ortho = t - n * dot_nt
    lens = np.linalg.norm(t_ortho, axis=1, keepdims=True)
    lens = np.where(lens < 1e-6, 1.0, lens)
    t_norm = t_ortho / lens

    cross_nt = np.cross(n, t)
    dot_cross = np.sum(cross_nt * tan2, axis=1)
    w = np.where(dot_cross < 0.0, -1.0, 1.0).astype(np.float32)

    return np.hstack([t_norm, w[:, None]]).astype(np.float32)
