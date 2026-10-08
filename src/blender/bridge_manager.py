"""KCD2 ModMaster Blender Bridge Manager.

Owns:
- Blender Addon lifecycle (install, update, repair, detect status)
- Strictly Localhost IPC Server (127.0.0.1:24952)
- Asset preparation for editable workspace
- One-click launch and automatic asset import into Blender
- Asset revision tracking (VANILLA -> WORKING COPY -> MODIFIED IN BLENDER)
"""
from __future__ import annotations

import json
import logging
import os
import re
import shutil
import socket
import subprocess
import sys
import threading
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Callable

from PySide6.QtCore import QObject, Signal

from app.paths import is_frozen
from archives.pak import PakArchive
from core.config import Settings
from core.tasks import UserFacingError
from database.index import AssetIndex, AssetRow
from materials.mtl_parser import parse_mtl_xml, resolve_and_stage_textures
from preview.converter import (
    combine_cryengine_dds,
    find_converter_exe,
    prepare_3d_preview,
    resolve_mtl_row,
)

log = logging.getLogger(__name__)

DEFAULT_IPC_HOST = "127.0.0.1"
DEFAULT_IPC_PORT = 24952
CURRENT_BRIDGE_VERSION = "1.3.0"
ADDON_NAME = "KCD2_ModMaster_Bridge"


class BridgeStatus:
    NOT_INSTALLED = "Not installed"
    INSTALLED = "Installed ✓"
    OUTDATED = "Outdated"
    BROKEN = "Broken"


@dataclass
class BridgeDetectionResult:
    status: str
    addon_dir: Path | None
    version: str = ""
    is_symlinked: bool = False
    details: str = ""


class BlenderBridgeSignals(QObject):
    """Qt signals for Bridge status and IPC events."""
    connection_changed = Signal(bool)
    asset_imported = Signal(str, str)  # asset_id, asset_name
    asset_exported = Signal(str, str, str)  # asset_id, asset_name, export_path
    log_message = Signal(str)


class BlenderBridgeManager:
    """ModMaster-side manager for Blender 5.2/5.1 integration."""

    _instance: "BlenderBridgeManager | None" = None

    def __init__(self, settings: Settings):
        self.settings = settings
        self.signals = BlenderBridgeSignals()
        self._server_socket: socket.socket | None = None
        self._server_thread: threading.Thread | None = None
        self._stop_event = threading.Event()
        self._clients: list[socket.socket] = []
        self._clients_lock = threading.Lock()
        self._is_connected = False
        self._active_client_info: dict[str, Any] = {}
        self._active_asset_metadata: dict[str, Any] | None = None

        # Start IPC server immediately
        self.start_ipc_server()

    @classmethod
    def get_instance(cls, settings: Settings) -> "BlenderBridgeManager":
        if cls._instance is None:
            cls._instance = cls(settings)
        return cls._instance

    # Addon Deployment & Detection
    @property
    def source_addon_dir(self) -> Path:
        """Path to the authoritative source code of the addon inside ModMaster."""
        return Path(__file__).resolve().parent / "addon" / ADDON_NAME

    def get_target_addon_dirs(self) -> list[Path]:
        """Finds all candidate Blender addons directories in user AppData."""
        candidates = []
        appdata = os.environ.get("APPDATA")
        if appdata:
            base = Path(appdata) / "Blender Foundation" / "Blender"
            if base.is_dir():
                # Check for versions: 5.2, 5.1, 5.0, 4.2
                for ver_dir in base.glob("*"):
                    if ver_dir.is_dir() and re.match(r"^\d+\.\d+$", ver_dir.name):
                        addons_dir = ver_dir / "scripts" / "addons"
                        candidates.append(addons_dir / ADDON_NAME)

        # Sort so 5.2 and 5.1 are first
        def ver_key(p: Path) -> tuple[int, int]:
            m = re.search(r"(\d+)\.(\d+)", str(p))
            return (int(m.group(1)), int(m.group(2))) if m else (0, 0)

        return sorted(candidates, key=ver_key, reverse=True)

    def detect_addon_status(self) -> BridgeDetectionResult:
        """Inspects Blender installation to detect bridge addon status."""
        targets = self.get_target_addon_dirs()
        if not targets:
            return BridgeDetectionResult(
                status=BridgeStatus.NOT_INSTALLED,
                addon_dir=None,
                details="No Blender configuration folders found in AppData."
            )

        # Check primary target (e.g. 5.2 or 5.1)
        primary = targets[0]
        for t in targets:
            if t.exists():
                primary = t
                break

        if not primary.exists():
            return BridgeDetectionResult(
                status=BridgeStatus.NOT_INSTALLED,
                addon_dir=primary,
                details=f"Addon directory not found in {primary.parent}"
            )

        init_file = primary / "__init__.py"
        if not init_file.is_file():
            return BridgeDetectionResult(
                status=BridgeStatus.BROKEN,
                addon_dir=primary,
                details="Missing __init__.py in addon folder."
            )

        # Read version from __init__.py
        installed_version = "unknown"
        try:
            content = init_file.read_text(encoding="utf-8", errors="replace")
            m = re.search(r'"version":\s*\(([^)]+)\)', content)
            if m:
                parts = [p.strip() for p in m.group(1).split(",")]
                installed_version = ".".join(parts)
        except Exception:
            pass

        is_symlink = primary.is_symlink()

        if installed_version == CURRENT_BRIDGE_VERSION:
            return BridgeDetectionResult(
                status=BridgeStatus.INSTALLED,
                addon_dir=primary,
                version=installed_version,
                is_symlinked=is_symlink,
                details=f"Ready for Blender ({'symlinked' if is_symlink else 'copied'})."
            )
        else:
            return BridgeDetectionResult(
                status=BridgeStatus.OUTDATED,
                addon_dir=primary,
                version=installed_version,
                is_symlinked=is_symlink,
                details=f"Installed version {installed_version} differs from required {CURRENT_BRIDGE_VERSION}."
            )

    def install_or_update_addon(self) -> tuple[bool, str]:
        """Installs or updates the bridge addon into Blender's configuration."""
        src = self.source_addon_dir
        if not src.is_dir():
            return False, f"Source addon directory missing: {src}"

        targets = self.get_target_addon_dirs()
        if not targets:
            # Fall back to creating 5.2 and 5.1 in AppData if needed
            appdata = os.environ.get("APPDATA")
            if appdata:
                targets = [
                    Path(appdata) / "Blender Foundation" / "Blender" / "5.2" / "scripts" / "addons" / ADDON_NAME,
                    Path(appdata) / "Blender Foundation" / "Blender" / "5.1" / "scripts" / "addons" / ADDON_NAME,
                ]

        installed_paths = []
        for dst in targets:
            try:
                dst.parent.mkdir(parents=True, exist_ok=True)
                if dst.exists() or dst.is_symlink():
                    if dst.is_symlink() or dst.is_file():
                        dst.unlink()
                    else:
                        shutil.rmtree(dst, ignore_errors=True)

                # A source checkout links the add-on for live edits; the installed app copies it,
                # because a link into the program folder breaks once ModMaster is uninstalled.
                try:
                    if is_frozen():
                        raise OSError("copy")
                    os.symlink(str(src), str(dst), target_is_directory=True)
                    log.info("Linked bridge addon via symlink to %s", dst)
                except (OSError, NotImplementedError):
                    shutil.copytree(src, dst, ignore=shutil.ignore_patterns("__pycache__"))
                    log.info("Copied bridge addon to %s", dst)

                installed_paths.append(str(dst))
            except Exception as e:
                log.warning("Failed to install addon to %s: %s", dst, e)

        if installed_paths:
            # Auto-enable in Blender preferences via headless call if blender_exe is set
            self._try_enable_addon_headless()
            return True, f"Bridge addon installed successfully to:\n" + "\n".join(installed_paths)
        return False, "Could not write to any Blender addon directory."

    def _try_enable_addon_headless(self) -> None:
        """Attempts to enable the addon in user preferences automatically."""
        blender_exe = self.settings.blender_exe
        if not blender_exe or not Path(blender_exe).is_file():
            return
        cmd = [
            blender_exe,
            "-b",
            "--python-expr",
            (
                "import bpy; "
                f"bpy.ops.preferences.addon_enable(module='{ADDON_NAME}'); "
                "bpy.ops.wm.save_userpref(); "
                "print('ADDON_AUTO_ENABLED')"
            )
        ]
        try:
            subprocess.run(cmd, capture_output=True, timeout=10)
        except Exception as e:
            log.debug("Auto-enable headless notice: %s", e)

    # Strictly Localhost IPC Server (127.0.0.1)
    def start_ipc_server(self) -> None:
        """Starts the local TCP server for communication with Blender."""
        if self._server_socket:
            return

        self._stop_event.clear()
        try:
            self._server_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            self._server_socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            # Localhost only.
            self._server_socket.bind((DEFAULT_IPC_HOST, DEFAULT_IPC_PORT))
            self._server_socket.listen(5)
            self._server_socket.settimeout(1.0)

            self._server_thread = threading.Thread(
                target=self._ipc_server_loop,
                daemon=True,
                name="KCD2BridgeIPCServer",
            )
            self._server_thread.start()
            log.info("KCD2 ModMaster Bridge IPC server listening on %s:%d", DEFAULT_IPC_HOST, DEFAULT_IPC_PORT)
        except Exception as e:
            log.warning("Could not start Bridge IPC server on port %d: %s", DEFAULT_IPC_PORT, e)

    def stop_ipc_server(self) -> None:
        """Stops the IPC server."""
        self._stop_event.set()
        if self._server_socket:
            try:
                self._server_socket.close()
            except Exception:
                pass
            self._server_socket = None

        with self._clients_lock:
            for c in self._clients:
                try:
                    c.close()
                except Exception:
                    pass
            self._clients.clear()

        self._is_connected = False
        self.signals.connection_changed.emit(False)

    def _ipc_server_loop(self) -> None:
        while not self._stop_event.is_set():
            try:
                client_sock, addr = self._server_socket.accept()
                # Verify strictly localhost address
                if addr[0] not in ("127.0.0.1", "localhost"):
                    client_sock.close()
                    continue

                with self._clients_lock:
                    self._clients.append(client_sock)

                threading.Thread(
                    target=self._handle_client,
                    args=(client_sock,),
                    daemon=True,
                ).start()
            except socket.timeout:
                continue
            except Exception:
                break

    def _handle_client(self, sock: socket.socket) -> None:
        sock.settimeout(1.0)
        buffer = ""
        self._is_connected = True
        self.signals.connection_changed.emit(True)

        while not self._stop_event.is_set():
            try:
                chunk = sock.recv(4096)
                if not chunk:
                    break
                buffer += chunk.decode("utf-8", errors="replace")
                while "\n" in buffer:
                    line, buffer = buffer.split("\n", 1)
                    line = line.strip()
                    if line:
                        self._process_ipc_message(sock, line)
            except socket.timeout:
                continue
            except Exception:
                break

        with self._clients_lock:
            if sock in self._clients:
                self._clients.remove(sock)
            if not self._clients:
                self._is_connected = False
                self.signals.connection_changed.emit(False)

        try:
            sock.close()
        except Exception:
            pass

    def _process_ipc_message(self, sock: socket.socket, line: str) -> None:
        try:
            msg = json.loads(line)
        except Exception as e:
            log.warning("Invalid JSON received from Blender: %s", e)
            return

        cmd = msg.get("command")
        resp: dict[str, Any] = {"status": "ok"}

        if cmd == "handshake":
            self._active_client_info = msg
            resp = {
                "status": "ok",
                "modmaster_version": "0.2.0",
                "bridge_version": CURRENT_BRIDGE_VERSION,
                "project": "Default Project",
                "workspace": str(self.settings.workspace),
            }
            self.signals.log_message.emit("Blender Bridge connected.")

        elif cmd == "ping":
            resp = {"status": "pong", "bridge_version": CURRENT_BRIDGE_VERSION}

        elif cmd == "get_active_asset":
            resp = {"status": "ok", "metadata": self._active_asset_metadata}

        elif cmd == "asset_exported":
            asset_id = msg.get("asset_id", "")
            asset_name = msg.get("asset_name", "")
            export_file = msg.get("export_file", "")
            log.info("Asset exported from Blender: %s (%s)", asset_name, export_file)
            self.signals.asset_exported.emit(asset_id, asset_name, export_file)
            self.signals.log_message.emit(f"Asset '{asset_name}' exported from Blender to workspace.")
            resp = {"status": "ok", "message": "Export acknowledged"}

        elif cmd == "asset_compiled":
            asset_id = msg.get("asset_id", "")
            model = msg.get("model", "")
            log.info("Asset compiled in Blender: %s (%s)", asset_id, model)
            self.signals.asset_exported.emit(asset_id, asset_id, model)
            self.signals.log_message.emit(f"'{asset_id}' compiled to {model}. Add it to a mod and build.")
            resp = {"status": "ok"}

        elif cmd == "request_build":
            self.signals.log_message.emit(f"Build requested for asset {msg.get('asset_id')}")
            resp = {"status": "ok"}

        # Send response back to Blender
        try:
            sock.sendall((json.dumps(resp) + "\n").encode("utf-8"))
        except Exception as e:
            log.debug("Failed to send IPC response: %s", e)

    def is_blender_connected(self) -> bool:
        """Returns True if Blender is actively connected over IPC."""
        return self._is_connected

    def send_command(self, payload: dict[str, Any]) -> bool:
        """Sends a command to all connected Blender clients."""
        data = (json.dumps(payload) + "\n").encode("utf-8")
        sent = False
        with self._clients_lock:
            dead_clients = []
            for c in self._clients:
                try:
                    c.sendall(data)
                    sent = True
                except Exception:
                    dead_clients.append(c)
            for d in dead_clients:
                self._clients.remove(d)

        return sent

    # Editable Workspace Concept & Staging
    def get_asset_slug(self, row: AssetRow) -> str:
        """Computes a clean directory slug for an asset."""
        stem = Path(row.filename).stem
        return re.sub(r"[^\w\-]", "_", stem)

    @staticmethod
    def rig_source(row: AssetRow, index: AssetIndex) -> AssetRow | None:
        """The skinned file behind a model: the row itself, or a .cdf/.skin next to a static .cgf."""
        ext = row.ext.lower()
        if ext in ("cdf", "skin", "chr"):
            return row
        if ext == "cgf":
            stem = row.vpath.rsplit(".", 1)[0]
            for candidate in ("cdf", "skin"):
                hits = index.find_by_vpath(f"{stem}.{candidate}")
                if hits:
                    return hits[0]
        return None

    def prepare_editable_workspace(
        self,
        row: AssetRow,
        index: AssetIndex,
        progress_cb: Callable[[str], None] | None = None,
        mode: str = "static",
    ) -> dict[str, Any]:
        """Creates the dedicated editable workspace for an asset and prepares GLB interchange."""
        if mode == "rigged":
            source = self.rig_source(row, index)
            if source is None:
                raise UserFacingError(f"{row.filename} has no skeleton to import.")
            return self._prepare_skinned(source, index, progress_cb, keep_rig=True)
        if row.ext.lower() in ("cdf", "skin", "chr"):
            return self._prepare_skinned(row, index, progress_cb, keep_rig=False)
        slug = self.get_asset_slug(row)
        ws_root = self.settings.workspace / "Assets" / slug
        source_dir = ws_root / "source"
        textures_dir = ws_root / "textures"
        blender_dir = ws_root / "blender"
        export_dir = ws_root / "export"
        meta_dir = ws_root / "metadata"

        for d in (source_dir, textures_dir, blender_dir, export_dir, meta_dir):
            d.mkdir(parents=True, exist_ok=True)

        meta_file = meta_dir / ".modmaster_asset.json"
        blend_file = blender_dir / f"{slug}.blend"
        interchange_file = source_dir / f"{slug}_interchange.glb"
        export_glb = export_dir / f"{slug}_exported.glb"
        export_dae = export_dir / f"{slug}_exported.dae"

        # Check if already staged
        existing_meta = None
        if meta_file.is_file():
            try:
                with open(meta_file, "r", encoding="utf-8") as f:
                    existing_meta = json.load(f)
            except Exception:
                pass

        if existing_meta and interchange_file.is_file():
            if progress_cb:
                progress_cb(f"Reusing existing workspace for {slug}...")
            if existing_meta.get("material_schema_version", 0) < 2:
                # Migrate material metadata/attached gloss only; reuse geometry.
                self.sync_textures_for_asset(row, index, progress_cb=progress_cb)
                existing_meta = json.loads(meta_file.read_text(encoding="utf-8"))
            self._active_asset_metadata = existing_meta
            return existing_meta

        if progress_cb:
            progress_cb(f"Extracting vanilla files for {row.filename}...")

        with PakArchive(row.archive_path) as pak:
            target_cgf = pak.extract(row.vpath, source_dir)

        with index.connection(read_only=True) as conn:
            comps = index.companions(row, conn=conn)
            for c in comps:
                if c.ext.lower() in ("cgfm", "skina"):
                    with PakArchive(c.archive_path) as cpak:
                        cpak.extract(c.vpath, source_dir)

            mtl_row = resolve_mtl_row(index, row, conn=conn)
            mtl_file: Path | None = None
            textures_list: list[str] = []
            materials_meta: list[dict[str, Any]] = []

            if mtl_row:
                with PakArchive(mtl_row.archive_path) as mpak:
                    mtl_data = mpak.read(mtl_row.vpath)
                    mtl_file = target_cgf.parent / mtl_row.filename
                    with open(mtl_file, "wb") as f:
                        f.write(mtl_data)

                try:
                    mtl_def = parse_mtl_xml(mtl_data, mtl_vpath=mtl_row.vpath)
                    tot, res, missing = resolve_and_stage_textures(
                        mtl_def, index, textures_dir, conn=conn
                    )
                    textures_list = [
                        str(textures_dir / f)
                        for f in os.listdir(textures_dir)
                        if f.lower().endswith(".dds")
                    ]
                    materials_meta = [asdict(sub) for sub in mtl_def.submaterials]

                    if progress_cb:
                        progress_cb(f"Resolved MTL: {mtl_row.filename} ({len(materials_meta)} submaterials, {len(textures_list)} textures)")
                    self.signals.log_message.emit(
                        f"Resolved materials for {row.filename}: {len(materials_meta)} submaterials, {len(textures_list)} textures staged."
                    )
                except Exception as err:
                    log.warning("MTL texture resolution notice: %s", err)

        if progress_cb:
            progress_cb("Generating interchange GLB asset...")

        conv_exe = find_converter_exe(self.settings)
        if not conv_exe:
            raise UserFacingError("KCD2-Convertor.exe not found.")

        cmd = [str(conv_exe), str(target_cgf), "-glb"]
        if mtl_file and mtl_file.is_file():
            cmd.extend([
                "-material", str(mtl_file),
                "-objectdir", str(textures_dir),
                "-embedtextures",
            ])

        proc = subprocess.run(cmd, capture_output=True, text=True, cwd=str(target_cgf.parent), timeout=60)
        expected_glb = target_cgf.with_suffix(".glb")
        if not expected_glb.is_file():
            glbs = list(target_cgf.parent.glob("*.glb"))
            if glbs:
                expected_glb = glbs[0]
            else:
                raise UserFacingError(f"Converter failed to create GLB: {proc.stdout}")

        # Copy to standardized interchange name
        if expected_glb != interchange_file:
            shutil.copy2(expected_glb, interchange_file)

        meta = {
            "version": CURRENT_BRIDGE_VERSION,
            "asset_id": f"{slug}_{row.size}",
            "asset_name": slug,
            "filename": row.filename,
            "virtual_path": row.vpath,
            "source_archive": row.archive_name,
            "mtl_path": mtl_row.vpath if mtl_row else "",
            "mtl_name": mtl_row.filename if mtl_row else "",
            "project": "Default Project",
            "workspace_dir": str(ws_root),
            "source_dir": str(source_dir),
            "textures_dir": str(textures_dir),
            "blend_file": str(blend_file),
            "interchange_file": str(interchange_file),
            "export_dir": str(export_dir),
            "export_file": str(export_glb),
            "dae_export_file": str(export_dae),
            "status": "unmodified",
            "created_at": time.time(),
            "last_exported": None,
            "textures": textures_list,
            "materials": materials_meta,
            "material_schema_version": 2,
        }

        with open(meta_file, "w", encoding="utf-8") as f:
            json.dump(meta, f, indent=2)

        self._active_asset_metadata = meta
        return meta

    def _skinned_parts(self, src: AssetRow) -> tuple[str, list[tuple[str, str]]]:
        """(skeleton path, [(skin path, material path)]) for a .cdf, .skin or .chr."""
        if src.ext.lower() != "cdf":
            return src.vpath, [(src.vpath, "")]
        from xml.etree import ElementTree as ET
        with PakArchive(src.archive_path) as pak:
            root = ET.fromstring(pak.read(src.vpath))
        model = root.find("Model")
        skeleton = model.get("File", "") if model is not None else ""
        parts = [(a.get("Binding", ""), a.get("Material", ""))
                 for a in root.iter("Attachment")
                 if a.get("Type", "").upper() == "CA_SKIN" and a.get("Binding", "").lower().endswith(".skin")]
        if not parts:
            if not skeleton:
                raise UserFacingError(f"{src.filename} lists no skin attachments.")
            parts = [(skeleton, "")]
        return skeleton, parts

    def _prepare_skinned(self, src: AssetRow, index: AssetIndex,
                         progress_cb: Callable[[str], None] | None, keep_rig: bool) -> dict[str, Any]:
        from preview.skin_uv import inject_skin_uvs

        slug = self.get_asset_slug(src) + ("_rigged" if keep_rig else "_static")
        ws_root = self.settings.workspace / "Assets" / slug
        source_dir, textures_dir = ws_root / "source", ws_root / "textures"
        blender_dir, export_dir, meta_dir = ws_root / "blender", ws_root / "export", ws_root / "metadata"
        for d in (source_dir, textures_dir, blender_dir, export_dir, meta_dir):
            d.mkdir(parents=True, exist_ok=True)
        meta_file = meta_dir / ".modmaster_asset.json"
        if meta_file.is_file():
            try:
                existing = json.loads(meta_file.read_text(encoding="utf-8"))
                if existing.get("parts") and all(Path(p["interchange_file"]).is_file() for p in existing["parts"]):
                    self._active_asset_metadata = existing
                    return existing
            except (OSError, ValueError, KeyError):
                pass

        conv_exe = find_converter_exe(self.settings)
        if not conv_exe:
            raise UserFacingError("KCD2-Convertor.exe not found.")
        skeleton, parts = self._skinned_parts(src)
        parts_meta: list[dict[str, Any]] = []
        with index.connection(read_only=True) as conn:
            for number, (skin_path, mtl_path) in enumerate(parts):
                rows = index.find_by_vpath(skin_path, conn=conn)
                if not rows:
                    log.warning("Skin %s listed in %s is not in the index", skin_path, src.filename)
                    continue
                skin_row = rows[0]
                if progress_cb:
                    progress_cb(f"Extracting {skin_row.filename}...")
                with PakArchive(skin_row.archive_path) as pak:
                    skin_file = pak.extract(skin_row.vpath, source_dir)
                for c in index.companions(skin_row, conn=conn):
                    with PakArchive(c.archive_path) as cpak:
                        cpak.extract(c.vpath, source_dir)

                mtl_row = None
                if mtl_path:
                    found = index.find_by_vpath(mtl_path, conn=conn)
                    mtl_row = found[0] if found else None
                mtl_row = mtl_row or resolve_mtl_row(index, skin_row, conn=conn)
                mtl_file: Path | None = None
                materials: list[dict[str, Any]] = []
                if mtl_row:
                    with PakArchive(mtl_row.archive_path) as mpak:
                        mtl_data = mpak.read(mtl_row.vpath)
                    mtl_file = skin_file.parent / mtl_row.filename
                    mtl_file.write_bytes(mtl_data)
                    try:
                        mtl_def = parse_mtl_xml(mtl_data, mtl_vpath=mtl_row.vpath)
                        resolve_and_stage_textures(mtl_def, index, textures_dir, conn=conn)
                        materials = [asdict(sub) for sub in mtl_def.submaterials]
                    except Exception as err:
                        log.warning("MTL texture resolution notice: %s", err)

                if progress_cb:
                    progress_cb(f"Converting {skin_row.filename} with its skeleton...")
                cmd = [str(conv_exe), str(skin_file), "-glb", "-objectdir", str(textures_dir)]
                if mtl_file:
                    cmd += ["-material", str(mtl_file), "-embedtextures"]
                proc = subprocess.run(cmd, capture_output=True, text=True, cwd=str(skin_file.parent), timeout=120)
                produced = skin_file.with_suffix(".glb")
                if not produced.is_file():
                    raise UserFacingError(f"Converter failed for {skin_row.filename}: {proc.stdout[-500:]}")
                glb = source_dir / f"{slug}_part{number}_{skin_file.stem}.glb"
                shutil.move(str(produced), glb)
                inject_skin_uvs(glb, skin_file)
                parts_meta.append({"interchange_file": str(glb), "materials": materials,
                                   "mtl_path": mtl_row.vpath if mtl_row else "", "virtual_path": skin_row.vpath})
        if not parts_meta:
            raise UserFacingError(f"No skins of {src.filename} could be converted.")

        meta = {
            "version": CURRENT_BRIDGE_VERSION,
            "asset_id": slug,
            "asset_name": slug,
            "filename": src.filename,
            "virtual_path": src.vpath,
            "source_archive": src.archive_name,
            "skeleton": skeleton,
            "rigged": keep_rig,
            "strip_rig": not keep_rig,
            "parts": parts_meta,
            "interchange_file": parts_meta[0]["interchange_file"],
            "materials": parts_meta[0]["materials"],
            "mtl_path": parts_meta[0]["mtl_path"],
            "mtl_name": Path(parts_meta[0]["mtl_path"]).name,
            "project": "Default Project",
            "workspace_dir": str(ws_root),
            "source_dir": str(source_dir),
            "textures_dir": str(textures_dir),
            "blend_file": str(blender_dir / f"{slug}.blend"),
            "export_dir": str(export_dir),
            "export_file": str(export_dir / f"{slug}_exported.glb"),
            "status": "unmodified",
            "created_at": time.time(),
            "last_exported": None,
            "textures": [str(p) for p in textures_dir.glob("*.dds")],
            "material_schema_version": 2,
        }
        meta_file.write_text(json.dumps(meta, indent=2), encoding="utf-8")
        self._active_asset_metadata = meta
        return meta

    # Open in Blender Workflow
    def open_in_blender(
        self,
        row: AssetRow,
        index: AssetIndex,
        progress_cb: Callable[[str], None] | None = None,
        mode: str = "static",
    ) -> None:
        """One-click workflow: stages asset, launches/signals Blender, and imports model."""
        blender_exe = self.settings.blender_exe
        if not blender_exe or not Path(blender_exe).is_file():
            raise UserFacingError(
                "Blender executable not configured.\n"
                "Please set your Blender 5.2/5.1 path in Settings."
            )

        meta = self.prepare_editable_workspace(row, index, progress_cb=progress_cb, mode=mode)
        slug = meta["asset_name"]
        blend_file = Path(meta["blend_file"])

        if self.is_blender_connected():
            if progress_cb:
                progress_cb(f"Sending import job to active Blender session...")

            sent = self.send_command({
                "command": "import_asset",
                "metadata": meta,
            })
            if sent:
                log.info("Sent import_asset command to connected Blender.")
                return

        if progress_cb:
            progress_cb("Launching Blender and initializing ModMaster Bridge...")

        startup_script = self.settings.workspace / "cache" / "bridge_launch.py"
        startup_script.parent.mkdir(parents=True, exist_ok=True)

        meta_json_escaped = json.dumps(meta).replace("\\", "\\\\").replace('"', '\\"')
        script_code = f"""# Auto-generated by KCD2 ModMaster
import bpy
import json
import time

try:
    bpy.ops.preferences.addon_enable(module='{ADDON_NAME}')
except Exception as e:
    print('Addon enable notice:', e)

meta = json.loads("{meta_json_escaped}")

def do_import():
    try:
        from {ADDON_NAME} import operators
        operators.import_asset_into_scene(meta)
        print('KCD2 ModMaster Bridge: Asset auto-imported successfully.')
    except Exception as err:
        print('Auto-import error:', err)
    return None

bpy.app.timers.register(do_import, first_interval=0.5)
"""
        startup_script.write_text(script_code, encoding="utf-8")

        # Launch Blender with .blend file or new file and python startup script
        args = [blender_exe]
        if blend_file.is_file():
            args.append(str(blend_file))
        args.extend(["--python", str(startup_script)])

        log.info("Launching Blender with: %s", args)
        subprocess.Popen(args)

    # Explicit Modular Pipeline Operations
    def sync_textures_for_asset(
        self,
        row: AssetRow,
        index: AssetIndex,
        progress_cb: Callable[[str], None] | None = None,
    ) -> bool:
        """Explicit Operation B: Resolves MTL, extracts/converts textures to workspace textures/, and signals Blender."""
        slug = self.get_asset_slug(row)
        ws_root = self.settings.workspace / "Assets" / slug
        textures_dir = ws_root / "textures"
        textures_dir.mkdir(parents=True, exist_ok=True)
        meta_file = ws_root / "metadata" / ".modmaster_asset.json"

        if progress_cb:
            progress_cb(f"Resolving textures for {row.filename}...")

        with index.connection(read_only=True) as conn:
            mtl_row = resolve_mtl_row(index, row, conn=conn)
            if not mtl_row:
                if progress_cb:
                    progress_cb("No MTL material found for asset.")
                return False

            with PakArchive(mtl_row.archive_path) as mpak:
                mtl_data = mpak.read(mtl_row.vpath)

            mtl_def = parse_mtl_xml(mtl_data, mtl_vpath=mtl_row.vpath)
            tot, res, missing = resolve_and_stage_textures(
                mtl_def, index, textures_dir, conn=conn
            )

        materials_meta = [asdict(sub) for sub in mtl_def.submaterials]

        # Update metadata file
        meta = {}
        if meta_file.is_file():
            try:
                meta = json.loads(meta_file.read_text(encoding="utf-8"))
            except Exception:
                pass
        meta["materials"] = materials_meta
        meta["material_schema_version"] = 2
        meta["textures_dir"] = str(textures_dir)
        meta_file.write_text(json.dumps(meta, indent=2), encoding="utf-8")
        self._active_asset_metadata = meta

        # Signal Blender over IPC if connected
        if self.is_blender_connected():
            if progress_cb:
                progress_cb("Sending sync_textures command to connected Blender...")
            self.send_command({
                "command": "sync_textures",
                "metadata": meta,
            })
            self.signals.log_message.emit(f"Textures synced to Blender: {res}/{tot} resolved.")
            return True
        else:
            if progress_cb:
                progress_cb(f"Textures staged to workspace ({res}/{tot} resolved). Blender not connected.")
            return True

    def rebuild_materials_in_blender(
        self,
        progress_cb: Callable[[str], None] | None = None,
    ) -> bool:
        """Explicit Operation D: Sends rebuild_materials command to clean and rebuild shader graphs."""
        if not self.is_blender_connected():
            if progress_cb:
                progress_cb("Blender is not connected. Open Blender first.")
            return False

        if progress_cb:
            progress_cb("Sending rebuild_materials command to Blender...")
        sent = self.send_command({
            "command": "rebuild_materials",
            "metadata": self._active_asset_metadata or {},
        })
        if sent:
            self.signals.log_message.emit("Rebuild materials command sent to Blender.")
        return sent
