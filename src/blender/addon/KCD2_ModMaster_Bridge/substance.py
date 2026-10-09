"""Round trip to Adobe Substance 3D Painter: send the mesh over, bring the painted textures back."""
from __future__ import annotations

import subprocess
from pathlib import Path

import bpy

from . import cry_compile
from .metadata import get_active_asset_metadata
from .panel import icon

TEXTURES = "textures"


def substance_dir(context) -> Path | None:
    meta = get_active_asset_metadata(context.scene) or {}
    ws = meta.get("workspace_dir")
    return Path(ws) / "substance" if ws else None


def _meshes(context) -> list:
    from .cgf_export import _export_meshes
    return _export_meshes(context, bool(context.selected_objects))


def _prefs(context):
    addon = context.preferences.addons.get(__package__)
    return addon.preferences if addon else None


class KCD2_OT_open_substance(bpy.types.Operator):
    """Export the model and open it in Substance 3D Painter"""
    bl_idname = "kcd2.open_substance"
    bl_label = "Open in Substance Painter"

    def execute(self, context):
        prefs = _prefs(context)
        painter = cry_compile.find_painter(prefs.substance_path if prefs else None)
        if painter is None:
            self.report({"ERROR"}, "Substance 3D Painter not found. Set its path in the add-on preferences.")
            return {"CANCELLED"}
        folder = substance_dir(context)
        if folder is None:
            self.report({"ERROR"}, "Open the asset from ModMaster first, so its textures have a home.")
            return {"CANCELLED"}
        meshes = _meshes(context)
        if not meshes:
            self.report({"ERROR"}, "No visible mesh objects to paint.")
            return {"CANCELLED"}
        (folder / TEXTURES).mkdir(parents=True, exist_ok=True)
        try:
            plugin = cry_compile.install_painter_plugin()
        except OSError as exc:
            plugin = None
            self.report({"WARNING"}, f"The Painter plugin could not be installed: {exc}")
        project = next(iter(sorted(folder.glob("*.spp"))), None)
        if project is not None:
            # A saved Painter project keeps the layers; reopening it beats starting over from the mesh.
            args = [str(painter), str(project)]
        else:
            fbx = folder / f"{folder.parent.name}.fbx"
            previous = list(context.selected_objects)
            active = context.view_layer.objects.active
            try:
                bpy.ops.object.select_all(action="DESELECT")
                for obj in meshes:
                    obj.select_set(True)
                context.view_layer.objects.active = meshes[0]
                bpy.ops.export_scene.fbx(filepath=str(fbx), use_selection=True, object_types={"MESH"},
                                         use_mesh_modifiers=True, mesh_smooth_type="FACE", add_leaf_bones=False,
                                         bake_anim=False, path_mode="STRIP")
            finally:
                bpy.ops.object.select_all(action="DESELECT")
                for obj in previous:
                    obj.select_set(True)
                context.view_layer.objects.active = active
            args = [str(painter), "--mesh", str(fbx), "--export-path", str(folder / TEXTURES)]
        subprocess.Popen(args, close_fds=True)
        how = ("In Painter use File > Export for KCD2 ModMaster" if plugin
               else f"In Painter export the textures to {folder / TEXTURES}")
        self.report({"INFO"}, f"Painter opens. {how}, then click IMPORT SUBSTANCE TEXTURES here.")
        return {"FINISHED"}


def _image_node(tree, path: Path, non_color: bool, location):
    node = tree.nodes.new("ShaderNodeTexImage")
    node.image = bpy.data.images.load(str(path), check_existing=True)
    node.image.reload()
    if non_color:
        node.image.colorspace_settings.name = "Non-Color"
    node.location = location
    return node


def _link(tree, source, socket) -> None:
    for link in list(socket.links):
        tree.links.remove(link)
    tree.links.new(source, socket)


def apply_textures(mat, textures: dict) -> None:
    mat.use_nodes = True
    tree = mat.node_tree
    principled = next((n for n in tree.nodes if n.type == "BSDF_PRINCIPLED"), None)
    if principled is None:
        principled = tree.nodes.new("ShaderNodeBsdfPrincipled")
        output = next((n for n in tree.nodes if n.type == "OUTPUT_MATERIAL"), None) or \
            tree.nodes.new("ShaderNodeOutputMaterial")
        tree.links.new(principled.outputs["BSDF"], output.inputs["Surface"])
    x, y = principled.location.x - 700, principled.location.y
    if "base" in textures:
        node = _image_node(tree, textures["base"], False, (x, y))
        _link(tree, node.outputs["Color"], principled.inputs["Base Color"])
    if "metallic" in textures:
        node = _image_node(tree, textures["metallic"], True, (x, y - 300))
        _link(tree, node.outputs["Color"], principled.inputs["Metallic"])
    if "roughness" in textures:
        node = _image_node(tree, textures["roughness"], True, (x, y - 600))
        _link(tree, node.outputs["Color"], principled.inputs["Roughness"])
    if "normal" in textures:
        node = _image_node(tree, textures["normal"], True, (x, y - 900))
        normal_map = tree.nodes.new("ShaderNodeNormalMap")
        normal_map.location = (x + 300, y - 900)
        tree.links.new(node.outputs["Color"], normal_map.inputs["Color"])
        _link(tree, normal_map.outputs["Normal"], principled.inputs["Normal"])
    # The export copies a game material's own textures; painted ones must take its place.
    if "kcd2_source_material" in mat:
        del mat["kcd2_source_material"]


class KCD2_OT_import_substance(bpy.types.Operator):
    """Connect the textures exported from Substance Painter to the matching materials"""
    bl_idname = "kcd2.import_substance"
    bl_label = "Import Substance Textures"

    def execute(self, context):
        folder = substance_dir(context)
        textures_dir = folder / TEXTURES if folder else None
        if textures_dir is None or not textures_dir.is_dir():
            self.report({"ERROR"}, "No Substance textures yet. Use OPEN IN SUBSTANCE PAINTER and export there first.")
            return {"CANCELLED"}
        materials = {s.material.name: s.material for obj in _meshes(context) for s in obj.material_slots if s.material}
        files = [p for p in textures_dir.rglob("*") if p.is_file()]
        matched = cry_compile.match_substance_textures(files, list(materials))
        if not matched:
            names = ", ".join(cry_compile.texture_set(n) for n in materials) or "none"
            self.report({"ERROR"}, f"No exported textures match the materials ({names}). Painter names them "
                                   "<TextureSet>_BaseColor, _Normal, _Roughness.")
            return {"CANCELLED"}
        for name, textures in matched.items():
            apply_textures(materials[name], textures)
        missing = sorted(set(materials) - set(matched))
        note = f" No textures for: {', '.join(missing)}." if missing else ""
        self.report({"INFO"}, f"Textures connected for {len(matched)} material(s).{note} Now EXPORT TO KCD2.")
        return {"FINISHED"}


CLASSES = [KCD2_OT_open_substance, KCD2_OT_import_substance]


def register() -> None:
    for cls in CLASSES:
        bpy.utils.register_class(cls)


def unregister() -> None:
    for cls in reversed(CLASSES):
        bpy.utils.unregister_class(cls)
