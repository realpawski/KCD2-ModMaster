"""Export to KCD2: Blender scene to compiled .cgf, .mtl and .dds inside a ModMaster workspace asset."""
from __future__ import annotations

import json
import tempfile
import time
from pathlib import Path

import bpy

from . import cry_compile
from .bridge import send_message_to_modmaster
from .metadata import get_active_asset_metadata
from .panel import icon

NEW_ASSET = "__new__"
_asset_items: list[tuple[str, str, str]] = []


def _prefs(context):
    addon = context.preferences.addons.get(__package__)
    return addon.preferences if addon else None


def workspace_root(context) -> Path:
    meta = get_active_asset_metadata(context.scene) or {}
    ws = meta.get("workspace_dir")
    if ws and Path(ws).parent.name.lower() == "assets":
        return Path(ws).parent.parent
    prefs = _prefs(context)
    if prefs and prefs.workspace_dir:
        return Path(bpy.path.abspath(prefs.workspace_dir))
    return Path.home() / "Documents" / "KCD2 ModMaster" / "Workspace"


def _asset_enum(self, context):
    _asset_items.clear()
    assets = workspace_root(context) / "Assets"
    if assets.is_dir():
        for folder in sorted(assets.iterdir()):
            if not folder.is_dir():
                continue
            name = folder.name
            meta = folder / "metadata" / ".modmaster_asset.json"
            if meta.is_file():
                try:
                    data = json.loads(meta.read_text(encoding="utf-8"))
                    name = data.get("asset_name") or data.get("name") or name
                except ValueError:
                    pass
            _asset_items.append((folder.name, name, str(folder)))
    _asset_items.append((NEW_ASSET, "New asset…", "Create a new workspace asset"))
    return _asset_items


def _export_meshes(context, selected_only: bool) -> list:
    objects = context.selected_objects if selected_only else context.view_layer.objects
    return [o for o in objects if o.type == "MESH" and o.visible_get() and "proxy" not in o.name.lower()]


def _image_input(socket):
    if not socket or not socket.is_linked:
        return None
    node = socket.links[0].from_node
    if node.type == "TEX_IMAGE" and node.image:
        return node.image
    if node.type == "NORMAL_MAP":
        return _image_input(node.inputs.get("Color"))
    return None


def _save_tif(image, path: Path) -> Path:
    copy = image.copy()
    try:
        w, h = copy.size
        pot = lambda v: 1 << max(v - 1, 1).bit_length()
        if (w, h) != (pot(w), pot(h)) and w and h:
            copy.scale(pot(w), pot(h))
        copy.filepath_raw = str(path)
        copy.file_format = "TIFF"
        copy.save()
    finally:
        bpy.data.images.remove(copy)
    return path


def _game_textures(source: dict, mtl_path: str) -> dict:
    folder = str(Path(mtl_path).parent.as_posix()) if mtl_path else ""
    result = {}
    for slot, path in (source.get("textures") or {}).items():
        p = str(path).replace("\\", "/")
        relative = p.startswith("./") or "/" not in p
        p = p[2:] if p.startswith("./") else p
        result[slot] = f"{folder}/{p}" if relative and folder else p
    return result


def _material_entry(mat, name: str, rc: Path, work: Path, tex_root: Path, tex_virtual: str, mtl_path: str) -> dict:
    if mat is not None and mat.get("kcd2_source_material"):
        source = json.loads(mat["kcd2_source_material"])
        return {"name": name, "shader": source.get("shader") or "Illum",
                "attributes": source.get("source_attributes") or {},
                "public_params": source.get("public_params") or {},
                "textures": _game_textures(source, mtl_path)}

    entry = {"name": name, "textures": {}}
    principled = None
    if mat is not None and mat.use_nodes:
        principled = next((n for n in mat.node_tree.nodes if n.type == "BSDF_PRINCIPLED"), None)
    if principled is None:
        if mat is not None:
            entry["diffuse"] = tuple(mat.diffuse_color)[:3]
        return entry

    stem = cry_compile.slug(name)
    base = principled.inputs.get("Base Color")
    image = _image_input(base)
    if image:
        tif = _save_tif(image, work / f"{stem}_diff.tif")
        cry_compile.compile_texture(rc, tif, tex_root / f"{stem}_diff.dds", "Albedo")
        entry["textures"]["Diffuse"] = f"{tex_virtual}/{stem}_diff.dds"
    elif base is not None:
        entry["diffuse"] = tuple(base.default_value)[:3]
    normal = _image_input(principled.inputs.get("Normal"))
    if normal:
        tif = _save_tif(normal, work / f"{stem}_ddna.tif")
        cry_compile.compile_texture(rc, tif, tex_root / f"{stem}_ddna.dds", "Normals")
        entry["textures"]["Bumpmap"] = f"{tex_virtual}/{stem}_ddna.dds"
    return entry


def _ensure_asset(root: Path, asset_id: str, display: str) -> Path:
    folder = root / "Assets" / asset_id
    meta = folder / "metadata" / ".modmaster_asset.json"
    if not meta.is_file():
        for sub in ("metadata", "blender", "export", "textures"):
            (folder / sub).mkdir(parents=True, exist_ok=True)
        now = time.time()
        meta.write_text(json.dumps({
            "asset_id": asset_id, "asset_name": display, "asset_type": "Static Prop",
            "source_type": "blender_scene", "workspace_dir": str(folder), "status": "EDITING",
            "materials": [], "textures": [], "created_at": now, "updated_at": now,
        }, indent=2), encoding="utf-8")
    return folder


class KCD2_OT_export_cgf(bpy.types.Operator):
    """Compile the model into a KCD2 .cgf with material and textures"""
    bl_idname = "kcd2.export_cgf"
    bl_label = "Export to KCD2 (.cgf)"
    bl_options = {"REGISTER"}

    target: bpy.props.EnumProperty(name="Asset", items=_asset_enum)
    new_name: bpy.props.StringProperty(name="Name", default="")
    selected_only: bpy.props.BoolProperty(name="Selected objects only", default=True)

    def invoke(self, context, event):
        meta = get_active_asset_metadata(context.scene) or {}
        ids = [i[0] for i in _asset_enum(self, context)]
        if meta.get("asset_id") in ids:
            self.target = meta["asset_id"]
        else:
            self.target = NEW_ASSET
        if not self.new_name:
            self.new_name = context.active_object.name if context.active_object else "model"
        self.selected_only = bool(context.selected_objects)
        return context.window_manager.invoke_props_dialog(self, width=420)

    def draw(self, context):
        layout = self.layout
        layout.prop(self, "target")
        if self.target == NEW_ASSET:
            layout.prop(self, "new_name")
        layout.prop(self, "selected_only")
        layout.label(text="The model's origin is the world origin.", icon=icon("INFO"))

    def execute(self, context):
        prefs = _prefs(context)
        rc = cry_compile.find_rc(prefs.rc_path if prefs else None)
        if rc is None:
            self.report({"ERROR"}, "Resource Compiler not found. Install KCD2 Modding Tools from Steam "
                                   "or set rc.exe in the add-on preferences.")
            return {"CANCELLED"}

        meshes = _export_meshes(context, self.selected_only)
        if not meshes:
            self.report({"ERROR"}, "No visible mesh objects to export.")
            return {"CANCELLED"}

        root = workspace_root(context)
        if self.target == NEW_ASSET:
            display = self.new_name.strip() or "model"
            asset_id = cry_compile.slug(display)
        else:
            asset_id = self.target
            display = next((i[1] for i in _asset_items if i[0] == asset_id), asset_id)
        asset_dir = _ensure_asset(root, asset_id, display)

        for obj in meshes:
            if not obj.material_slots or not any(s.material for s in obj.material_slots):
                mat = bpy.data.materials.get("kcd2_default") or bpy.data.materials.new("kcd2_default")
                obj.data.materials.append(mat)

        model, tex_virtual = cry_compile.model_paths(asset_id)
        compiled = asset_dir / "compiled"
        meta = get_active_asset_metadata(context.scene) or {}
        mtl_path = meta.get("mtl_path") or next((o.get("kcd2_mtl_path") for o in meshes if o.get("kcd2_mtl_path")), "")

        previous_selection = list(context.selected_objects)
        previous_active = context.view_layer.objects.active
        try:
            with tempfile.TemporaryDirectory(prefix="kcd2_export_") as tmp:
                work = Path(tmp)
                fbx = work / f"{asset_id}.fbx"
                bpy.ops.object.select_all(action="DESELECT")
                for obj in meshes:
                    obj.select_set(True)
                context.view_layer.objects.active = meshes[0]
                bpy.ops.export_scene.fbx(filepath=str(fbx), use_selection=True, object_types={"MESH"},
                                         use_mesh_modifiers=True, mesh_smooth_type="FACE",
                                         apply_scale_options="FBX_SCALE_UNITS", add_leaf_bones=False,
                                         bake_anim=False, path_mode="STRIP")
                subs = cry_compile.compile_model(rc, fbx, compiled / f"{model}.cgf", model)
                entries = [_material_entry(bpy.data.materials.get(name), name, rc, work,
                                           compiled / tex_virtual, tex_virtual, mtl_path) for name in subs]
                cry_compile.write_mtl(compiled / f"{model}.mtl", entries)
        except cry_compile.CompileError as exc:
            self.report({"ERROR"}, f"Compile failed: {exc}")
            return {"CANCELLED"}
        finally:
            bpy.ops.object.select_all(action="DESELECT")
            for obj in previous_selection:
                obj.select_set(True)
            context.view_layer.objects.active = previous_active

        meta_file = asset_dir / "metadata" / ".modmaster_asset.json"
        try:
            data = json.loads(meta_file.read_text(encoding="utf-8"))
            data.update({"compiled_model": f"{model}.cgf", "compiled_at": time.time(), "updated_at": time.time()})
            meta_file.write_text(json.dumps(data, indent=2), encoding="utf-8")
        except (OSError, ValueError):
            pass
        send_message_to_modmaster({"command": "asset_compiled", "asset_id": asset_id,
                                   "model": f"{model}.cgf", "timestamp": time.time()})
        self.report({"INFO"}, f"Compiled {asset_id}.cgf with {len(subs)} material(s). "
                              "Add the asset to a mod in ModMaster and build it.")
        return {"FINISHED"}


class KCD2_AddonPreferences(bpy.types.AddonPreferences):
    bl_idname = __package__

    rc_path: bpy.props.StringProperty(
        name="Resource Compiler (rc.exe)", subtype="FILE_PATH",
        description="Found automatically when KCD2 Modding Tools are installed through Steam")
    workspace_dir: bpy.props.StringProperty(
        name="ModMaster workspace", subtype="DIR_PATH",
        description="Used when the scene was not opened from ModMaster")

    def draw(self, context):
        layout = self.layout
        layout.prop(self, "rc_path")
        found = cry_compile.find_rc(self.rc_path)
        layout.label(text=str(found) if found else "rc.exe not found", icon=icon("CHECKMARK" if found else "ERROR"))
        layout.prop(self, "workspace_dir")


CLASSES = [KCD2_OT_export_cgf, KCD2_AddonPreferences]


def register() -> None:
    for cls in CLASSES:
        bpy.utils.register_class(cls)


def unregister() -> None:
    for cls in reversed(CLASSES):
        bpy.utils.unregister_class(cls)
