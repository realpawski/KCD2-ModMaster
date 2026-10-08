"""KCD2 ModMaster Bridge — Texture Management & Semantic Decoder.

Handles texture loading, DDS format inspection, semantic detection for CryEngine/KCD2
textures (_ddn, _ddna, _diff, _spec, _bgs), color space assignment, and diagnostics.
"""
from __future__ import annotations

import logging
import struct
from enum import Enum
from pathlib import Path
from typing import Any

import bpy

log = logging.getLogger("KCD2_ModMaster_Bridge.textures")


class TextureSemantic(str, Enum):
    DIFFUSE = 'DIFFUSE'
    NORMAL_STANDARD = 'NORMAL_STANDARD'
    NORMAL_DDN = 'NORMAL_DDN'
    NORMAL_DDNA = 'NORMAL_DDNA'
    SPECULAR = 'SPECULAR'
    GLOSS = 'GLOSS'
    ROUGHNESS = 'ROUGHNESS'
    ALPHA = 'ALPHA'
    MASK = 'MASK'
    UNKNOWN = 'UNKNOWN'


def classify_texture(slot, filename):
    if slot in ('Bumpmap', 'Normal'):
        stem = Path(filename).stem.lower()
        return TextureSemantic.NORMAL_DDNA if stem.endswith('_ddna') else TextureSemantic.NORMAL_DDN if stem.endswith('_ddn') else TextureSemantic.NORMAL_STANDARD
    if slot == 'Custom' and Path(filename).stem.lower().endswith('_bgs'):
        return TextureSemantic.MASK
    return {'Diffuse': TextureSemantic.DIFFUSE, 'Specular': TextureSemantic.SPECULAR,
            'Gloss': TextureSemantic.GLOSS, 'Roughness': TextureSemantic.ROUGHNESS,
            'Opacity': TextureSemantic.ALPHA}.get(slot, TextureSemantic.UNKNOWN)

# DXGI Format constants
DXGI_FORMAT_UNKNOWN = 0
DXGI_FORMAT_R8G8B8A8_UNORM = 28
DXGI_FORMAT_BC1_UNORM = 71
DXGI_FORMAT_BC1_UNORM_SRGB = 72
DXGI_FORMAT_BC2_UNORM = 74
DXGI_FORMAT_BC3_UNORM = 77
DXGI_FORMAT_BC3_UNORM_SRGB = 78
DXGI_FORMAT_BC4_UNORM = 80
DXGI_FORMAT_BC5_UNORM = 83
DXGI_FORMAT_BC5_SNORM = 84
DXGI_FORMAT_BC7_UNORM = 98
DXGI_FORMAT_BC7_UNORM_SRGB = 99


def inspect_dds_header(file_path: Path) -> dict[str, Any]:
    """Inspects a DDS header on disk to determine dimensions, compression format, and DXGI type."""
    info: dict[str, Any] = {
        "valid": False,
        "width": 0,
        "height": 0,
        "fourcc": "",
        "dxgi_format": 0,
        "format_name": "Unknown",
        "channels_desc": "Unknown",
    }
    if not file_path.is_file():
        return info

    try:
        with open(file_path, "rb") as f:
            header = f.read(148)
        if len(header) < 128 or header[:4] != b"DDS ":
            return info

        info["valid"] = True
        height, width = struct.unpack("<II", header[12:20])
        info["width"] = width
        info["height"] = height

        pf_flags, fourcc, rgb_bits = struct.unpack("<I4sI", header[80:92])
        info["fourcc"] = fourcc.decode("latin1", errors="ignore").rstrip("\x00")

        dxgi = 0
        if fourcc == b"DX10" and len(header) >= 148:
            dxgi = struct.unpack("<I", header[128:132])[0]
        info["dxgi_format"] = dxgi

        # Map DXGI / FourCC to human-readable names
        if dxgi == DXGI_FORMAT_BC5_SNORM:
            info["format_name"] = "BC5_SNORM (DXGI 84 / 3Dc / RGTC2 signed)"
            info["channels_desc"] = "2 Channels: R (Tangent X), G (Tangent Y)"
        elif dxgi == DXGI_FORMAT_BC5_UNORM:
            info["format_name"] = "BC5_UNORM (DXGI 83 / 3Dc unsigned)"
            info["channels_desc"] = "2 Channels: R (Tangent X), G (Tangent Y)"
        elif dxgi in (DXGI_FORMAT_BC1_UNORM, DXGI_FORMAT_BC1_UNORM_SRGB):
            info["format_name"] = "BC1 / DXT1 (DXGI 71/72)"
            info["channels_desc"] = "3 Channels: RGB"
        elif dxgi in (DXGI_FORMAT_BC3_UNORM, DXGI_FORMAT_BC3_UNORM_SRGB):
            info["format_name"] = "BC3 / DXT5 (DXGI 77/78)"
            info["channels_desc"] = "4 Channels: RGB + Alpha"
        elif dxgi == DXGI_FORMAT_BC4_UNORM:
            info["format_name"] = "BC4_UNORM (DXGI 80 / Height/Displacement)"
            info["channels_desc"] = "1 Channel: R"
        elif dxgi in (DXGI_FORMAT_BC7_UNORM, DXGI_FORMAT_BC7_UNORM_SRGB):
            info["format_name"] = "BC7 (DXGI 98/99)"
            info["channels_desc"] = "4 Channels: RGBA"
        elif fourcc == b"DXT1":
            info["format_name"] = "DXT1"
            info["channels_desc"] = "3 Channels: RGB"
        elif fourcc == b"DXT5":
            info["format_name"] = "DXT5"
            info["channels_desc"] = "4 Channels: RGB + Alpha"
        elif fourcc in (b"ATI2", b"BC5S", b"BC5U"):
            info["format_name"] = f"BC5 ({fourcc.decode('latin1')})"
            info["channels_desc"] = "2 Channels: R (Tangent X), G (Tangent Y)"
        else:
            info["format_name"] = f"FourCC: {info['fourcc'] or 'Uncompressed'}, dxgi={dxgi}"
            info["channels_desc"] = "RGB / Standard"
    except Exception as e:
        log.debug("DDS header read exception for %s: %s", file_path, e)

    return info


def detect_normal_semantic(
    texture_name: str,
    file_path: Path | None = None,
) -> dict[str, Any]:
    """Detects texture semantic encoding and builds decoder configuration.

    Distinguishes:
    - KCD2_DDNA: CryEngine 2-channel BC5_SNORM normal map with suffix _ddna
    - KCD2_DDN: CryEngine 2-channel BC5_SNORM normal map with suffix _ddn
    - STANDARD_NORMAL: Conventional 3-channel RGB tangent-space normal map
    """
    stem = Path(texture_name).stem.lower()
    info = inspect_dds_header(file_path) if file_path else {}
    fmt = info.get("dxgi_format")
    semantic = "NORMAL_DDNA" if stem.endswith("_ddna") else "NORMAL_DDN" if stem.endswith("_ddn") else "NORMAL_STANDARD"
    if fmt == 84:
        encoding = "BC5_SNORM_YX"
    elif fmt == 83:
        encoding = "BC5_UNORM_YX"
    elif semantic == "NORMAL_STANDARD" and (not file_path or Path(file_path).suffix.lower() != ".dds" or fmt in (28, 71, 72, 77, 78, 98, 99)):
        encoding = "RGB_XYZ"
    else:
        encoding = "UNKNOWN"
    return {"texture_name": texture_name, "semantic": semantic,
            "encoding": encoding, "decoder": "signed BC5 blocks -> KCD2 .yx -> positive Z -> Blender tangent basis" if fmt == 84 else encoding,
            "green_inversion": fmt in (83, 84), "blue_reconstruction": fmt in (83, 84),
            "alpha_semantic": "separate .dds.a BC4 smoothness" if semantic == "NORMAL_DDNA" else "none",
            "dds_format": info.get("format_name", "Unknown"),
            "channels": {"R": "signed tangent Y", "G": "signed tangent X", "B": "not stored", "A": "not stored"} if fmt == 84 else {},
            "color_space": "Non-Color"}


def log_normal_diagnostics(config: dict[str, Any], status: str = "SUCCESS") -> None:
    """Emits formatted diagnostic block for debugging normal texture interpretation."""
    ch = config.get("channels", {})
    diag = (
        f"\n======================================================================\n"
        f"KCD2 NORMAL MAP DIAGNOSTICS\n"
        f"======================================================================\n"
        f"Normal texture:       {config.get('texture_name', 'Unknown')}\n"
        f"Detected semantic:    {config.get('semantic', 'Unknown')}\n"
        f"DDS format:           {config.get('dds_format', 'Unknown')}\n"
        f"Source channels:\n"
        f"  R = {ch.get('R', '')}\n"
        f"  G = {ch.get('G', '')}\n"
        f"  B = {ch.get('B', '')}\n"
        f"  A = {ch.get('A', '')}\n"
        f"Decoder:              {config.get('decoder', '')}\n"
        f"Green inversion:      {'YES (DirectX Y-down -> Blender OpenGL Y-up)' if config.get('green_inversion') else 'NO'}\n"
        f"Blue reconstruction:  {'YES (Nz = sqrt(max(0, 1 - Nx^2 - Ny^2)))' if config.get('blue_reconstruction') else 'NO'}\n"
        f"Alpha semantic:       {config.get('alpha_semantic', '')}\n"
        f"Blender color space:  {config.get('color_space', 'Non-Color')}\n"
        f"Normal setup:         {status}\n"
        f"======================================================================"
    )
    log.info(diag)
    print(diag)


def reload_workspace_textures(textures_dir: Path) -> int:
    """Reloads all Blender images located within the asset textures directory."""
    if not textures_dir.is_dir():
        return 0

    reloaded = 0
    t_dir_str = str(textures_dir).lower()
    for img in bpy.data.images:
        if img.filepath:
            fp = bpy.path.abspath(img.filepath).lower()
            if t_dir_str in fp:
                try:
                    img.reload()
                    reloaded += 1
                except Exception as e:
                    log.debug("Could not reload image %s: %s", img.name, e)

    return reloaded
