"""Compile the native AVM1 menu without installing any global Flash tooling."""
from pathlib import Path
import argparse
import hashlib
import json
import subprocess

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "runtime/kcd2/modmaster_dev"


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--compiler", required=True, type=Path, help="Path to MTASC 1.14 executable")
    parser.add_argument("--font", required=True, type=Path, help="Licensed TrueType font to embed locally")
    args = parser.parse_args()
    compiler = args.compiler.resolve()
    swf = SOURCE / "Data/Libs/UI/ModMasterMenu.swf"
    source = SOURCE / "ui/ModMasterMenu.as"
    swf.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run([str(compiler), "-cp", str(source.parent), "-version", "8", "-header", "1280:720:30",
                    "-main", "-swf", str(swf), "ModMasterMenu.as"], check=True)
    from embed_runtime_font import embed
    glyphs = embed(swf, args.font)
    data = {"embedded_font_glyphs": glyphs, "font_sha256": hashlib.sha256(args.font.read_bytes()).hexdigest(),"compiler": "MTASC 1.14", "compiler_source": "https://github.com/fdorg/flashdevelop/tree/development/FlashDevelop/Bin/Debug/Tools/mtasc",
            "compiler_sha256": hashlib.sha256(compiler.read_bytes()).hexdigest(),
            "source_sha256": hashlib.sha256(source.read_bytes()).hexdigest(),
            "swf_sha256": hashlib.sha256(swf.read_bytes()).hexdigest(), "swf_version": 8}
    (SOURCE / "ui/build.json").write_text(json.dumps(data, indent=2), encoding="utf-8")
    print(f"Compiled {swf}")


if __name__ == "__main__":
    main()
