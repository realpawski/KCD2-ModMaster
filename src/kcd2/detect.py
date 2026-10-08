"""Detection of Steam libraries, KCD2, KCD2 Modding Tools and Blender."""
from __future__ import annotations

import logging
import os
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path

log = logging.getLogger(__name__)

KCD2_APPID = "1771300"
KCD2_INSTALLDIR = "KingdomComeDeliverance2"
KCD2MOD_APPID = "2429020"
KCD2MOD_INSTALLDIR = "KCD2Mod"

GAME_EXE_REL = Path("Bin/Win64MasterMasterSteamPGO/KingdomCome.exe")
RC_EXE_REL = Path("Tools/rc/rc.exe")
EDITOR_EXE_REL = Path("Bin/Win64ReleaseSteamLTO_DLL/Editor.exe")


@dataclass
class Validation:
    ok: bool
    problems: list[str] = field(default_factory=list)
    info: list[str] = field(default_factory=list)


def steam_root() -> Path | None:
    candidates: list[str] = []
    if sys.platform == "win32":
        try:
            import winreg

            for hive, key, val in (
                (winreg.HKEY_CURRENT_USER, r"Software\Valve\Steam", "SteamPath"),
                (winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\WOW6432Node\Valve\Steam", "InstallPath"),
                (winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\Valve\Steam", "InstallPath"),
            ):
                try:
                    with winreg.OpenKey(hive, key) as k:
                        candidates.append(winreg.QueryValueEx(k, val)[0])
                except OSError:
                    pass
        except ImportError:
            pass
    candidates += [r"C:\Program Files (x86)\Steam", r"C:\Program Files\Steam"]
    for c in candidates:
        p = Path(c)
        if (p / "steamapps").is_dir():
            return p
    return None


def parse_library_paths(vdf_text: str) -> list[Path]:
    paths = []
    for m in re.finditer(r'"path"\s+"((?:[^"\\]|\\.)*)"', vdf_text):
        paths.append(Path(m.group(1).replace("\\\\", "\\")))
    return paths


def steam_libraries() -> list[Path]:
    root = steam_root()
    libs: list[Path] = []
    if root:
        libs.append(root)
        for vdf in (root / "steamapps" / "libraryfolders.vdf", root / "config" / "libraryfolders.vdf"):
            if vdf.exists():
                try:
                    libs += parse_library_paths(vdf.read_text(encoding="utf-8", errors="replace"))
                except OSError as e:
                    log.warning("Could not read %s: %s", vdf, e)
    seen, out = set(), []
    for lib in libs:
        key = str(lib).lower().rstrip("\\/")
        if key not in seen and (lib / "steamapps").is_dir():
            seen.add(key)
            out.append(lib)
    return out


def _installdir_from_manifest(manifest: Path) -> str | None:
    try:
        m = re.search(r'"installdir"\s+"([^"]+)"', manifest.read_text(encoding="utf-8", errors="replace"))
        return m.group(1) if m else None
    except OSError:
        return None


def find_steam_app(appid: str, fallback_dir: str) -> Path | None:
    for lib in steam_libraries():
        common = lib / "steamapps" / "common"
        manifest = lib / "steamapps" / f"appmanifest_{appid}.acf"
        if manifest.exists():
            d = _installdir_from_manifest(manifest) or fallback_dir
            if (common / d).is_dir():
                return common / d
        if (common / fallback_dir).is_dir():
            return common / fallback_dir
    return None


def detect_game_dir() -> Path | None:
    p = find_steam_app(KCD2_APPID, KCD2_INSTALLDIR)
    log.info("KCD2 detection: %s", p or "not found")
    return p


def detect_tools_dir() -> Path | None:
    p = find_steam_app(KCD2MOD_APPID, KCD2MOD_INSTALLDIR)
    log.info("KCD2 Modding Tools detection: %s", p or "not found")
    return p


def validate_game_dir(path: str | Path) -> Validation:
    if not path:
        return Validation(False, ["No KCD2 folder selected."])
    p = Path(path)
    v = Validation(True)
    if not p.is_dir():
        return Validation(False, [f"Folder does not exist:\n{p}"])
    data = p / "Data"
    if not data.is_dir():
        v.ok = False
        v.problems.append(
            f"Could not find the 'Data' folder.\nExpected:\n{data}\n\n"
            "Select the KCD2 root folder (the one containing Bin, Data, Engine)."
        )
        return v
    paks = list(data.glob("*.pak"))
    if not paks:
        v.ok = False
        v.problems.append(f"No .pak archives found in\n{data}")
    else:
        v.info.append(f"{len(paks)} archives in Data")
    for required in ("Objects-part0.pak", "IPL_Objects-part0.pak", "Textures-part0.pak"):
        if not (data / required).exists():
            v.problems.append(f"Could not locate {required}.\nExpected:\n{data / required}")
    if (p / GAME_EXE_REL).exists():
        v.info.append("KingdomCome.exe found")
    else:
        v.problems.append(f"Game executable not found at expected location:\n{p / GAME_EXE_REL}")
    return v


def validate_tools_dir(path: str | Path) -> Validation:
    if not path:
        return Validation(False, ["No KCD2 Modding Tools folder selected (optional for Milestone 1)."])
    p = Path(path)
    if not p.is_dir():
        return Validation(False, [f"Folder does not exist:\n{p}"])
    v = Validation(True)
    if (p / RC_EXE_REL).exists():
        v.info.append("Resource Compiler (rc.exe) found")
    else:
        v.ok = False
        v.problems.append(f"Resource Compiler not found.\nExpected:\n{p / RC_EXE_REL}")
    if (p / EDITOR_EXE_REL).exists():
        v.info.append("Editor.exe found")
    return v


def _blender_version_key(p: Path) -> tuple:
    m = re.search(r"(\d+)\.(\d+)", str(p))
    return (int(m.group(1)), int(m.group(2))) if m else (0, 0)


def detect_blender_candidates() -> list[Path]:
    """Hints only – portable installs must be chosen manually."""
    found: list[Path] = []
    for base in (os.environ.get("ProgramFiles", r"C:\Program Files"), os.environ.get("ProgramFiles(x86)", "")):
        if base:
            found += Path(base, "Blender Foundation").glob("*/blender.exe")
    for lib in steam_libraries():
        exe = lib / "steamapps" / "common" / "Blender" / "blender.exe"
        if exe.exists():
            found.append(exe)
    if sys.platform == "win32":
        try:
            import winreg

            with winreg.OpenKey(winreg.HKEY_CLASSES_ROOT, r"blendfile\shell\open\command") as k:
                cmd = winreg.QueryValueEx(k, "")[0]
                m = re.match(r'"([^"]+blender[^"]*\.exe)"', cmd, re.I)
                if m and Path(m.group(1)).exists():
                    found.append(Path(m.group(1)))
        except OSError:
            pass
    uniq = {str(p).lower(): p for p in found}
    return sorted(uniq.values(), key=_blender_version_key, reverse=True)
