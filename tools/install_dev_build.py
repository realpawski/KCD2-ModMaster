"""Builds the app and updates the local installation in place, for testing between releases.

Waits until the running ModMaster is closed, replaces the program files (settings in %APPDATA% and the
workspace stay untouched) and starts it again. No version change and no installer are involved.
"""
from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DIST = ROOT / "dist" / "KCD2ModMaster"
EXE = "KCD2ModMaster.exe"
DEFAULT_TARGET = Path(os.environ.get("LOCALAPPDATA", "")) / "Programs" / "KCD2 ModMaster"


def running() -> bool:
    # German Windows answers with umlauts in the console code page; the default decoder gave no output at all.
    out = subprocess.run(["tasklist", "/FI", f"IMAGENAME eq {EXE}", "/NH"], capture_output=True, text=True,
                         encoding="oem", errors="replace").stdout or ""
    return EXE.lower() in out.lower()


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--skip-build", action="store_true")
    parser.add_argument("--target", type=Path, default=DEFAULT_TARGET)
    parser.add_argument("--no-start", action="store_true")
    args = parser.parse_args()

    if not (args.target / EXE).is_file():
        print(f"No installation found in {args.target}")
        return 1
    # A second run would rebuild dist/ while the first one still copies from it.
    lock = Path(tempfile.gettempdir()) / "kcd2_modmaster_install_dev_build.lock"
    try:
        handle = os.open(lock, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
    except FileExistsError:
        print(f"Another update is running; remove {lock} if it is stale.")
        return 1
    os.close(handle)
    try:
        return _update(args)
    finally:
        lock.unlink(missing_ok=True)


def _update(args) -> int:
    if not args.skip_build:
        subprocess.run([sys.executable, str(ROOT / "tools" / "build_release.py"), "--no-installer"], check=True)
    if not (DIST / EXE).is_file():
        print(f"Build output missing: {DIST}")
        return 1
    if running():
        print("Waiting for ModMaster to close...", flush=True)
        while running():
            time.sleep(2)
        time.sleep(1)
    internal = args.target / "_internal"
    if internal.is_dir():
        shutil.rmtree(internal)
    shutil.copytree(DIST, args.target, dirs_exist_ok=True)
    print(f"Updated {args.target}")
    if not args.no_start:
        subprocess.Popen([str(args.target / EXE)], cwd=str(args.target), close_fds=True,
                         creationflags=0x00000008 | 0x00000200)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
