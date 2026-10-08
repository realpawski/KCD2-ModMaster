"""KCD2 ModMaster Bridge Addon for Blender 5.x / 4.x.

Provides one-click interoperability between KCD2 ModMaster and Blender.
"""
from __future__ import annotations

import logging
from typing import Any

import bpy

bl_info = {
    "name": "KCD2 ModMaster Bridge",
    "author": "PAWSKI",
    "version": (1, 1, 0),
    "blender": (4, 2, 0),
    "location": "View3D > Sidebar > KCD2 ModMaster",
    "description": "Seamless one-click bridge between KCD2 ModMaster and Blender.",
    "category": "Import-Export",
}

from . import bridge, cgf_export, metadata, operators, panel, workspace

log = logging.getLogger("KCD2_ModMaster_Bridge")

_timer_registered = False


def _bridge_timer_callback() -> float:
    """Timer callback on Blender main thread to process incoming ModMaster commands."""
    try:
        cmd = bridge.get_next_command()
        while cmd:
            action = cmd.get("command")
            if action == "import_asset":
                meta = cmd.get("metadata", {})
                log.info("Received import_asset command for %s", meta.get("asset_name"))
                operators.import_asset_into_scene(meta)
            elif action == "sync_textures":
                meta = cmd.get("metadata", {})
                log.info("Received sync_textures command for %s", meta.get("asset_name"))
                bpy.ops.kcd2.sync_textures()
            elif action == "build_materials":
                log.info("Received build_materials command")
                bpy.ops.kcd2.build_materials()
            elif action == "rebuild_materials":
                log.info("Received rebuild_materials command")
                bpy.ops.kcd2.rebuild_materials()
            elif action == "ping":
                bridge.send_message_to_modmaster({"status": "pong", "bridge_version": bridge.BRIDGE_VERSION})
            elif action == "open_workspace":
                ws = cmd.get("workspace_dir")
                if ws:
                    workspace.open_folder_in_explorer(ws)

            cmd = bridge.get_next_command()
    except Exception as e:
        log.debug("Timer callback exception: %s", e)

    return 0.25


def register() -> None:
    global _timer_registered
    operators.register()
    cgf_export.register()
    panel.register()

    # Start IPC listener client
    try:
        bridge.start_bridge_listener()
    except Exception as err:
        log.warning("Could not start bridge listener: %s", err)

    # Register main thread timer
    if not _timer_registered:
        bpy.app.timers.register(_bridge_timer_callback, persistent=True)
        _timer_registered = True

    log.info("KCD2 ModMaster Bridge addon registered.")


def unregister() -> None:
    global _timer_registered
    if _timer_registered:
        try:
            bpy.app.timers.unregister(_bridge_timer_callback)
        except Exception:
            pass
        _timer_registered = False

    try:
        bridge.stop_bridge_listener()
    except Exception:
        pass

    panel.unregister()
    cgf_export.unregister()
    operators.unregister()
    log.info("KCD2 ModMaster Bridge addon unregistered.")


if __name__ == "__main__":
    register()
