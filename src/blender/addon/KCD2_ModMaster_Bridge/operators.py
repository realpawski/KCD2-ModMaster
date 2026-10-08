"""Blender operators for KCD2 ModMaster Bridge.

Handles:
- Pure geometry import (never fails if textures are missing)
- Explicit Texture Syncing
- Explicit Material Node Graph Building (using structured metadata)
- Non-destructive Material Rebuilding
- Model Export to ModMaster workspace
"""
from __future__ import annotations

import json
import logging
import time
from pathlib import Path
from typing import Any

import bpy

from .bridge import is_connected, ping_modmaster, send_message_to_modmaster
from .materials import reconstruct_all_materials_for_objects, validate_mesh_uvs
from .metadata import (
    get_active_asset_metadata,
    load_asset_metadata,
    save_asset_metadata,
    tag_blender_entities,
)
from .textures import reload_workspace_textures
from .workspace import open_folder_in_explorer

log = logging.getLogger("KCD2_ModMaster_Bridge.operators")


def frame_viewport_model() -> None:
    """Frames all 3D viewports onto the imported/active model."""
    try:
        for window in bpy.context.window_manager.windows:
            screen = window.screen
            for area in screen.areas:
                if area.type == 'VIEW_3D':
                    for region in area.regions:
                        if region.type == 'WINDOW':
                            override = {
                                'window': window,
                                'screen': screen,
                                'area': area,
                                'region': region,
                                'scene': bpy.context.scene,
                            }
                            with bpy.context.temp_override(**override):
                                bpy.ops.view3d.view_all(center=False)
                    break
    except Exception as e:
        log.debug("Viewport frame failed: %s", e)


def is_proxy_object(obj: Any) -> bool:
    """Detects CryEngine/KCD2 shadow proxies, physics collision hulls, and nodraw geometry."""
    name_l = obj.name.lower()
    if any(kw in name_l for kw in ("shadowproxy", "$physics", "proxy_")):
        return True
    if obj.type == "MESH" and obj.material_slots:
        slot_names = [s.name.lower() for s in obj.material_slots if s.material]
        if slot_names and all("proxy" in sn or "nodraw" in sn for sn in slot_names):
            return True
    return False


def segregate_proxies(coll: Any, new_objs: list[Any]) -> list[Any]:
    """Segregates proxies into KCD2_Proxies collection and returns visual meshes."""
    proxy_coll_name = "KCD2_Proxies"
    proxy_coll = bpy.data.collections.get(proxy_coll_name)
    if not proxy_coll:
        proxy_coll = bpy.data.collections.new(proxy_coll_name)
        coll.children.link(proxy_coll)

    visual_objs = []
    for obj in new_objs:
        if is_proxy_object(obj):
            if obj.name in coll.objects:
                coll.objects.unlink(obj)
            if obj.name not in proxy_coll.objects:
                proxy_coll.objects.link(obj)
            obj.hide_viewport = True
            obj.hide_render = True
            obj.display_type = 'WIRE'
        else:
            visual_objs.append(obj)

    return visual_objs


def _alive(obj: Any) -> bool:
    try:
        return obj.name in bpy.data.objects
    except ReferenceError:
        return False


def _copy_bones(src: Any, dst: Any, names: list[str]) -> None:
    """Adds bones that only one part of a character uses, e.g. a head with its own eye bones."""
    to_dst = dst.matrix_world.inverted() @ src.matrix_world
    bones = [src.data.bones[n] for n in names]
    previous = bpy.context.view_layer.objects.active
    bpy.context.view_layer.objects.active = dst
    bpy.ops.object.mode_set(mode='EDIT')
    try:
        edit = dst.data.edit_bones
        for bone in bones:
            new = edit.new(bone.name)
            new.length = bone.length
            new.matrix = to_dst @ bone.matrix_local
            new.use_deform = bone.use_deform
        for bone in bones:
            if bone.parent is not None and bone.parent.name in edit:
                edit[bone.name].parent = edit[bone.parent.name]
    finally:
        bpy.ops.object.mode_set(mode='OBJECT')
        bpy.context.view_layer.objects.active = previous


def merge_armatures(objs: list[Any]) -> Any | None:
    """Character parts arrive with one copy of the same skeleton each; keep one and rebind the rest."""
    arms = [o for o in objs if o.type == 'ARMATURE']
    if not arms:
        return None
    main = max(arms, key=lambda a: len(a.data.bones))
    for arm in arms:
        if arm == main:
            continue
        main_bones = {b.name for b in main.data.bones}
        missing = [b.name for b in arm.data.bones if b.name not in main_bones]
        if missing:
            _copy_bones(arm, main, missing)
        for obj in [o for o in objs if _alive(o) and o != arm]:
            if obj.parent == arm:
                world = obj.matrix_world.copy()
                obj.parent = main
                obj.matrix_world = world
            for mod in getattr(obj, "modifiers", []):
                if mod.type == 'ARMATURE' and mod.object == arm:
                    mod.object = main
        bpy.data.objects.remove(arm, do_unlink=True)
    return main


def strip_rig(objs: list[Any]) -> None:
    """Keeps the meshes in their bind pose and drops skeleton, bone shapes and armature modifiers."""
    for obj in objs:
        if obj.type != 'MESH':
            continue
        for mod in list(obj.modifiers):
            if mod.type == 'ARMATURE':
                obj.modifiers.remove(mod)
        if obj.parent is not None and obj.parent.type == 'ARMATURE':
            world = obj.matrix_world.copy()
            obj.parent = None
            obj.matrix_world = world
    for obj in objs:
        if obj.type == 'ARMATURE':
            bpy.data.objects.remove(obj, do_unlink=True)


def _import_glb(path: Path, coll: Any) -> list[Any]:
    existing = set(bpy.data.objects)
    bpy.ops.import_scene.gltf(
        filepath=str(path),
        import_pack_images=False,
        merge_vertices=False,
        guess_original_bind_pose=True,
    )
    new_objs = [obj for obj in bpy.data.objects if obj not in existing]
    for obj in new_objs:
        if obj.name not in coll.objects:
            for c in obj.users_collection:
                c.objects.unlink(obj)
            coll.objects.link(obj)
    return new_objs


def import_asset_into_scene(metadata: dict[str, Any]) -> bool:
    """Executes geometry import and staging into Blender scene."""
    asset_name = metadata.get("asset_name", "asset")
    blend_path = metadata.get("blend_file", "")
    parts = metadata.get("parts") or [{
        "interchange_file": metadata.get("interchange_file", ""),
        "materials": metadata.get("materials", []),
        "mtl_path": metadata.get("mtl_path", ""),
    }]
    missing = [p["interchange_file"] for p in parts if not Path(p["interchange_file"]).is_file()]
    if missing:
        log.error("Interchange file not found: %s", missing[0])
        return False

    scene = bpy.context.scene
    coll_name = f"KCD2_{asset_name}"
    coll = bpy.data.collections.get(coll_name)
    if not coll:
        coll = bpy.data.collections.new(coll_name)
        scene.collection.children.link(coll)
    view_layer = bpy.context.view_layer
    view_layer.active_layer_collection = (
        view_layer.layer_collection.children.get(coll_name) or view_layer.layer_collection
    )

    all_new: list[Any] = []
    visual_objs: list[Any] = []
    for part in parts:
        try:
            new_objs = _import_glb(Path(part["interchange_file"]), coll)
        except Exception as err:
            log.error("GLTF import failed: %s", err)
            return False
        all_new += new_objs
        part_visual = [o for o in segregate_proxies(coll, new_objs) if o.type == 'MESH']
        for obj in part_visual:
            validate_mesh_uvs(obj)
        try:
            reconstruct_all_materials_for_objects(part_visual, {**metadata, **part}, allow_imported=True)
        except Exception as mat_err:
            log.warning("Material reconstruction notice: %s", mat_err)
        visual_objs += part_visual

    # The glTF importer adds an icosphere as bone display shape; it must never be exported.
    shapes = [o for o in all_new if o.type == 'MESH' and o.name.startswith("Icosphere")
              and o.parent is None and not o.vertex_groups and not o.material_slots]
    for obj in shapes:
        obj.hide_viewport = True
        obj.hide_render = True
        visual_objs = [v for v in visual_objs if v != obj]

    if metadata.get("strip_rig"):
        strip_rig(all_new)
        for obj in shapes:
            bpy.data.objects.remove(obj, do_unlink=True)
        all_new = [o for o in all_new if _alive(o)]
    else:
        merge_armatures(all_new)
        all_new = [o for o in all_new if _alive(o)]

    tag_blender_entities(scene, coll, all_new, metadata)

    bpy.ops.object.select_all(action='DESELECT')
    visual_objs = [o for o in visual_objs if _alive(o)]
    for obj in visual_objs:
        obj.select_set(True)
    if visual_objs:
        bpy.context.view_layer.objects.active = visual_objs[0]

    frame_viewport_model()

    if blend_path:
        p_blend = Path(blend_path)
        p_blend.parent.mkdir(parents=True, exist_ok=True)
        try:
            bpy.ops.wm.save_as_mainfile(filepath=str(p_blend))
            log.info("Saved blend file to %s", p_blend)
        except Exception as err:
            log.warning("Could not auto-save blend file: %s", err)

    return True


class KCD2_OT_import_from_modmaster(bpy.types.Operator):
    """Imports the active model geometry prepared by KCD2 ModMaster."""
    bl_idname = "kcd2.import_from_modmaster"
    bl_label = "Import Model"
    bl_description = "Import model geometry from ModMaster workspace"

    def execute(self, context):
        meta = get_active_asset_metadata(context.scene)
        if not meta:
            resp = send_message_to_modmaster({"command": "get_active_asset"})
            if resp and resp.get("metadata"):
                meta = resp["metadata"]

        if not meta:
            self.report({'WARNING'}, "No active ModMaster asset found. Select an asset in ModMaster first.")
            return {'CANCELLED'}

        ok = import_asset_into_scene(meta)
        if ok:
            self.report({'INFO'}, f"Successfully imported {meta.get('asset_name')}")
            return {'FINISHED'}
        else:
            self.report({'ERROR'}, "Failed to import asset interchange file.")
            return {'CANCELLED'}


class KCD2_OT_sync_textures(bpy.types.Operator):
    """Syncs and reloads textures from the active ModMaster workspace."""
    bl_idname = "kcd2.sync_textures"
    bl_label = "Sync Textures"
    bl_description = "Reload textures from workspace and refresh image nodes"

    def execute(self, context):
        meta = get_active_asset_metadata(context.scene)
        if not meta:
            self.report({'WARNING'}, "No active ModMaster asset linked.")
            return {'CANCELLED'}

        textures_dir = Path(meta.get("textures_dir", ""))
        n_reloaded = reload_workspace_textures(textures_dir)

        # Update materials with newly loaded textures
        asset_name = meta.get("asset_name", "")
        coll = bpy.data.collections.get(f"KCD2_{asset_name}")
        objs = [o for o in coll.all_objects if o.type == 'MESH'] if coll else [o for o in context.scene.objects if o.type == 'MESH']
        reconstruct_all_materials_for_objects(objs, meta)

        self.report({'INFO'}, f"Synced textures ({n_reloaded} reloaded). Materials updated.")
        return {'FINISHED'}


class KCD2_OT_build_materials(bpy.types.Operator):
    """Builds clean Principled BSDF material node setups using ModMaster metadata."""
    bl_idname = "kcd2.build_materials"
    bl_label = "Build Materials"
    bl_description = "Construct Principled BSDF node trees from KCD2 material metadata"

    def execute(self, context):
        meta = get_active_asset_metadata(context.scene)
        if not meta:
            self.report({'WARNING'}, "No active ModMaster asset metadata found.")
            return {'CANCELLED'}

        asset_name = meta.get("asset_name", "")
        coll = bpy.data.collections.get(f"KCD2_{asset_name}")
        objs = [o for o in coll.all_objects if o.type == 'MESH'] if coll else [o for o in context.scene.objects if o.type == 'MESH']

        count = reconstruct_all_materials_for_objects(objs, meta)
        self.report({'INFO'}, f"Built {count} material node graphs from KCD2 metadata.")
        return {'FINISHED'}


class KCD2_OT_rebuild_materials(bpy.types.Operator):
    """Non-destructively rebuilds material node trees without altering mesh geometry, transforms, or UVs."""
    bl_idname = "kcd2.rebuild_materials"
    bl_label = "Rebuild Materials"
    bl_description = "Rebuild material node trees cleanly while strictly preserving geometry, transforms, and UVs"

    def execute(self, context):
        meta = get_active_asset_metadata(context.scene)
        if not meta:
            self.report({'WARNING'}, "No active ModMaster asset metadata found.")
            return {'CANCELLED'}

        asset_name = meta.get("asset_name", "")
        coll = bpy.data.collections.get(f"KCD2_{asset_name}")
        objs = [o for o in coll.all_objects if o.type == 'MESH'] if coll else [o for o in context.scene.objects if o.type == 'MESH']

        count = reconstruct_all_materials_for_objects(objs, meta)
        self.report({'INFO'}, f"Cleanly rebuilt {count} materials without touching geometry.")
        return {'FINISHED'}


class KCD2_OT_export_to_workspace(bpy.types.Operator):
    """Exports the model to the current ModMaster workspace."""
    bl_idname = "kcd2.export_to_workspace"
    bl_label = "Export to Current Workspace"
    bl_description = "Export modified asset directly into the active ModMaster workspace"

    def execute(self, context):
        meta = get_active_asset_metadata(context.scene)
        if not meta:
            self.report({'ERROR'}, "No active ModMaster asset linked to this scene.")
            return {'CANCELLED'}

        asset_name = meta.get("asset_name", "asset")
        coll_name = f"KCD2_{asset_name}"
        coll = bpy.data.collections.get(coll_name)

        export_objs = coll.all_objects if coll else [o for o in context.scene.objects if o.type == 'MESH']
        if not export_objs:
            self.report({'ERROR'}, f"No objects found in collection '{coll_name}' to export.")
            return {'CANCELLED'}

        export_file = meta.get("export_file")
        if not export_file:
            ws = meta.get("workspace_dir", "")
            export_file = str(Path(ws) / "export" / f"{asset_name}_exported.glb")

        p_export = Path(export_file)
        p_export.parent.mkdir(parents=True, exist_ok=True)

        bpy.ops.object.select_all(action='DESELECT')
        for obj in export_objs:
            obj.select_set(True)

        try:
            bpy.ops.export_scene.gltf(
                filepath=str(p_export),
                export_format='GLB',
                use_selection=True,
                export_apply=False,
                export_materials='EXPORT',
                export_image_format='AUTO',
            )
        except Exception as err:
            self.report({'ERROR'}, f"GLB Export failed: {err}")
            return {'CANCELLED'}

        dae_file = meta.get("dae_export_file") or str(p_export.with_suffix(".dae"))
        if hasattr(bpy.ops.wm, "collada_export"):
            try:
                bpy.ops.wm.collada_export(
                    filepath=str(dae_file),
                    selected=True,
                    apply_modifiers=False,
                )
            except Exception as e:
                log.debug("Collada export optional notice: %s", e)

        meta["status"] = "modified"
        meta["last_exported"] = time.time()
        meta["export_file"] = str(p_export)
        meta["dae_export_file"] = str(dae_file)
        tag_blender_entities(context.scene, coll, list(export_objs), meta)

        meta_path = Path(meta.get("workspace_dir", "")) / "metadata" / ".modmaster_asset.json"
        save_asset_metadata(meta_path, meta)

        send_message_to_modmaster({
            "command": "asset_exported",
            "asset_id": meta.get("asset_id"),
            "asset_name": asset_name,
            "export_file": str(p_export),
            "dae_file": str(dae_file),
            "timestamp": time.time(),
            "metadata": meta,
        })

        self.report({'INFO'}, f"Exported successfully to {p_export.name}")
        return {'FINISHED'}


class KCD2_OT_export_as_new_asset(bpy.types.Operator):
    """Exports model as a new version or new asset name."""
    bl_idname = "kcd2.export_as_new_asset"
    bl_label = "Export as New Asset"
    bl_description = "Export with custom version suffix"

    suffix: bpy.props.StringProperty(name="Suffix", default="_variant")

    def invoke(self, context, event):
        return context.window_manager.invoke_props_dialog(self)

    def execute(self, context):
        meta = get_active_asset_metadata(context.scene)
        if not meta:
            self.report({'ERROR'}, "No active ModMaster asset linked.")
            return {'CANCELLED'}

        asset_name = f"{meta.get('asset_name', 'asset')}{self.suffix}"
        ws = meta.get("workspace_dir", "")
        p_export = Path(ws) / "export" / f"{asset_name}_exported.glb"
        p_export.parent.mkdir(parents=True, exist_ok=True)

        try:
            bpy.ops.export_scene.gltf(
                filepath=str(p_export),
                export_format='GLB',
                use_selection=True,
            )
            self.report({'INFO'}, f"Exported new asset variant: {p_export.name}")
            return {'FINISHED'}
        except Exception as e:
            self.report({'ERROR'}, f"Export failed: {e}")
            return {'CANCELLED'}


class KCD2_OT_open_workspace_folder(bpy.types.Operator):
    """Opens active asset workspace directory in Explorer."""
    bl_idname = "kcd2.open_workspace_folder"
    bl_label = "Open Workspace Folder"
    bl_description = "Open active asset folder in Windows Explorer"

    def execute(self, context):
        meta = get_active_asset_metadata(context.scene)
        ws = meta.get("workspace_dir") if meta else None
        if not ws:
            self.report({'WARNING'}, "No workspace directory linked.")
            return {'CANCELLED'}
        open_folder_in_explorer(ws)
        return {'FINISHED'}


class KCD2_OT_sync_modmaster(bpy.types.Operator):
    """Synchronizes status with ModMaster."""
    bl_idname = "kcd2.sync_modmaster"
    bl_label = "Sync from ModMaster"
    bl_description = "Query connection and synchronization status from ModMaster"

    def execute(self, context):
        ok = ping_modmaster()
        if ok:
            self.report({'INFO'}, "Connected to KCD2 ModMaster ✓")
        else:
            self.report({'WARNING'}, "Could not connect to ModMaster (127.0.0.1:24952)")
        return {'FINISHED'}


class KCD2_OT_send_to_modmaster(bpy.types.Operator):
    """Sends compile and packaging trigger to ModMaster."""
    bl_idname = "kcd2.send_to_modmaster"
    bl_label = "Send to ModMaster"
    bl_description = "Signal ModMaster to validate and prepare asset for compilation"

    def execute(self, context):
        meta = get_active_asset_metadata(context.scene)
        if not meta:
            self.report({'WARNING'}, "No active asset linked.")
            return {'CANCELLED'}
        resp = send_message_to_modmaster({
            "command": "request_build",
            "asset_id": meta.get("asset_id"),
            "metadata": meta,
        })
        if resp and resp.get("status") == "ok":
            self.report({'INFO'}, "ModMaster notified for build.")
        else:
            self.report({'INFO'}, "Signal sent to ModMaster.")
        return {'FINISHED'}


CLASSES = [
    KCD2_OT_import_from_modmaster,
    KCD2_OT_sync_textures,
    KCD2_OT_build_materials,
    KCD2_OT_rebuild_materials,
    KCD2_OT_export_to_workspace,
    KCD2_OT_export_as_new_asset,
    KCD2_OT_open_workspace_folder,
    KCD2_OT_sync_modmaster,
    KCD2_OT_send_to_modmaster,
]


def register() -> None:
    for cls in CLASSES:
        bpy.utils.register_class(cls)


def unregister() -> None:
    for cls in reversed(CLASSES):
        bpy.utils.unregister_class(cls)
