"""Build the Windows release: PyInstaller app folder, Inno Setup installer and SHA256SUMS.txt.

    python tools/build_release.py            # app + installer
    python tools/build_release.py --no-installer
"""
from __future__ import annotations

import argparse
import hashlib
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from app.version import APP_NAME, PUBLISHER, VERSION  # noqa: E402

DIST = ROOT / "dist"
BUILD = ROOT / "build"
ISCC_CANDIDATES = (
    Path(os.environ.get("LOCALAPPDATA", "")) / "Programs/Inno Setup 6/ISCC.exe",
    Path(os.environ.get("ProgramFiles(x86)", "")) / "Inno Setup 6/ISCC.exe",
    Path(os.environ.get("ProgramFiles", "")) / "Inno Setup 6/ISCC.exe",
)

VERSION_INFO = """VSVersionInfo(
  ffi=FixedFileInfo(filevers={nums}, prodvers={nums}, mask=0x3f, flags=0x0, OS=0x40004,
                    fileType=0x1, subtype=0x0, date=(0, 0)),
  kids=[
    StringFileInfo([StringTable('040904B0', [
      StringStruct('CompanyName', '{publisher}'),
      StringStruct('FileDescription', '{name}'),
      StringStruct('FileVersion', '{version}'),
      StringStruct('InternalName', 'KCD2ModMaster'),
      StringStruct('OriginalFilename', 'KCD2ModMaster.exe'),
      StringStruct('ProductName', '{name}'),
      StringStruct('ProductVersion', '{version}')])]),
    VarFileInfo([VarStruct('Translation', [1033, 1200])])
  ]
)
"""


def run(cmd: list[str]) -> None:
    print(">", " ".join(cmd), flush=True)
    subprocess.run(cmd, check=True, cwd=ROOT)


def write_version_info() -> None:
    numbers = [int(n) for n in re.findall(r"\d+", VERSION.split("-")[0])[:3]] + [0]
    BUILD.mkdir(exist_ok=True)
    (BUILD / "version_info.txt").write_text(VERSION_INFO.format(
        nums=tuple(numbers), publisher=PUBLISHER, name=APP_NAME, version=VERSION), encoding="utf-8")


def find_iscc() -> Path | None:
    found = shutil.which("ISCC")
    if found:
        return Path(found)
    return next((p for p in ISCC_CANDIDATES if p.is_file()), None)


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--no-installer", action="store_true")
    args = parser.parse_args()

    write_version_info()
    run([sys.executable, "-m", "PyInstaller", "--noconfirm", "--clean",
         "--distpath", str(DIST), "--workpath", str(BUILD / "pyinstaller"), "packaging/modmaster.spec"])
    if args.no_installer:
        return 0

    iscc = find_iscc()
    if iscc is None:
        print("Inno Setup 6 (ISCC.exe) not found. Install it from https://jrsoftware.org/isdl.php")
        return 1
    run([str(iscc), f"/DAppVersion={VERSION}", f"/DSourceDir={DIST / 'KCD2ModMaster'}",
         f"/DOutputDir={DIST}", "packaging/installer.iss"])

    installer = DIST / f"KCD2ModMaster-{VERSION}-Setup.exe"
    (DIST / "SHA256SUMS.txt").write_text(f"{sha256(installer)}  {installer.name}\n", encoding="utf-8")
    print(f"\n{installer}\n{DIST / 'SHA256SUMS.txt'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
