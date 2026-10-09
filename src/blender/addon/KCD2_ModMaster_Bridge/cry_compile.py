"""Compiles FBX and TIF files to KCD2 game formats with Warhorse's Resource Compiler.

Imports nothing from Blender so ModMaster can use the same code.
"""
from __future__ import annotations

import os
import re
import shutil
import struct
import subprocess
import tempfile
from pathlib import Path
from xml.sax.saxutils import quoteattr

RC_REL = Path("steamapps/common/KCD2Mod/Tools/rc/rc.exe")
OBJECTS_ROOT = "Objects/modmaster"
WHITE = "EngineAssets/Textures/white.dds"
CHUNK_MTLNAME = 0x1014


class CompileError(Exception):
    pass


def _steam_libraries() -> list[Path]:
    roots = []
    if os.name == "nt":
        try:
            import winreg
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, r"Software\Valve\Steam") as key:
                roots.append(Path(winreg.QueryValueEx(key, "SteamPath")[0]))
        except OSError:
            pass
    roots += [Path(r"C:\Program Files (x86)\Steam"), Path(r"C:\Program Files\Steam")]
    libraries = []
    for root in roots:
        vdf = root / "steamapps" / "libraryfolders.vdf"
        if vdf.is_file():
            text = vdf.read_text(encoding="utf-8", errors="replace")
            libraries += [Path(p.replace("\\\\", "\\")) for p in re.findall(r'"path"\s+"([^"]+)"', text)]
        libraries.append(root)
    seen, result = set(), []
    for lib in libraries:
        key = str(lib).lower()
        if key not in seen:
            seen.add(key)
            result.append(lib)
    return result


def find_rc(*hints: str | Path | None) -> Path | None:
    """rc.exe from a given path or tools folder, else from any Steam library with KCD2 Modding Tools."""
    for hint in hints:
        if not hint:
            continue
        p = Path(hint)
        for candidate in (p, p / "rc.exe", p / "Tools" / "rc" / "rc.exe"):
            if candidate.is_file() and candidate.name.lower() == "rc.exe":
                return candidate
    for lib in _steam_libraries():
        candidate = lib / RC_REL
        if candidate.is_file():
            return candidate
    return None


def _run(rc: Path, filename: str, cwd: Path, *args: str) -> str:
    flags = 0x08000000 if os.name == "nt" else 0
    result = subprocess.run([str(rc), filename, *args], cwd=cwd, capture_output=True, text=True,
                            errors="replace", timeout=600, creationflags=flags)
    log = result.stdout + result.stderr
    if result.returncode != 0:
        errors = [line.split(">", 1)[-1].strip() for line in log.splitlines() if line.lstrip().startswith("E:")]
        raise CompileError("\n".join(errors[-5:]) or f"rc.exe exited with code {result.returncode}")
    return log


def read_cgf_materials(data: bytes) -> tuple[str, list[str]]:
    """Material library name and sub-material names stored in a compiled CGF."""
    if data[:4] != b"CrCh":
        raise CompileError("Not a compiled CryEngine model.")
    _version, count, table = struct.unpack_from("<III", data, 4)
    for i in range(count):
        kind, _ver, _cid, size, offset = struct.unpack_from("<HHIII", data, table + i * 16)
        if kind != CHUNK_MTLNAME:
            continue
        chunk = data[offset:offset + size]
        name = chunk[:128].split(b"\0")[0].decode("latin-1")
        subs = max(struct.unpack_from("<i", chunk, 128)[0], 0)
        names = chunk[132 + 4 * subs:].split(b"\0")[:subs]
        return name, [n.decode("latin-1") for n in names]
    return "", []


def compile_model(rc: Path, fbx: Path, target_cgf: Path, material_path: str) -> list[str]:
    """Compile an FBX to target_cgf and return the sub-material names in slot order."""
    with tempfile.TemporaryDirectory(prefix="kcd2_rc_") as tmp:
        work = Path(tmp)
        source = work / f"{target_cgf.stem}.fbx"
        shutil.copy2(fbx, source)
        _run(rc, source.name, work, f"/setmtl={material_path}")
        built = work / f"{target_cgf.stem}.cgf"
        if not built.is_file():
            raise CompileError("rc.exe finished without writing a .cgf file.")
        data = built.read_bytes()
        _name, subs = read_cgf_materials(data)
        target_cgf.parent.mkdir(parents=True, exist_ok=True)
        target_cgf.write_bytes(data)
        return subs


def compile_texture(rc: Path, image: Path, target_dds: Path, preset: str = "Albedo") -> Path:
    """Compile a TIF to DDS. Other formats must be converted to TIF first."""
    with tempfile.TemporaryDirectory(prefix="kcd2_rc_") as tmp:
        work = Path(tmp)
        source = work / f"{target_dds.stem}.tif"
        shutil.copy2(image, source)
        _run(rc, source.name, work, f"/preset={preset}")
        built = source.with_suffix(".dds")
        if not built.is_file():
            raise CompileError(f"rc.exe did not produce a texture for {image.name}.")
        target_dds.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(built, target_dds)
        return target_dds


def _color(values) -> str:
    return ",".join(f"{float(v):.4g}" for v in list(values)[:3])


def submaterial_xml(sub: dict) -> str:
    """One <Material> element. sub: name, shader, diffuse, textures {Map: path}, attributes, public_params."""
    attrs = {"Name": sub["name"], "MtlFlags": "524416", "Shader": sub.get("shader", "Illum"),
             "StringGenMask": "", "SurfaceType": sub.get("surface_type", "mat_default"),
             "Diffuse": _color(sub.get("diffuse", (1, 1, 1))), "Specular": "0.04,0.04,0.04",
             "Opacity": "1", "Shininess": "64"}
    textures = dict(sub.get("textures") or {})
    if "Bumpmap" in textures:
        attrs["StringGenMask"] = "%NORMAL_MAP"
    attrs.update(sub.get("attributes") or {})
    attrs["Name"] = sub["name"]
    head = " ".join(f"{k}={quoteattr(str(v))}" for k, v in attrs.items())
    lines = [f"  <Material {head}>", "   <Textures>"]
    for slot, path in (textures or {"Diffuse": WHITE}).items():
        lines.append(f"    <Texture Map={quoteattr(slot)} File={quoteattr(path)}/>")
    lines.append("   </Textures>")
    params = sub.get("public_params") or {}
    if params:
        lines.append("   <PublicParams " + " ".join(f"{k}={quoteattr(str(v))}" for k, v in params.items()) + "/>")
    lines.append("  </Material>")
    return "\n".join(lines)


def write_mtl(path: Path, subs: list[dict]) -> Path:
    body = "\n".join(submaterial_xml(s) for s in subs)
    text = ('<Material MtlFlags="524544" vertModifType="0">\n <SubMaterials>\n'
            f"{body}\n </SubMaterials>\n</Material>\n")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path


def slug(text: str) -> str:
    return re.sub(r"[^a-z0-9_]+", "_", text.lower()).strip("_") or "model"


def model_paths(asset_id: str) -> tuple[str, str]:
    """(model virtual path without extension, texture folder) inside the game's file system."""
    base = f"{OBJECTS_ROOT}/{asset_id}"
    return f"{base}/{asset_id}", f"{base}/textures"


CHUNK_COMPILED_BONES = 0x2000
COMPILED_BONE_SIZE = 584


def read_bone_matrices(data: bytes) -> dict[str, list[float]]:
    """Bone-to-world matrices (3x4, row-major) of every bone stored in a .skin or .chr."""
    if data[:4] != b"CrCh":
        return {}
    _version, count, table = struct.unpack_from("<III", data, 4)
    for i in range(count):
        kind, version, _cid, size, offset = struct.unpack_from("<HHIII", data, table + i * 16)
        if kind != CHUNK_COMPILED_BONES or version != 0x800:
            continue
        bones = {}
        for b in range(size // COMPILED_BONE_SIZE):
            base = offset + b * COMPILED_BONE_SIZE
            name = data[base + 344:base + 568].split(b"\0")[0].decode("latin-1")
            bones[name] = list(struct.unpack_from("<12f", data, base + 296))
        return bones
    return {}


def write_cdf(path: Path, skeleton: str, skin: str, material: str) -> Path:
    text = ('<CharacterDefinition>\n'
            f' <Model File={quoteattr(skeleton)}/>\n'
            ' <AttachmentList>\n'
            f'  <Attachment Type="CA_SKIN" AName="body" Binding={quoteattr(skin)} Material={quoteattr(material)} '
            'Flags="0"/>\n'
            ' </AttachmentList>\n'
            '</CharacterDefinition>\n')
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path


def compile_skin(rc: Path, dae: Path, target_skin: Path) -> list[str]:
    """Compile a CryEngine Collada file to target_skin and return the sub-material names in slot order."""
    with tempfile.TemporaryDirectory(prefix="kcd2_rc_") as tmp:
        work = Path(tmp)
        shutil.copy2(dae, work / dae.name)
        log = _run(rc, dae.name, work)
        errors = [line.split(">", 1)[-1].strip() for line in log.splitlines() if line.lstrip().startswith("E:")]
        if errors:
            raise CompileError("\n".join(errors[:3]))
        intermediate = next(work.glob("*.skin"), None)
        if intermediate is None:
            raise CompileError("rc.exe finished without writing a .skin file.")
        # Collada yields the exporter's intermediate chunks; a second pass builds the game format.
        _run(rc, intermediate.name, work, f"/targetroot={work / 'out'}")
        built = work / "out" / intermediate.name
        if not built.is_file():
            raise CompileError("rc.exe did not finish the .skin file.")
        data = built.read_bytes()
        _name, subs = read_cgf_materials(data)
        target_skin.parent.mkdir(parents=True, exist_ok=True)
        target_skin.write_bytes(data)
        return subs


# --- Substance Painter -------------------------------------------------------------------------------------

PAINTER_PATHS = (
    Path(r"C:\Program Files\Adobe\Adobe Substance 3D Painter\Adobe Substance 3D Painter.exe"),
    Path(r"C:\Program Files\Allegorithmic\Substance Painter\Substance Painter.exe"),
)
SUBSTANCE_CHANNELS = (
    ("basecolor", "base"), ("albedo", "base"), ("diffuse", "base"),
    ("normaldirectx", "normal"), ("normalopengl", "normal"), ("normal", "normal"),
    ("roughness", "roughness"), ("metalness", "metallic"), ("metallic", "metallic"),
)
IMAGE_SUFFIXES = (".png", ".tga", ".tif", ".tiff", ".jpg", ".jpeg", ".exr")


def find_painter(configured: str | None = None) -> Path | None:
    candidates = [Path(configured)] if configured else []
    candidates += list(PAINTER_PATHS)
    for library in _steam_libraries():
        common = library / "steamapps" / "common"
        if common.is_dir():
            candidates += sorted(common.glob("*Substance*Painter*/*Painter*.exe"))
    return next((c for c in candidates if c.is_file()), None)


def _key(text: str) -> str:
    return re.sub(r"[^a-z0-9]", "", text.lower())


def texture_set(material_name: str) -> str:
    """The name Painter gives a material's texture set, without ModMaster's own suffix."""
    return re.sub(r"\s*\[ModMaster\]$", "", material_name)


def match_substance_textures(files: list[Path], material_names: list[str]) -> dict[str, dict[str, Path]]:
    """material -> {base|normal|roughness|metallic: file} from Painter's <TextureSet>_<Channel> exports."""
    wanted = {_key(texture_set(name)): name for name in material_names}
    result: dict[str, dict[str, Path]] = {}
    for file in sorted(files):
        if file.suffix.lower() not in IMAGE_SUFFIXES:
            continue
        stem = _key(file.stem)
        for channel, slot in SUBSTANCE_CHANNELS:
            if stem.endswith(channel) and stem[:-len(channel)] in wanted:
                result.setdefault(wanted[stem[:-len(channel)]], {}).setdefault(slot, file)
                break
    return result


def write_tiff_rgba(path: Path, width: int, height: int, pixels: bytes) -> Path:
    """An uncompressed 8-bit RGBA TIFF; rows top to bottom. The alpha channel survives, unlike Blender's saver."""
    if len(pixels) != width * height * 4:
        raise ValueError("Pixel data does not match the image size")
    entries = [
        (256, 4, 1, width), (257, 4, 1, height), (258, 3, 4, None), (259, 3, 1, 1), (262, 3, 1, 2),
        (273, 4, 1, None), (277, 3, 1, 4), (278, 4, 1, height), (279, 4, 1, len(pixels)), (284, 3, 1, 1),
        (338, 3, 1, 2),
    ]
    ifd_offset = 8
    ifd_size = 2 + len(entries) * 12 + 4
    bits_offset = ifd_offset + ifd_size
    data_offset = bits_offset + 8
    out = bytearray(struct.pack("<2sHI", b"II", 42, ifd_offset))
    out += struct.pack("<H", len(entries))
    for tag, kind, count, value in entries:
        if tag == 258:
            out += struct.pack("<HHII", tag, kind, count, bits_offset)
        elif tag == 273:
            out += struct.pack("<HHII", tag, kind, count, data_offset)
        elif kind == 3:
            out += struct.pack("<HHIHH", tag, kind, count, value, 0)
        else:
            out += struct.pack("<HHII", tag, kind, count, value)
    out += struct.pack("<I", 0)
    out += struct.pack("<4H", 8, 8, 8, 8)
    out += pixels
    Path(path).write_bytes(bytes(out))
    return Path(path)
