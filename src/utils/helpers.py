"""Formatting helpers."""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

# Console tools (converter, headless Blender) otherwise flash a command window over the app on every call.
NO_WINDOW = 0x08000000 if sys.platform == "win32" else 0


def human_size(n: int | None) -> str:
    if n is None:
        return "—"
    f = float(n)
    for unit in ("B", "KB", "MB", "GB"):
        if f < 1024 or unit == "GB":
            return f"{int(f)} {unit}" if unit == "B" else f"{f:.1f} {unit}"
        f /= 1024
    return f"{f:.1f} GB"


def is_within(child: Path, parent: Path) -> bool:
    try:
        child.resolve().relative_to(parent.resolve())
        return True
    except (ValueError, OSError):
        return False


def reveal_in_explorer(path: Path) -> None:
    path = Path(path)
    if sys.platform == "win32":
        if path.is_file():
            subprocess.Popen(["explorer", "/select,", str(path)])
        else:
            os.startfile(str(path if path.exists() else path.parent))  # noqa: S606
    else:
        subprocess.Popen(["xdg-open", str(path if path.is_dir() else path.parent)])
