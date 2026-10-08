"""N-Panel UI for KCD2 ModMaster Blender Bridge in 3D Viewport."""
from __future__ import annotations

import bpy

from .bridge import is_connected
from .metadata import get_active_asset_metadata

_ICONS = set(bpy.types.UILayout.bl_rna.functions["operator"].parameters["icon"].enum_items.keys())


def icon(name: str) -> str:
    # Blender renames and removes icons between versions; an unknown one would abort the whole panel.
    return name if name in _ICONS else "NONE"


class KCD2_PT_modmaster_panel(bpy.types.Panel):
    """KCD2 ModMaster Sidebar Panel in 3D Viewport."""
    bl_label = "KCD2 ModMaster"
    bl_idname = "KCD2_PT_modmaster_panel"
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'UI'
    bl_category = "KCD2 ModMaster"

    def draw(self, context):
        layout = self.layout
        scene = context.scene

        meta = get_active_asset_metadata(scene)
        connected = is_connected()

        # Connection status badge
        box_status = layout.box()
        row_conn = box_status.row(align=True)
        if connected:
            row_conn.label(text="CONNECTED TO MODMASTER ✓", icon=icon('CHECKMARK'))
        else:
            row_conn.label(text="MODMASTER OFFLINE", icon=icon('CANCEL'))
            row_conn.operator("kcd2.sync_modmaster", text="Retry", icon=icon('FILE_REFRESH'))

        # Active Asset / Project info
        box_info = layout.box()
        box_info.label(text="Bridge Context", icon=icon('PRESET'))

        proj = scene.get("modmaster_project") or (meta.get("project") if meta else "Default Project")
        col = box_info.column(align=True)
        col.label(text=f"Current Project: {proj}")

        if meta:
            col.label(text=f"Current Asset: {meta.get('asset_name', 'None')}")
            col.label(text=f"Source: {meta.get('virtual_path', 'N/A')}")
            status_txt = meta.get("status", "unmodified").upper()
            col.label(text=f"Status: {status_txt}")

            ws = meta.get("workspace_dir", "")
            if ws:
                col.separator()
                col.label(text="Workspace:")
                # Display truncated workspace path
                ws_disp = ws if len(ws) < 36 else f"...{ws[-33:]}"
                col.label(text=ws_disp)
        else:
            col.label(text="No active ModMaster asset linked")

        layout.separator()

        # Main Actions
        col_actions = layout.column(align=True)
        col_actions.scale_y = 1.25

        col_actions.operator("kcd2.import_from_modmaster", text="IMPORT MODEL", icon=icon('IMPORT'))

        layout.separator()
        box_mat = layout.box()
        box_mat.label(text="Materials & Textures", icon=icon('MATERIAL'))
        col_mat = box_mat.column(align=True)
        col_mat.operator("kcd2.sync_textures", text="SYNC TEXTURES", icon=icon('IMAGE_DATA'))
        col_mat.operator("kcd2.build_materials", text="BUILD MATERIALS", icon=icon('SHADING_RENDERED'))
        col_mat.operator("kcd2.rebuild_materials", text="REBUILD MATERIALS", icon=icon('FILE_REFRESH'))

        layout.separator()
        col_exp = layout.column(align=True)
        col_exp.scale_y = 1.2
        col_exp.operator("kcd2.export_cgf", text="EXPORT TO KCD2 (.CGF)", icon=icon('EXPORT'))
        col_exp.operator("kcd2.export_to_workspace", text="EXPORT GLB PREVIEW", icon=icon('FILE_3D'))
        col_exp.operator("kcd2.export_as_new_asset", text="EXPORT AS NEW ASSET", icon=icon('DUPLICATE'))
        col_exp.operator("kcd2.open_workspace_folder", text="OPEN WORKSPACE FOLDER", icon=icon('FILE_FOLDER'))

        layout.separator()
        col_sync = layout.column(align=True)
        col_sync.operator("kcd2.sync_modmaster", text="CHECK CONNECTION", icon=icon('LINKED'))
        col_sync.operator("kcd2.send_to_modmaster", text="REQUEST BUILD", icon=icon('TOOL_SETTINGS'))


def register() -> None:
    bpy.utils.register_class(KCD2_PT_modmaster_panel)


def unregister() -> None:
    bpy.utils.unregister_class(KCD2_PT_modmaster_panel)
