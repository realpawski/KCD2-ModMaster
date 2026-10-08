"""Shared KCD2 Material & Texture Semantic Classification Layer.

Centralizes KCD2 / CryEngine material interpretations (MTL, shaders, surface types)
into renderer-agnostic PBR parameters (Roughness, Metallic, Specular F0, Alpha Mode, Tangents).
Shared by both the ModMaster internal 3D viewport preview and the Blender Bridge.
"""
from __future__ import annotations

import logging
import math
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

log = logging.getLogger(__name__)


class MaterialFamily:
    STANDARD_PBR = "STANDARD_PBR"
    ORGANIC_DIELECTRIC = "ORGANIC_DIELECTRIC"
    HAIR_FUR = "HAIR_FUR"
    EYE = "EYE"
    VEGETATION = "VEGETATION"
    HUMAN_SKIN = "HUMAN_SKIN"
    DECAL_OVERLAY = "DECAL_OVERLAY"
    PROXY = "PROXY"
    UNSUPPORTED = "UNSUPPORTED"


class NormalSemantic:
    KCD2_DDNA = "KCD2_DDNA"
    KCD2_DDN = "KCD2_DDN"
    STANDARD_NORMAL = "STANDARD_NORMAL"
    NO_NORMAL = "NO_NORMAL"


@dataclass
class KCD2MaterialDescription:
    """Renderer-agnostic KCD2 material description classified from MTL & textures."""
    name: str = "default"
    kcd2_submaterial_id: int = 0
    shader_type: str = "Illum"
    surface_type: str = ""
    material_family: str = "STANDARD_PBR"  # "STANDARD_PBR", "HAIR_FUR", "EYE", "VEGETATION", "HUMAN_SKIN", "PROXY", "UNSUPPORTED"

    # Texture semantics
    diffuse_texture: str = ""
    normal_texture: str = ""
    specular_texture: str = ""
    gloss_texture: str = ""
    opacity_texture: str = ""
    normal_encoding: str = "KCD2_DDNA"  # "KCD2_DDNA", "KCD2_DDN", "STANDARD_NORMAL", "NO_NORMAL"

    # Evaluated PBR parameters
    base_color: tuple[float, float, float, float] = (1.0, 1.0, 1.0, 1.0)
    roughness: float = 0.65
    metallic: float = 0.0
    specular_f0: tuple[float, float, float] = (0.04, 0.04, 0.04)
    ior: float = 1.5
    emissive: tuple[float, float, float] = (0.0, 0.0, 0.0)

    # Transparency & Geometry flags
    alpha_mode: str = "OPAQUE"  # "OPAQUE", "MASK", "BLEND"
    alpha_cutoff: float = 0.5
    double_sided: bool = False
    is_hidden: bool = False  # e.g. proxies or HideMask="0"
    is_proxy: bool = False

    material_flags: str = ""
    diagnostic_report: str = ""
    fallback_reason: str = ""

    @property
    def normal_semantic(self) -> str:
        return self.normal_encoding


# Alias for backward compatibility
KCD2MaterialPBR = KCD2MaterialDescription


def linearize_srgb(val: float) -> float:
    """Linearizes sRGB [0..1] value to linear space (gamma 2.2 approximation)."""
    return max(0.0, min(1.0, float(val))) ** 2.2


def detect_normal_semantic(
    texture_filename: str = "",
    slot_name: str = "",
    has_tangents: bool = True,
    has_uvs: bool = True,
) -> str:
    """Identifies normal map semantic from filename suffixes and geometric basis."""
    if not has_tangents or not has_uvs:
        return "NO_NORMAL"
    fn = Path(texture_filename).stem.lower() if texture_filename else ""
    if fn.endswith("_ddna") or "_ddna" in fn:
        return "KCD2_DDNA"
    if fn.endswith("_ddn") or "_ddn" in fn:
        return "KCD2_DDN"
    if slot_name.lower() in ("bumpmap", "normal") and not fn:
        return "KCD2_DDNA"
    if fn.endswith("_norm") or fn.endswith("_normal"):
        return "STANDARD_NORMAL"
    if slot_name.lower() in ("bumpmap", "normal"):
        return "KCD2_DDNA"
    return "STANDARD_NORMAL"


def spec_gloss_to_metallic(diffuse_rgb: tuple[float, float, float], specular_rgb: tuple[float, float, float]) -> float:
    """Khronos PBR quadratic conversion from Specular/Gloss to Metallic factor."""
    d = [max(0.0, min(1.0, float(c))) for c in diffuse_rgb]
    s = [max(0.0, min(1.0, float(c))) for c in specular_rgb]
    db = math.sqrt(0.299 * d[0] * d[0] + 0.587 * d[1] * d[1] + 0.114 * d[2] * d[2])
    sb = math.sqrt(0.299 * s[0] * s[0] + 0.587 * s[1] * s[1] + 0.114 * s[2] * s[2])
    if sb < 0.04:
        return 0.0
    one_minus = 1.0 - max(s)
    a = 0.04
    b = db * one_minus / 0.96 + sb - 0.08
    c = 0.04 - sb
    det = max(0.0, b * b - 4.0 * a * c)
    return max(0.0, min(1.0, (-b + math.sqrt(det)) / (2.0 * a)))


def classify_kcd2_material(
    name: str,
    shader: str = "Illum",
    surface_type: str = "",
    shininess: float = 255.0,
    specular_color: tuple[float, float, float] = (0.23, 0.23, 0.23),
    diffuse_color: tuple[float, float, float] = (1.0, 1.0, 1.0),
    opacity: float = 1.0,
    alpha_test: float = 0.0,
    textures: dict[str, str] | None = None,
    public_params: dict[str, str] | None = None,
    source_attributes: dict[str, str] | None = None,
    has_tangents: bool = True,
    has_uvs: bool = True,
    submaterial_id: int = 0,
    asset_name: str = "",
) -> KCD2MaterialDescription:
    """Classifies a KCD2 CryEngine material definition into physically plausible PBR parameters.

    Generic rules:
    - No asset-name hardcoding
    - Linearizes sRGB specular values (0.238 sRGB -> 0.042 linear F0 dielectric)
    - Distinguishes texture multiplier Specular=(1,1,1) from conductor reflectivity
    - Detects shader families: Illum, Hair, Eye, Vegetation, HumanSkin, Nodraw
    - Safely suppresses non-visual overlay shaders (%EYE_AO_OVERLAY% / HideMask=0)
    - Preserves diffuse reflection for dielectrics and wooden weapon hafts
    - Ensures finite physical IOR (1.50) and clamped GGX roughness
    """
    if hasattr(name, "name") and not isinstance(name, str):
        submat = name
        name = getattr(submat, "name", "")
        shader = getattr(submat, "shader", shader)
        surface_type = getattr(submat, "surface_type", surface_type)
        shininess = getattr(submat, "shininess", shininess)
        specular_color = getattr(submat, "specular_color", specular_color)
        diffuse_color = getattr(submat, "diffuse_color", diffuse_color)
        opacity = getattr(submat, "opacity", opacity)
        alpha_test = getattr(submat, "alpha_test", alpha_test)
        textures = getattr(submat, "textures", textures) or {}
        public_params = getattr(submat, "public_params", public_params) or {}
        source_attributes = getattr(submat, "source_attributes", source_attributes) or {}
        submaterial_id = getattr(submat, "id", submaterial_id)

    textures = textures or {}
    public_params = public_params or {}
    source_attributes = source_attributes or {}

    mat_name_l = str(name).lower().strip()
    shader_l = shader.lower().strip()
    surface_l = surface_type.lower().strip()

    diff_tex = textures.get("Diffuse", "")
    norm_tex = textures.get("Bumpmap", "")
    spec_tex = textures.get("Specular", "")
    custom_tex = textures.get("Custom", "")
    opacity_tex = textures.get("Opacity", "")

    diff_file_l = Path(diff_tex).name.lower() if diff_tex else ""
    norm_file_l = Path(norm_tex).name.lower() if norm_tex else ""

    fallback_reason = ""
    is_hidden = False
    is_proxy = False

    if shader_l in ("nodraw", "none") or any(kw in mat_name_l for kw in ("proxy", "shadowproxy", "phys", "$physics")):
        material_family = "PROXY"
        is_proxy = True
        is_hidden = True
    elif shader_l in ("hair", "fur"):
        material_family = "HAIR_FUR"
    elif shader_l == "eye":
        material_family = "EYE"
    elif shader_l in ("vegetation", "foliage", "leaves"):
        material_family = "VEGETATION"
    elif shader_l in ("humanskin", "skin"):
        material_family = "HUMAN_SKIN"
    elif shader_l in ("illum", "default"):
        material_family = "STANDARD_PBR"
    else:
        material_family = "UNSUPPORTED"
        fallback_reason = f"UNSUPPORTED KCD2 SHADER: {shader} (using neutral dielectric fallback)"
        log.info(
            "\n[FALLBACK MATERIAL]\nAsset:          %s\nMaterial:       %s (ID %d)\nShader:         %s\n"
            "Reason:         %s\nFallback parameters: Roughness=0.70, Metallic=0.00, Specular F0=(0.040, 0.040, 0.040), IOR=1.50\n",
            asset_name or "model", name, submaterial_id, shader, fallback_reason
        )

    # Overlay passes carry debug tints and must not render opaque.
    hide_mask = public_params.get("HideMask", "")
    string_gen_mask = source_attributes.get("StringGenMask", "")
    is_overlay_pass = (
        "%EYE_AO_OVERLAY%" in string_gen_mask
        or "overlay" in mat_name_l
        or hide_mask == "0"
    )

    if material_family == "EYE" and is_overlay_pass:
        is_hidden = True
        fallback_reason = (
            f"CryEngine Eye AO Overlay (%EYE_AO_OVERLAY% / HideMask={hide_mask}) "
            f"is a secondary decal pass, suppressed to prevent solid purple surface corruption"
        )
        log.info(
            "\n[FALLBACK MATERIAL]\nAsset:          %s\nSubmaterial:    %s (ID %d)\nShader:         %s\n"
            "Status:         SUPPRESSED / HIDDEN\nReason:         %s\n",
            asset_name or "model", name, submaterial_id, shader, fallback_reason
        )

    # In CryEngine MTL, Specular attribute is sRGB. Linearize:
    spec_r = max(0.0, min(1.0, float(specular_color[0])))
    spec_g = max(0.0, min(1.0, float(specular_color[1])))
    spec_b = max(0.0, min(1.0, float(specular_color[2])))
    spec_linear = math.pow(max(spec_r, spec_g, spec_b), 2.2)

    has_spec_or_bgs_tex = bool(spec_tex or custom_tex or "_bgs" in norm_file_l)

    # Known dielectric indicators
    is_dielectric_surface = any(
        kw in surface_l for kw in ("wood", "rock", "stone", "flesh", "skin", "fabric", "cloth", "leather", "vegetation", "grass", "foliage", "dirt", "mud", "glass", "hair", "fur", "meat", "thatch")
    )
    is_dielectric_name = any(
        kw in mat_name_l for kw in ("hair", "fur", "body", "skin", "head", "face", "flesh", "eye", "wood", "rope", "cloth", "leather", "plank", "dirt", "rock", "stone", "leaf", "plant", "shaft", "haft", "card")
    ) or any(
        kw in diff_file_l for kw in ("hair", "fur", "body", "skin", "head", "face", "flesh", "eye", "wood", "rope", "cloth", "leather", "plank", "dirt", "rock", "stone", "leaf", "plant", "shaft", "haft", "card")
    )

    if material_family == "STANDARD_PBR" and any(
        kw in surface_l or kw in mat_name_l for kw in ("body", "skin", "fur", "hair", "flesh", "meat")
    ):
        material_family = "ORGANIC_DIELECTRIC"

    # Conductor (metal) classification:
    if material_family in ("HAIR_FUR", "EYE", "VEGETATION", "HUMAN_SKIN", "ORGANIC_DIELECTRIC", "PROXY"):
        is_metal = False
    elif surface_l.startswith("mat_metal") or "metal" in surface_l:
        is_metal = True
    elif is_dielectric_surface or is_dielectric_name:
        is_metal = False
    elif spec_linear < 0.10:
        # Physical law: no conductor has linear specular reflectance below 10%.
        # 0.238 sRGB -> 0.042 linear F0 is standard dielectric (wood/stone/plastic).
        is_metal = False
    elif has_spec_or_bgs_tex and (spec_r >= 0.95 and spec_g >= 0.95 and spec_b >= 0.95):
        # Specular (1,1,1) with a texture is a tint, not metalness.
        # Check if explicitly named metal
        is_metal = any(kw in mat_name_l for kw in ("metal", "iron", "steel", "gold", "silver", "brass", "bronze"))
    else:
        # Fallback to Khronos spec-gloss quadratic conversion
        diff_rgb = (float(diffuse_color[0]), float(diffuse_color[1]), float(diffuse_color[2]))
        spec_rgb = (spec_r, spec_g, spec_b)
        conv_metallic = spec_gloss_to_metallic(diff_rgb, spec_rgb)
        is_metal = conv_metallic > 0.55

    if is_metal:
        metallic = 0.85
        roughness = 0.35
        specular_f0 = (0.75, 0.75, 0.75)
        ior = 2.5
    else:
        metallic = 0.0
        ior = 1.50
        # Dielectrics: standard physical range F0 = 0.02 - 0.05
        if 0.01 <= spec_linear <= 0.08:
            specular_f0 = (spec_linear, spec_linear, spec_linear)
        else:
            specular_f0 = (0.04, 0.04, 0.04)

        if material_family == "HAIR_FUR" or "hair" in mat_name_l or "fur" in mat_name_l:
            roughness = 0.65
        elif material_family == "EYE":
            roughness = 0.12
        elif material_family == "HUMAN_SKIN":
            roughness = 0.55
        elif material_family == "VEGETATION":
            roughness = 0.60
        elif any(kw in surface_l or kw in mat_name_l for kw in ("wood", "rope", "shaft", "haft")):
            roughness = 0.75
        elif any(kw in surface_l or kw in mat_name_l for kw in ("rock", "stone", "masonry", "cobble")):
            roughness = 0.85
        elif any(kw in surface_l or kw in mat_name_l for kw in ("leather", "cloth", "fabric")):
            roughness = 0.70
        elif has_spec_or_bgs_tex:
            roughness = 0.70
        else:
            # Blinn-Phong exponent to GGX roughness, 0.70 when absent.
            if abs(shininess - 255.0) < 1.0:
                roughness = 0.70
            else:
                roughness = max(0.35, min(0.85, 1.0 - (shininess / 350.0)))

    is_hair_or_card = material_family in ("HAIR_FUR", "VEGETATION") or "card" in mat_name_l
    if is_hidden or is_proxy:
        alpha_mode = "MASK"
        alpha_cutoff = 1.0  # Discard all fragments safely
        double_sided = False
    elif is_hair_or_card or alpha_test > 0.01:
        alpha_mode = "MASK"
        alpha_cutoff = alpha_test if alpha_test > 0.01 else (0.50 if is_hair_or_card else 0.25)
        double_sided = True
    elif opacity < 0.95:
        alpha_mode = "BLEND"
        alpha_cutoff = 0.0
        double_sided = False
    else:
        alpha_mode = "OPAQUE"
        alpha_cutoff = 0.5
        double_sided = False

    normal_encoding = detect_normal_semantic(
        texture_filename=norm_tex,
        slot_name="Bumpmap",
        has_tangents=has_tangents,
        has_uvs=has_uvs,
    )
    if normal_encoding == "NO_NORMAL":
        log.info("Material '%s' (ID %d): Normal mapping disabled (no valid tangent/UV basis)", name, submaterial_id)

    if is_hidden:
        base_color_rgba = (0.0, 0.0, 0.0, 0.0)
    else:
        base_color_rgba = (
            float(diffuse_color[0]),
            float(diffuse_color[1]),
            float(diffuse_color[2]),
            float(opacity),
        )

    return KCD2MaterialDescription(
        name=name,
        kcd2_submaterial_id=submaterial_id,
        shader_type=shader,
        surface_type=surface_type,
        material_family=material_family,
        diffuse_texture=diff_tex,
        normal_texture=norm_tex,
        specular_texture=spec_tex,
        gloss_texture=custom_tex,
        opacity_texture=opacity_tex,
        normal_encoding=normal_encoding,
        base_color=base_color_rgba,
        roughness=roughness,
        metallic=metallic,
        specular_f0=specular_f0,
        ior=ior,
        alpha_mode=alpha_mode,
        alpha_cutoff=alpha_cutoff,
        double_sided=double_sided,
        is_hidden=is_hidden,
        is_proxy=is_proxy,
        material_flags=string_gen_mask,
        fallback_reason=fallback_reason,
    )


# Backward compatible helper
def interpret_kcd2_material(
    name: str,
    shader: str = "Illum",
    surface_type: str = "",
    shininess: float = 255.0,
    specular_color: tuple[float, float, float] = (0.23, 0.23, 0.23),
    diffuse_color: tuple[float, float, float] = (1.0, 1.0, 1.0),
    opacity: float = 1.0,
    alpha_test: float = 0.0,
    diffuse_filename: str = "",
    normal_filename: str = "",
    has_bgs: bool = False,
    submaterial_id: int = 0,
    has_tangents: bool = True,
    has_uvs: bool = True,
    asset_name: str = "",
) -> KCD2MaterialDescription:
    textures = {}
    if diffuse_filename:
        textures["Diffuse"] = diffuse_filename
    if normal_filename:
        textures["Bumpmap"] = normal_filename
    if has_bgs:
        textures["Custom"] = "bgs.tif"

    return classify_kcd2_material(
        name=name,
        shader=shader,
        surface_type=surface_type,
        shininess=shininess,
        specular_color=specular_color,
        diffuse_color=diffuse_color,
        opacity=opacity,
        alpha_test=alpha_test,
        textures=textures,
        has_tangents=has_tangents,
        has_uvs=has_uvs,
        submaterial_id=submaterial_id,
        asset_name=asset_name,
    )


def format_diagnostic_report(
    desc: KCD2MaterialDescription,
    source_mtl: str = "embedded",
    diffuse_tex: str = "none",
    normal_tex: str = "none",
    tangent_status: str = "valid (VEC4)",
    uv_status: str = "valid (TEXCOORD_0)",
    triangles: int = 0,
) -> str:
    """Formats a concise developer diagnostic block for a material."""
    lines = [
        f"Material:          {desc.name}",
        f"Shader Family:     {desc.material_family} ({desc.shader_type})",
        f"Surface Type:      {desc.surface_type or '(none)'}",
        f"Source MTL:        {source_mtl}",
        f"Material ID:       {desc.kcd2_submaterial_id}",
        f"Diffuse:           {diffuse_tex}",
        f"Normal:            {normal_tex}",
        f"Normal Encoding:   {desc.normal_encoding}",
        f"Specular F0:       ({desc.specular_f0[0]:.3f}, {desc.specular_f0[1]:.3f}, {desc.specular_f0[2]:.3f})",
        f"Roughness:         {desc.roughness:.2f}",
        f"Metallic:          {desc.metallic:.2f}",
        f"IOR:               {desc.ior:.2f}",
        f"Alpha Mode:        {desc.alpha_mode} (cutoff={desc.alpha_cutoff:.2f}, 2-sided={desc.double_sided})",
        f"Status:            {'HIDDEN / SUPPRESSED' if desc.is_hidden else 'ACTIVE'}",
        f"Tangent Basis:     {tangent_status}",
        f"UV:                {uv_status}",
        f"Triangles:         {triangles:,}",
    ]
    if desc.fallback_reason:
        lines.append(f"Fallback Reason:   {desc.fallback_reason}")
    return "\n".join(lines)


def format_uv_diagnostic(
    asset: str = "",
    primitive: int = 0,
    material: str = "",
    texture: str = "",
    texture_semantic: str = "",
    available_uv_sets: str = "TEXCOORD_0",
    selected_uv_set: str = "TEXCOORD_0",
    uv_range: str = "[0.0, 1.0]",
    wrap_mode: str = "REPEAT",
    texture_dimensions: str = "",
) -> str:
    """Formats a concise developer UV diagnostic block."""
    lines = [
        "[UV DIAGNOSTIC]",
        f"Asset:              {asset}",
        f"Primitive:          {primitive}",
        f"Material:           {material}",
        f"Texture:            {texture}",
        f"Texture Semantic:   {texture_semantic}",
        f"Available UV Sets:  {available_uv_sets}",
        f"Selected UV Set:    {selected_uv_set}",
        f"UV Range:           {uv_range}",
        f"Wrap Mode:          {wrap_mode}",
        f"Texture Dimensions: {texture_dimensions}",
    ]
    return "\n".join(lines)

