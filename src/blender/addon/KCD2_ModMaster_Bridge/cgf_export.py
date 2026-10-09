"""Export to KCD2: Blender scene to compiled .cgf, .mtl and .dds inside a ModMaster workspace asset."""
from __future__ import annotations

import json
import tempfile
import time
from pathlib import Path

import bpy

from . import cry_compile, dae_export
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
    objects = list(context.selected_objects if selected_only else context.view_layer.objects)
    # A selected skeleton stands for everything it carries: bound meshes and objects parented to it.
    for arm in [o for o in objects if o.type == "ARMATURE"]:
        for obj in context.view_layer.objects:
            bound = any(m.type == "ARMATURE" and m.object == arm for m in getattr(obj, "modifiers", []))
            if (bound or obj.parent == arm) and obj not in objects:
                objects.append(obj)
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


def _pot_pixels(image, size=None):
    """RGBA floats of an image at a power-of-two size (or the given one), rows top to bottom."""
    import numpy as np

    copy = image.copy()
    try:
        w, h = copy.size
        pot = lambda v: 1 << max(v - 1, 1).bit_length()
        target = size or (pot(w), pot(h))
        if (w, h) != target:
            copy.scale(*target)
        pixels = np.empty(target[0] * target[1] * 4, dtype=np.float32)
        copy.pixels.foreach_get(pixels)
    finally:
        bpy.data.images.remove(copy)
    return target, pixels.reshape(target[1], target[0], 4)[::-1]


def _save_ddna(normal, roughness, path: Path) -> Path:
    """Normal map with smoothness (1 - roughness) in alpha, the layout of the game's _ddna textures."""
    import numpy as np

    if normal is not None:
        size, pixels = _pot_pixels(normal)
    else:
        size, rough = _pot_pixels(roughness)
        pixels = np.empty_like(rough)
        pixels[..., 0:3] = (0.5, 0.5, 1.0)
    _size, rough = _pot_pixels(roughness, size)
    pixels = pixels.copy()
    pixels[..., 3] = 1.0 - rough[..., 0]
    data = (np.clip(pixels, 0.0, 1.0) * 255.0 + 0.5).astype(np.uint8).tobytes()
    return cry_compile.write_tiff_rgba(path, size[0], size[1], data)


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
    roughness = _image_input(principled.inputs.get("Roughness"))
    if roughness:
        tif = _save_ddna(normal, roughness, work / f"{stem}_ddna.tif")
        cry_compile.compile_texture(rc, tif, tex_root / f"{stem}_ddna.dds", "NormalsWithSmoothness")
        entry["textures"]["Bumpmap"] = f"{tex_virtual}/{stem}_ddna.dds"
    elif normal:
        tif = _save_tif(normal, work / f"{stem}_ddna.tif")
        cry_compile.compile_texture(rc, tif, tex_root / f"{stem}_ddna.dds", "Normals")
        entry["textures"]["Bumpmap"] = f"{tex_virtual}/{stem}_ddna.dds"
    return entry


def _rigged_meshes(meshes: list) -> tuple:
    """The armature the meshes deform with and the meshes bound to it."""
    for obj in meshes:
        for mod in obj.modifiers:
            if mod.type == "ARMATURE" and mod.object is not None:
                arm = mod.object
                bound = [o for o in meshes if any(m.type == "ARMATURE" and m.object == arm for m in o.modifiers)]
                return arm, bound
    return None, []


def _nearest_bone(armature, obj) -> str:
    """The bone closest to an object's centre, so a loose hat follows the head."""
    from mathutils import Vector
    from mathutils.geometry import intersect_point_line

    corners = [obj.matrix_world @ Vector(c) for c in obj.bound_box]
    centre = sum(corners, Vector()) / len(corners)
    best, best_distance = "", float("inf")
    for bone in armature.data.bones:
        head = armature.matrix_world @ bone.head_local
        tail = armature.matrix_world @ bone.tail_local
        point, factor = intersect_point_line(centre, head, tail)
        point = head if factor < 0 else tail if factor > 1 else point
        distance = (centre - point).length
        if distance < best_distance:
            best, best_distance = bone.name, distance
    return best


def _original_bones(meta: dict) -> dict:
    """Bone matrices from the game files the rigged model was imported from."""
    bones: dict = {}
    source = Path(meta.get("source_dir", ""))
    for part in meta.get("parts", []):
        path = source / part.get("virtual_path", "")
        if path.is_file():
            for name, rows in cry_compile.read_bone_matrices(path.read_bytes()).items():
                bones.setdefault(name, rows)
    return bones


class _GameOrientation:
    """Turns the meshes back into game orientation for the duration of an export."""

    def __init__(self, objects: list):
        self.saved = {o: o.matrix_world.copy() for o in objects}
        self.order = sorted(objects, key=self._depth)

    @staticmethod
    def _depth(obj) -> int:
        depth = 0
        while obj.parent is not None:
            obj, depth = obj.parent, depth + 1
        return depth

    def __enter__(self):
        for obj in self.order:
            obj.matrix_world = dae_export.TO_GAME @ self.saved[obj]
        return self

    def __exit__(self, *_exc):
        for obj in self.order:
            obj.matrix_world = self.saved[obj]


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
    """Compile the model for KCD2: a static .cgf, or a rigged .skin with character definition"""
    bl_idname = "kcd2.export_cgf"
    bl_label = "Export to KCD2"
    bl_options = {"REGISTER"}

    export_type: bpy.props.EnumProperty(name="Export as", items=[
        ("STATIC", "Static model (.cgf)", "A prop or the model of an item. Bones and weights are ignored"),
        ("RIGGED", "Rigged model (.skin)", "Keeps skin weights on the game skeleton so the game's animations play"),
    ])
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
        armature, _bound = _rigged_meshes(_export_meshes(context, self.selected_only))
        self.export_type = "RIGGED" if armature is not None and meta.get("skeleton") else "STATIC"
        return context.window_manager.invoke_props_dialog(self, width=460)

    def draw(self, context):
        layout = self.layout
        layout.prop(self, "export_type", expand=True)
        layout.separator()
        layout.prop(self, "target")
        if self.target == NEW_ASSET:
            layout.prop(self, "new_name")
        layout.prop(self, "selected_only")
        if self.export_type == "RIGGED":
            layout.label(text="Mesh and weights may change; keep the game's bones.", icon=icon("INFO"))
        else:
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
                if self.export_type == "RIGGED":
                    result = self._export_rigged(meta, meshes, asset_id, rc, work, compiled, tex_virtual, mtl_path)
                else:
                    result = self._export_static(context, meshes, asset_id, rc, work, compiled, model,
                                                 tex_virtual, mtl_path)
        except cry_compile.CompileError as exc:
            self.report({"ERROR"}, f"Compile failed: {exc}")
            return {"CANCELLED"}
        except ValueError as exc:
            self.report({"ERROR"}, str(exc))
            return {"CANCELLED"}
        finally:
            bpy.ops.object.select_all(action="DESELECT")
            for obj in previous_selection:
                obj.select_set(True)
            context.view_layer.objects.active = previous_active
        produced, subs = result

        meta_file = asset_dir / "metadata" / ".modmaster_asset.json"
        try:
            data = json.loads(meta_file.read_text(encoding="utf-8"))
            data.update({"compiled_model": produced, "compiled_at": time.time(), "updated_at": time.time()})
            meta_file.write_text(json.dumps(data, indent=2), encoding="utf-8")
        except (OSError, ValueError):
            pass
        send_message_to_modmaster({"command": "asset_compiled", "asset_id": asset_id,
                                   "model": produced, "timestamp": time.time()})
        self.report({"INFO"}, f"Compiled {Path(produced).name} with {len(subs)} material(s). "
                              "Add the asset to a mod in ModMaster and build it.")
        return {"FINISHED"}

    def _materials(self, names, rc, work, compiled, tex_virtual, mtl_path, lookup):
        return [_material_entry(lookup(name), name, rc, work, compiled / tex_virtual, tex_virtual, mtl_path)
                for name in names]

    def _export_static(self, context, meshes, asset_id, rc, work, compiled, model, tex_virtual, mtl_path):
        fbx = work / f"{asset_id}.fbx"
        bpy.ops.object.select_all(action="DESELECT")
        for obj in meshes:
            obj.select_set(True)
        context.view_layer.objects.active = meshes[0]
        with _GameOrientation(meshes):
            bpy.ops.export_scene.fbx(filepath=str(fbx), use_selection=True, object_types={"MESH"},
                                     use_mesh_modifiers=True, mesh_smooth_type="FACE",
                                     apply_scale_options="FBX_SCALE_UNITS", add_leaf_bones=False,
                                     bake_anim=False, path_mode="STRIP")
        subs = cry_compile.compile_model(rc, fbx, compiled / f"{model}.cgf", model)
        entries = self._materials(subs, rc, work, compiled, tex_virtual, mtl_path, bpy.data.materials.get)
        cry_compile.write_mtl(compiled / f"{model}.mtl", entries)
        return f"{model}.cgf", subs

    def _export_rigged(self, meta, meshes, asset_id, rc, work, compiled, tex_virtual, mtl_path):
        armature, bound = _rigged_meshes(meshes)
        if armature is None:
            raise ValueError("No mesh is bound to an armature. Import the model as 'Rigged model' first.")
        skeleton = meta.get("skeleton")
        if not skeleton:
            raise ValueError("Rigged export needs a skeleton from the game. Import a character or animal "
                             "as 'Rigged model' and export from that scene.")
        model, _textures = cry_compile.model_paths(asset_id)
        dae = work / f"{asset_id}.dae"
        rigid = {m.name: _nearest_bone(armature, m) for m in meshes if m not in bound}
        for mesh_name, bone in rigid.items():
            self.report({"INFO"}, f"{mesh_name} is not weighted to the skeleton; it follows bone {bone}.")
        materials = dae_export.write_skin_dae(dae, asset_id, armature, bound + [m for m in meshes if m not in bound],
                                              asset_id, _original_bones(meta), rigid)
        subs = cry_compile.compile_skin(rc, dae, compiled / f"{model}.skin")
        by_label = {dae_export.material_label(asset_id, i, m): m for i, m in enumerate(materials)}
        by_clean = {dae_export.clean_material_name(m.name): m for m in bpy.data.materials}

        def lookup(sub):
            return by_clean.get(by_label.get(sub, dae_export.clean_material_name(sub)))

        entries = self._materials(subs, rc, work, compiled, tex_virtual, mtl_path, lookup)
        cry_compile.write_mtl(compiled / f"{model}.mtl", entries)
        cry_compile.write_cdf(compiled / f"{model}.cdf", skeleton, f"{model}.skin", f"{model}.mtl")
        return f"{model}.cdf", subs


class KCD2_AddonPreferences(bpy.types.AddonPreferences):
    bl_idname = __package__

    rc_path: bpy.props.StringProperty(
        name="Resource Compiler (rc.exe)", subtype="FILE_PATH",
        description="Found automatically when KCD2 Modding Tools are installed through Steam")
    workspace_dir: bpy.props.StringProperty(
        name="ModMaster workspace", subtype="DIR_PATH",
        description="Used when the scene was not opened from ModMaster")
    substance_path: bpy.props.StringProperty(
        name="Substance 3D Painter", subtype="FILE_PATH",
        description="Found automatically in the default Adobe and Steam folders")

    def draw(self, context):
        layout = self.layout
        layout.prop(self, "rc_path")
        found = cry_compile.find_rc(self.rc_path)
        layout.label(text=str(found) if found else "rc.exe not found", icon=icon("CHECKMARK" if found else "ERROR"))
        layout.prop(self, "workspace_dir")
        layout.prop(self, "substance_path")
        painter = cry_compile.find_painter(self.substance_path)
        layout.label(text=str(painter) if painter else "Substance 3D Painter not found",
                     icon=icon("CHECKMARK" if painter else "INFO"))


CLASSES = [KCD2_OT_export_cgf, KCD2_AddonPreferences]


def register() -> None:
    for cls in CLASSES:
        bpy.utils.register_class(cls)


def unregister() -> None:
    for cls in reversed(CLASSES):
        bpy.utils.unregister_class(cls)
