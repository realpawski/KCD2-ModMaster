"""Unit and integration tests for KCD2 ModMaster Blender Bridge and round-trip workflow."""
from __future__ import annotations

import json
import os
import subprocess
import time
from pathlib import Path

import pytest

from blender.bridge_manager import (
    CURRENT_BRIDGE_VERSION,
    BlenderBridgeManager,
    BridgeStatus,
)
from core.config import Settings
from database.index import AssetIndex


@pytest.fixture
def test_settings(tmp_path):
    s = Settings()
    s.workspace_dir = str(tmp_path / "Workspace")
    s.blender_exe = r"C:\Program Files\Blender Foundation\Blender 5.1\blender.exe"
    s.ensure_workspace()
    return s


def test_bridge_addon_files_exist():
    """Verifies that the authoritative source files for the bridge addon exist."""
    addon_dir = Path(__file__).resolve().parent.parent / "src" / "blender" / "addon" / "KCD2_ModMaster_Bridge"
    assert addon_dir.is_dir()
    for fname in ("__init__.py", "operators.py", "panel.py", "bridge.py", "workspace.py", "metadata.py"):
        assert (addon_dir / fname).is_file(), f"Missing addon file: {fname}"


def test_bridge_addon_install_and_detect(test_settings):
    """Tests addon installation and detection across user AppData."""
    mgr = BlenderBridgeManager(test_settings)
    try:
        ok, msg = mgr.install_or_update_addon()
        assert ok is True

        det = mgr.detect_addon_status()
        assert det.status == BridgeStatus.INSTALLED
        assert det.version == CURRENT_BRIDGE_VERSION
        assert det.addon_dir is not None
        assert (det.addon_dir / "__init__.py").is_file()
    finally:
        mgr.stop_ipc_server()


def test_ipc_ping_and_handshake(test_settings):
    """Tests localhost IPC communication on 127.0.0.1:24952."""
    import socket

    probe = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        probe.bind(("127.0.0.1", 24952))
    except OSError:
        pytest.skip("Port 24952 is taken by a running ModMaster")
    finally:
        probe.close()

    mgr = BlenderBridgeManager(test_settings)
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        s.settimeout(2.0)
        s.connect(("127.0.0.1", 24952))

        handshake = {"command": "handshake", "bridge_version": CURRENT_BRIDGE_VERSION}
        s.sendall((json.dumps(handshake) + "\n").encode("utf-8"))

        data = s.recv(4096).decode("utf-8")
        resp = json.loads(data.strip().split("\n")[0])
        assert resp.get("status") == "ok"
        assert resp.get("bridge_version") == CURRENT_BRIDGE_VERSION

        time.sleep(0.1)
        assert mgr.is_blender_connected() is True

        ping = {"command": "ping"}
        s.sendall((json.dumps(ping) + "\n").encode("utf-8"))
        data2 = s.recv(4096).decode("utf-8")
        resp2 = json.loads(data2.strip().split("\n")[0])
        assert resp2.get("status") == "pong"

        s.close()
    finally:
        mgr.stop_ipc_server()


def test_real_cat_asset_blender_roundtrip():
    """End-to-end integration test with real cat.cgf asset through Blender 5.1."""
    s = Settings.load()
    if not Path(s.database_path).is_file():
        pytest.skip("Asset index not found on system.")

    blender_exe = Path(r"C:\Program Files\Blender Foundation\Blender 5.1\blender.exe")
    if not blender_exe.is_file():
        pytest.skip("Blender 5.1 executable not found.")
    from preview.converter import find_converter_exe
    if find_converter_exe(s) is None:
        pytest.skip("KCD2-Convertor.exe not found in this (isolated) environment.")

    idx = AssetIndex(s.database_path)
    rows = idx.find_by_vpath("Objects/characters/animals/cat/cat.cgf")
    if not rows:
        pytest.skip("cat.cgf not found in index.")
    cat_row = rows[0]

    mgr = BlenderBridgeManager(s)
    try:
        meta = mgr.prepare_editable_workspace(cat_row, idx)
        assert meta["asset_name"] == "cat"
        assert meta["status"] in ("unmodified", "modified")
        assert Path(meta["interchange_file"]).is_file()
        assert Path(meta["interchange_file"]).stat().st_size > 1000

        script = f"""import json, bpy
from pathlib import Path
meta_path = Path(r"{meta['workspace_dir']}") / "metadata" / ".modmaster_asset.json"
meta = json.loads(meta_path.read_text())
bpy.ops.preferences.addon_enable(module='KCD2_ModMaster_Bridge')
from KCD2_ModMaster_Bridge import operators
ok = operators.import_asset_into_scene(meta)
assert ok is True, 'Import failed'
assert 'KCD2_cat' in bpy.data.collections, 'Collection missing'
res = bpy.ops.kcd2.export_to_workspace()
assert 'FINISHED' in res, 'Export operator failed'
print('TEST_ROUNDTRIP_SUCCESS')
"""
        cmd = [str(blender_exe), "-b", "--python-expr", script]
        proc = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=60)
        assert proc.stdout and "TEST_ROUNDTRIP_SUCCESS" in proc.stdout, f"Blender script failed:\n{proc.stdout}\n{proc.stderr}"

        export_file = Path(meta["export_file"])
        assert export_file.is_file()
        assert export_file.stat().st_size > 10000

        updated_meta = json.loads((Path(meta["workspace_dir"]) / "metadata" / ".modmaster_asset.json").read_text())
        assert updated_meta["status"] == "modified"
        assert updated_meta["last_exported"] is not None

    finally:
        mgr.stop_ipc_server()


def test_converter_is_found_in_nested_addon_and_extension_folders(tmp_path, monkeypatch):
    from preview.converter import find_converter_exe

    import app.paths

    monkeypatch.setattr(app.paths, "resource_dir", lambda relative: tmp_path / "install" / relative)
    monkeypatch.setenv("APPDATA", str(tmp_path))
    blender = tmp_path / "Blender Foundation" / "Blender"
    assert find_converter_exe() is None
    tool = "io_KCD2_Blender_Toolkit/External/KCD2-Convertor/KCD2-Convertor.exe"
    for place in ("5.1/extensions/user_default/" + tool,
                  "5.2/scripts/addons/KCD2-Blender-Toolkit-0.3.2/" + tool):
        (blender / place).parent.mkdir(parents=True)
        (blender / place).write_bytes(b"MZ")
    assert find_converter_exe() == blender / "5.2/scripts/addons/KCD2-Blender-Toolkit-0.3.2" / tool


def test_the_converter_shipped_with_modmaster_comes_first(tmp_path, monkeypatch):
    import app.paths
    from preview.converter import BUNDLED_CONVERTER, find_converter_exe

    shipped = tmp_path / "install" / BUNDLED_CONVERTER
    shipped.parent.mkdir(parents=True)
    shipped.write_bytes(b"MZ")
    monkeypatch.setattr(app.paths, "resource_dir", lambda relative: tmp_path / "install" / relative)
    monkeypatch.setenv("APPDATA", str(tmp_path))
    assert find_converter_exe() == shipped
