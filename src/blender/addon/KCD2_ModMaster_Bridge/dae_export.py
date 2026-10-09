"""Writes a skinned mesh as CryEngine Collada, the only rigged input Warhorse's Resource Compiler takes."""
from __future__ import annotations

import math
from pathlib import Path
from xml.sax.saxutils import escape, quoteattr

import bpy
from mathutils import Matrix

# Imported game models sit rotated by 180 degrees around Z in Blender; exports turn them back.
TO_GAME = Matrix.Rotation(math.pi, 4, 'Z')
MAX_WEIGHTS = 4


def _matrix(m: Matrix) -> str:
    return " ".join(f"{m[r][c]:.6f}" for r in range(4) for c in range(4))


def _floats(values) -> str:
    return " ".join(f"{v:.6f}" for v in values)


def _sid(name: str) -> str:
    return "".join(ch if ch.isalnum() or ch in "_-." else "_" for ch in name)


def clean_material_name(name: str) -> str:
    return name.replace(" [ModMaster]", "").strip()


def material_label(library: str, index: int, name: str) -> str:
    return f"{library}-{index + 1:02d}-{name}"


def _mesh_section(obj, mesh, index: int, materials: list[str], library: str) -> tuple[str, list[str]]:
    gid = f"geom{index}"
    world = TO_GAME @ obj.matrix_world
    normal_m = world.to_3x3().inverted().transposed()
    positions = [world @ v.co for v in mesh.vertices]
    mesh.calc_loop_triangles()
    corner_normals = [normal_m @ n.vector for n in mesh.corner_normals]
    uv_layer = mesh.uv_layers.active
    uvs = [d.uv for d in uv_layer.data] if uv_layer else [(0.0, 0.0)] * len(mesh.loops)

    by_material: dict[int, list[int]] = {}
    for tri in mesh.loop_triangles:
        slot = tri.material_index
        for loop in tri.loops:
            by_material.setdefault(slot, []).extend((mesh.loops[loop].vertex_index, loop, loop))

    out = [f'  <geometry id="{gid}" name={quoteattr(obj.name)}><mesh>',
           f'   <source id="{gid}-pos"><float_array id="{gid}-pos-a" count="{len(positions) * 3}">'
           f'{_floats(c for p in positions for c in p)}</float_array><technique_common>'
           f'<accessor source="#{gid}-pos-a" count="{len(positions)}" stride="3"><param name="X" type="float"/>'
           f'<param name="Y" type="float"/><param name="Z" type="float"/></accessor></technique_common></source>',
           f'   <source id="{gid}-nrm"><float_array id="{gid}-nrm-a" count="{len(corner_normals) * 3}">'
           f'{_floats(c for n in corner_normals for c in n.normalized())}</float_array><technique_common>'
           f'<accessor source="#{gid}-nrm-a" count="{len(corner_normals)}" stride="3"><param name="X" type="float"/>'
           f'<param name="Y" type="float"/><param name="Z" type="float"/></accessor></technique_common></source>',
           f'   <source id="{gid}-uv"><float_array id="{gid}-uv-a" count="{len(uvs) * 2}">'
           f'{_floats(c for uv in uvs for c in (uv[0], uv[1]))}</float_array><technique_common>'
           f'<accessor source="#{gid}-uv-a" count="{len(uvs)}" stride="2"><param name="S" type="float"/>'
           f'<param name="T" type="float"/></accessor></technique_common></source>',
           f'   <vertices id="{gid}-v"><input semantic="POSITION" source="#{gid}-pos"/></vertices>']
    used = []
    for slot, indices in sorted(by_material.items()):
        mat = obj.material_slots[slot].material if slot < len(obj.material_slots) else None
        name = clean_material_name(mat.name) if mat else "kcd2_default"
        if name not in materials:
            materials.append(name)
        label = material_label(library, materials.index(name), name)
        used.append(label)
        out.append(f'   <triangles material="{escape(_sid(label))}" count="{len(indices) // 9}">'
                   f'<input semantic="VERTEX" source="#{gid}-v" offset="0"/>'
                   f'<input semantic="NORMAL" source="#{gid}-nrm" offset="1"/>'
                   f'<input semantic="TEXCOORD" source="#{gid}-uv" offset="2" set="0"/>'
                   f'<p>{" ".join(map(str, indices))}</p></triangles>')
    out.append("  </mesh></geometry>")
    return "\n".join(out), used


def _controller(obj, mesh, index: int, bones: list, bone_world: dict, fallback_bone: str | None = None) -> str:
    cid, gid = f"skin{index}", f"geom{index}"
    names = [b.name for b in bones]
    group_to_bone = {g.index: g.name for g in obj.vertex_groups if g.name in bone_world}
    weights: list[float] = []
    vcount: list[int] = []
    pairs: list[int] = []
    for v in mesh.vertices:
        influences = sorted(((g.weight, group_to_bone[g.group]) for g in v.groups
                             if g.group in group_to_bone and g.weight > 1e-4), reverse=True)[:MAX_WEIGHTS]
        if not influences:
            influences = [(1.0, fallback_bone if fallback_bone in names else names[0])]
        total = sum(w for w, _ in influences)
        vcount.append(len(influences))
        for w, bone in influences:
            pairs += [names.index(bone), len(weights)]
            weights.append(w / total)
    ibms = [bone_world[n].inverted() for n in names]
    return "\n".join([
        f'  <controller id="{cid}"><skin source="#{gid}">',
        f'   <bind_shape_matrix>{_matrix(Matrix.Identity(4))}</bind_shape_matrix>',
        f'   <source id="{cid}-joints"><IDREF_array id="{cid}-joints-a" count="{len(names)}">'
        f'{" ".join(_sid(n) for n in names)}</IDREF_array><technique_common><accessor source="#{cid}-joints-a" '
        f'count="{len(names)}" stride="1"><param name="JOINT" type="IDREF"/></accessor></technique_common></source>',
        f'   <source id="{cid}-ibm"><float_array id="{cid}-ibm-a" count="{len(names) * 16}">'
        f'{" ".join(_matrix(m) for m in ibms)}</float_array><technique_common><accessor source="#{cid}-ibm-a" '
        f'count="{len(names)}" stride="16"><param name="TRANSFORM" type="float4x4"/></accessor></technique_common></source>',
        f'   <source id="{cid}-w"><float_array id="{cid}-w-a" count="{len(weights)}">{_floats(weights)}</float_array>'
        f'<technique_common><accessor source="#{cid}-w-a" count="{len(weights)}" stride="1">'
        f'<param name="WEIGHT" type="float"/></accessor></technique_common></source>',
        f'   <joints><input semantic="JOINT" source="#{cid}-joints"/>'
        f'<input semantic="INV_BIND_MATRIX" source="#{cid}-ibm"/></joints>',
        f'   <vertex_weights count="{len(vcount)}"><input semantic="JOINT" source="#{cid}-joints" offset="0"/>'
        f'<input semantic="WEIGHT" source="#{cid}-w" offset="1"/><vcount>{" ".join(map(str, vcount))}</vcount>'
        f'<v>{" ".join(map(str, pairs))}</v></vertex_weights>',
        "  </skin></controller>",
    ])


def _joint_nodes(bone, bone_world: dict, depth: int) -> str:
    parent_world = bone_world[bone.parent.name] if bone.parent else Matrix.Identity(4)
    local = parent_world.inverted() @ bone_world[bone.name]
    pad = " " * depth
    children = "".join(_joint_nodes(c, bone_world, depth + 1) for c in bone.children)
    sid = _sid(bone.name)
    return (f'{pad}<node id="{sid}" name={quoteattr(bone.name)} sid="{sid}" type="JOINT">'
            f'<matrix sid="transform">{_matrix(local)}</matrix>\n{children}{pad}</node>\n')


def game_matrix(rows: list[float]) -> Matrix:
    """A 3x4 row-major bone matrix from a game file."""
    return Matrix((rows[0:4], rows[4:8], rows[8:12], (0.0, 0.0, 0.0, 1.0)))


def write_skin_dae(path: Path, name: str, armature, meshes: list, library: str,
                   original_bones: dict[str, list[float]] | None = None,
                   rigid: dict[str, str] | None = None) -> list[str]:
    """Write `meshes` skinned to `armature` and return the Blender material names in slot order.

    Blender changes bone orientations on import, while the game requires its own (an identity
    root, matching frames for animations), so known bones keep the matrices from the game file.
    """
    bones = list(armature.data.bones)
    original_bones = original_bones or {}
    bone_world = {b.name: game_matrix(original_bones[b.name]) if b.name in original_bones
                  else TO_GAME @ armature.matrix_world @ b.matrix_local for b in bones}
    depsgraph = bpy.context.evaluated_depsgraph_get()
    materials: list[str] = []
    geometries, controllers, nodes = [], [], []
    for index, obj in enumerate(meshes):
        evaluated = obj.evaluated_get(depsgraph)
        mesh = evaluated.to_mesh(preserve_all_data_layers=True, depsgraph=depsgraph)
        try:
            section, used = _mesh_section(obj, mesh, index, materials, library)
            geometries.append(section)
            controllers.append(_controller(obj, mesh, index, bones, bone_world, (rigid or {}).get(obj.name)))
        finally:
            evaluated.to_mesh_clear()
        bindings = "".join(f'<instance_material symbol="{escape(_sid(label))}" target="#{escape(_sid(label))}"/>'
                           for label in used)
        nodes.append(f'   <node id="mesh{index}" name={quoteattr(obj.name)}><instance_controller url="#skin{index}">'
                     f'<skeleton>#{_sid(bones[0].name)}</skeleton><bind_material><technique_common>{bindings}'
                     f'</technique_common></bind_material></instance_controller></node>')

    labels = [material_label(library, i, m) for i, m in enumerate(materials)]
    effects = "\n".join(f'  <effect id="{_sid(l)}-fx"><profile_COMMON><technique sid="common"><phong>'
                        f'<diffuse><color sid="diffuse">1 1 1 1</color></diffuse></phong></technique></profile_COMMON></effect>'
                        for l in labels)
    mats = "\n".join(f'  <material id="{_sid(l)}" name={quoteattr(l)}><instance_effect url="#{_sid(l)}-fx"/></material>'
                     for l in labels)
    roots = "".join(_joint_nodes(b, bone_world, 3) for b in bones if b.parent is None)
    export_id = _sid(f"CryExportNode_{name}")
    text = "\n".join([
        '<?xml version="1.0" encoding="utf-8"?>',
        '<COLLADA xmlns="http://www.collada.org/2005/11/COLLADASchema" version="1.4.1">',
        ' <asset><contributor><authoring_tool>KCD2 ModMaster</authoring_tool></contributor>'
        '<unit name="meter" meter="1"/><up_axis>Z_UP</up_axis></asset>',
        f" <library_effects>\n{effects}\n </library_effects>",
        f" <library_materials>\n{mats}\n </library_materials>",
        " <library_geometries>\n" + "\n".join(geometries) + "\n </library_geometries>",
        " <library_controllers>\n" + "\n".join(controllers) + "\n </library_controllers>",
        ' <library_visual_scenes><visual_scene id="scene" name="scene">',
        f'  <node id="{export_id}" name="{export_id}">',
        "\n".join(nodes),
        roots.rstrip("\n"),
        # One property per line; a space-separated list makes rc ignore fileType and build a .cgf.
        '   <extra><technique profile="CryEngine"><properties>fileType=skin\nDoNotMerge\nUseCustomNormals'
        '</properties></technique></extra>',
        "  </node>",
        " </visual_scene></library_visual_scenes>",
        ' <scene><instance_visual_scene url="#scene"/></scene>',
        "</COLLADA>",
    ])
    Path(path).write_text(text, encoding="utf-8")
    return materials
