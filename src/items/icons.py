"""Inventory icons for mod items: any image becomes the game's 64 x 64 icon texture."""
from __future__ import annotations

import struct
from pathlib import Path

ICON_SIZE = 64
ICONS_DIR = "icons"
ICON_HINT = (f"{ICON_SIZE} x {ICON_SIZE} px PNG with a transparent background, the size of the game's "
             "inventory icons. Larger images are scaled down and centred.")


def icon_id(mod_id: str, item_id: str) -> str:
    return f"{mod_id}_{item_id}"


def icon_game_path(icon: str) -> str:
    return f"Libs/UI/Textures/Icons/Items/{icon}_icon.dds"


def normalize_icon(source: Path):
    """The image fitted into a transparent 64 x 64 square, keeping its proportions."""
    from PIL import Image

    with Image.open(source) as img:
        img = img.convert("RGBA")
        img.thumbnail((ICON_SIZE, ICON_SIZE), Image.LANCZOS)
        square = Image.new("RGBA", (ICON_SIZE, ICON_SIZE), (0, 0, 0, 0))
        square.paste(img, ((ICON_SIZE - img.width) // 2, (ICON_SIZE - img.height) // 2), img)
        return square


def store_icon(source: Path, project_dir: Path, item_id: str) -> str:
    """Saves the fitted icon in the mod and returns its path relative to the mod folder."""
    relative = f"{ICONS_DIR}/{item_id}.png"
    target = Path(project_dir) / relative
    target.parent.mkdir(parents=True, exist_ok=True)
    normalize_icon(source).save(target)
    return relative


def icon_dds(png: Path) -> bytes:
    """An uncompressed 32-bit DDS, which the game's texture loader reads like its own icons."""
    from PIL import Image

    with Image.open(png) as img:
        img = img.convert("RGBA")
        if img.size != (ICON_SIZE, ICON_SIZE):
            img = normalize_icon(png)
        r, g, b, a = img.split()
        pixels = Image.merge("RGBA", (b, g, r, a)).tobytes()
    flags = 0x1 | 0x2 | 0x4 | 0x8 | 0x1000  # caps, height, width, pitch, pixel format
    header = struct.pack("<4sIIIIIII44x", b"DDS ", 124, flags, ICON_SIZE, ICON_SIZE, ICON_SIZE * 4, 0, 0)
    pixel_format = struct.pack("<IIIIIIII", 32, 0x41, 0, 32, 0x00FF0000, 0x0000FF00, 0x000000FF, 0xFF000000)
    caps = struct.pack("<IIII4x", 0x1000, 0, 0, 0)
    return header + pixel_format + caps + pixels
