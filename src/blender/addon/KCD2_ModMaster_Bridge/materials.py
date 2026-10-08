"""Rebuild ModMaster-owned shaders while preserving mesh data and face slots."""
from __future__ import annotations
import json
import logging
import re
from pathlib import Path
import bpy
import numpy as np
from .normal_decoder import decode_normal, read_bc_dds
from .material_adapter import preview_parameters, spec_gloss_to_principled, is_dielectric_shader
from .textures import detect_normal_semantic, classify_texture
from .diagnostics import diagnose_material

log = logging.getLogger('KCD2_ModMaster_Bridge.materials')
NODE_DIFFUSE = 'KCD2_DIFFUSE'
NODE_NORMAL = 'KCD2_NORMAL'
NODE_NORMAL_MAP = 'KCD2_NORMAL_MAP'
NODE_NORMAL_DECODER = 'KCD2_NORMAL_DECODER'


def validate_mesh_uvs(obj):
    valid = obj.type == 'MESH' and bool(obj.data.uv_layers)
    if not valid:
        log.warning('Missing UVs: %s', obj.name)
    return valid


def load_image_with_colorspace(filepath, colorspace='sRGB', fallback_pattern=None):
    path = str(Path(filepath).resolve())
    # Separate datablocks by role: Eye uses the same file for diffuse/specular.
    for im in bpy.data.images:
        if im.get('kcd2_source') == path and im.colorspace_settings.name == colorspace:
            return im
    try:
        im = bpy.data.images.load(path, check_existing=False)
        if not im.size[0]:
            bpy.data.images.remove(im)
            return None
        im.colorspace_settings.name = colorspace
        im.alpha_mode = 'CHANNEL_PACKED'
        im['kcd2_source'] = path
        return im
    except RuntimeError as exc:
        log.warning('Cannot load %s: %s', path, exc)
        return None


def image_pixels(image, width, height, color=False):
    if image is None:
        return np.ones((height, width, 4), np.float32)
    a = np.empty(len(image.pixels), np.float32)
    image.pixels.foreach_get(a)
    a = a.reshape(image.size[1], image.size[0], 4)
    if color and not image.is_float:
        rgb = a[:, :, :3]
        a[:, :, :3] = np.where(rgb <= .04045, rgb/12.92, ((rgb+.055)/1.055)**2.4)
    yi = np.minimum((np.arange(height)*a.shape[0]/height).astype(int), a.shape[0]-1)
    xi = np.minimum((np.arange(width)*a.shape[1]/width).astype(int), a.shape[1]-1)
    return a[yi[:, None], xi[None, :]].copy()


def generated_image(name, pixels, source=''):
    height, width = pixels.shape[:2]
    im = bpy.data.images.get(name)
    if im and (tuple(im.size) != (width, height) or not im.is_float):
        im = None
    if im is None:
        im = bpy.data.images.new(name, width, height, alpha=True, float_buffer=True)
    rgba = np.ones((height, width, 4), np.float32)
    if pixels.shape[2] == 1:
        rgba[:, :, :3] = pixels
    else:
        rgba[:, :, :pixels.shape[2]] = pixels
    im.colorspace_settings.name = 'Non-Color'
    im.alpha_mode = 'CHANNEL_PACKED'
    im.pixels.foreach_set(np.ascontiguousarray(rgba).ravel())
    im.update()
    im.pack()
    im['kcd2_source'] = source
    return im


def texture_node(nt, name, image, location):
    n = nt.nodes.new('ShaderNodeTexImage')
    n.name = name
    n.label = name.replace('KCD2_', '')
    n.image = image
    n.location = location
    return n


def build_material_node_tree(mat, submat_meta, textures_dir):
    params = preview_parameters(submat_meta)
    resolved = submat_meta.get('resolved_textures', {})
    mat['kcd2_texture_roles'] = json.dumps({slot: classify_texture(slot, name).value for slot, name in resolved.items()})
    if 'kcd2_imported_principled' not in mat:
        old = next((n for n in mat.node_tree.nodes if n.type == 'BSDF_PRINCIPLED'), None) if mat.use_nodes else None
        mat['kcd2_imported_principled'] = json.dumps({s.name: s.default_value for s in old.inputs if s.type == 'VALUE'} if old else {})
    mat['kcd2_source_material'] = json.dumps(submat_meta, sort_keys=True)
    mat['kcd2_generated'] = True
    for key in ('shader', 'id', 'name', 'mtl_path'):
        mat['kcd2_material_id' if key == 'id' else 'kcd2_'+key] = submat_meta.get(key, '')
    mat['kcd2_gloss'] = float(submat_meta.get('shininess', 255))/255
    mat.use_nodes = True
    nt = mat.node_tree
    nt.nodes.clear()
    bsdf = nt.nodes.new('ShaderNodeBsdfPrincipled')
    bsdf.location = (350, 80)
    output = nt.nodes.new('ShaderNodeOutputMaterial')
    output.location = (650, 80)
    nt.links.new(bsdf.outputs['BSDF'], output.inputs['Surface'])
    for key, val in params.items():
        if key in bsdf.inputs: bsdf.inputs[key].default_value = val
    warnings = []
    shader = submat_meta.get('shader', '').lower()
    if shader not in ('illum', 'hair', 'eye'): warnings.append('Unsupported shader '+shader+'; base spec/gloss preview only')
    if shader == 'eye': warnings.append('Eye cornea/parallax/iris SSS approximated by Principled')
    if shader == 'hair': warnings.append('Hair dual Kajiya-Kay highlights/soft intersections approximated by Principled')
    def load(slot, colorspace='sRGB'):
        filename = resolved.get(slot)
        if not filename:
            if slot in submat_meta.get('textures', {}): warnings.append('Unresolved '+slot)
            return None
        im = load_image_with_colorspace(textures_dir/filename, colorspace)
        if im is None: warnings.append('Missing/unreadable '+slot+': '+filename)
        return im
    diffuse, specular = load('Diffuse'), load('Specular')
    sizes = [tuple(im.size) for im in (diffuse, specular) if im]
    w, h = max((s[0] for s in sizes), default=1), max((s[1] for s in sizes), default=1)
    d, s = image_pixels(diffuse, w, h, True), image_pixels(specular, w, h, True)
    d[:, :, :3] *= np.asarray(submat_meta.get('diffuse_color', [1, 1, 1]))
    s[:, :, :3] *= np.asarray(submat_meta.get('specular_color', [.04, .04, .04]))
    base, metal = spec_gloss_to_principled(d[:, :, :3], s[:, :, :3])
    dielectric = is_dielectric_shader(submat_meta)
    if dielectric:
        base, metal = d[:, :, :3], np.zeros((h, w), np.float32)
    # Recover the residual dielectric F0 rather than leaving all low-reflectance
    # surfaces at Principled's 4% default. Specular IOR Level scales 8% at IOR 1.5.
    residual = np.maximum(0, (s[:, :, :3]-metal[:, :, None]*base)/np.maximum(1-metal[:, :, None], 1e-6))
    if dielectric: residual = s[:, :, :3]
    f0 = np.max(residual, axis=-1)
    spec_level = np.clip(f0/.08, 0, 1)
    tint = residual/np.maximum(f0[:, :, None], 1e-6)
    if dielectric and float(f0.max()) > .08:
        warnings.append('Dielectric F0 above 8% exceeds fixed-IOR preview range; original reflectance retained')
    base_node = texture_node(nt, NODE_DIFFUSE, generated_image(mat.name+'::BaseLinear', base), (-450, 350))
    nt.links.new(base_node.outputs['Color'], bsdf.inputs['Base Color'])
    metal_node = texture_node(nt, 'KCD2_METALLIC_PREVIEW', generated_image(mat.name+'::MetallicPreview', metal[:, :, None]), (-180, 350))
    nt.links.new(metal_node.outputs['Color'], bsdf.inputs['Metallic'])
    level_node = texture_node(nt, 'KCD2_SPECULAR_LEVEL', generated_image(mat.name+'::SpecularLevel', spec_level[:, :, None]), (-450, 80))
    nt.links.new(level_node.outputs['Color'], bsdf.inputs['Specular IOR Level'])
    tint_node = texture_node(nt, 'KCD2_SPECULAR_TINT', generated_image(mat.name+'::SpecularTint', tint), (-450, -50))
    nt.links.new(tint_node.outputs['Color'], bsdf.inputs['Specular Tint'])
    mat['kcd2_metallic_range'] = [float(metal.min()), float(metal.max())]
    mat['kcd2_adapter'] = 'Dielectric shader reflectance' if dielectric else 'Joint diffuse/reflectance spec-gloss conversion; preview approximation'
    cutoff, opacity = float(submat_meta.get('alpha_test', 0)), params['Alpha']
    if cutoff > 0 or opacity < 1:
        alpha = d[:, :, 3]
        if shader == 'hair':
            multiplier = float(submat_meta.get('public_params', {}).get('AlphaBlendMultiplier', 1))
            if not np.isfinite(multiplier) or multiplier < 0:
                raise ValueError('Invalid Hair AlphaBlendMultiplier')
            alpha = np.clip(alpha*multiplier, 0, 1)
        if cutoff > 0: alpha = np.where(alpha >= cutoff, alpha, 0)
        alpha = alpha*opacity
        alpha_node = texture_node(nt, 'KCD2_ALPHA', generated_image(mat.name+'::Alpha', alpha[:, :, None]), (-180, 100))
        nt.links.new(alpha_node.outputs['Color'], bsdf.inputs['Alpha'])
        if hasattr(mat, 'surface_render_method'): mat.surface_render_method = 'DITHERED'
    flags = int(submat_meta.get('source_attributes', {}).get('MtlFlags', 0))
    mat.use_backface_culling = not bool(flags & 2)
    normal_name = resolved.get('Bumpmap') or resolved.get('Normal')
    if normal_name:
        path = textures_dir/normal_name
        cfg = detect_normal_semantic(normal_name, path)
        mat['kcd2_texture_semantics'] = json.dumps(cfg)
        try:
            if cfg['encoding'] in ('BC5_SNORM_YX', 'BC5_UNORM_YX'):
                rgb = decode_normal(path)
                im = generated_image(mat.name+'::NormalDecoded', rgb[::-1], str(path))
            elif cfg['encoding'] == 'RGB_XYZ':
                im = load_image_with_colorspace(path, 'Non-Color')
            else: raise ValueError('Unknown normal encoding: '+cfg['encoding'])
            if im is None: raise ValueError('Normal image missing')
            tex = texture_node(nt, NODE_NORMAL, im, (-450, -200))
            normal = nt.nodes.new('ShaderNodeNormalMap')
            normal.name = NODE_NORMAL_MAP
            normal.label = cfg['encoding']+' decoded; strength 1'
            normal.location = (100, -200)
            normal.inputs['Strength'].default_value = 1
            nt.links.new(tex.outputs['Color'], normal.inputs['Color'])
            nt.links.new(normal.outputs['Normal'], bsdf.inputs['Normal'])
        except (ValueError, OSError) as exc: warnings.append(str(exc))
    gloss_name = resolved.get('Gloss')
    if gloss_name and shader == 'illum':
        try:
            gloss, fmt = read_bc_dds(textures_dir/gloss_name)
            if fmt != 80: raise ValueError('Expected BC4_UNORM gloss')
            gloss *= float(submat_meta.get('shininess', 255))/255
            rough = np.clip(1-gloss, 0, 1)
            node = texture_node(nt, 'KCD2_ROUGHNESS', generated_image(mat.name+'::Roughness', rough[::-1]), (-180, -400))
            nt.links.new(node.outputs['Color'], bsdf.inputs['Roughness'])
            mat['kcd2_roughness_range'] = [float(rough.min()), float(rough.max())]
        except (ValueError, OSError) as exc: warnings.append(str(exc))
    elif normal_name and '_ddna' in normal_name.lower() and shader == 'illum':
        warnings.append('DDNA attached gloss missing; sync textures to stage .dds.a stream')
    if resolved.get('Detail'): warnings.append('Merged detail overlay not represented in base preview')
    if resolved.get('Custom'): warnings.append('Custom shader data preserved; not guessed as gloss')
    diagnose_material(mat, bsdf, submat_meta, warnings)


def reconstruct_all_materials_for_objects(objects, metadata, *, allow_imported=False):
    by_name = {m.get('name', '').casefold(): m for m in metadata.get('materials', [])}
    by_id = {m.get('id'): m for m in metadata.get('materials', [])}
    textures_dir, built, generated = Path(metadata.get('textures_dir', '')), set(), {}
    for obj in objects:
        if obj.type != 'MESH': continue
        if any(x in obj.name.casefold() for x in ('shadowproxy', '$physics', 'proxy_')): continue
        validate_mesh_uvs(obj)
        for idx, slot in enumerate(obj.material_slots):
            original = slot.material
            if not original: continue
            if not allow_imported and not original.get('kcd2_generated') and 'kcd2_material_id' not in original:
                log.info('Preserving user material %s in %s slot %d', original.name, obj.name, idx)
                continue
            name = re.sub(r'\.\d{3}$', '', original.get('kcd2_source_name', original.name)).casefold()
            submat = by_name.get(name)
            if original.get('kcd2_generated'):
                submat = by_id.get(original.get('kcd2_material_id')) or submat
            # Blender slots follow primitive order, NOT KCD2 material IDs.
            if submat is None:
                log.warning('Unmatched material %s in %s slot %d; preserved', original.name, obj.name, idx)
                continue
            if submat.get('is_proxy'): continue
            key, mat = (original.as_pointer(), submat['id']), original
            if not original.get('kcd2_generated'):
                mat = generated.get(key)
                if mat is None:
                    mat = original.copy()
                    mat.name = original.name+' [ModMaster]'
                    mat['kcd2_source_name'] = original.name
                    generated[key] = mat
                slot.link = "OBJECT"
                slot.material = mat
            if mat.as_pointer() not in built:
                build_material_node_tree(mat, dict(submat, mtl_path=metadata.get('mtl_path', '')), textures_dir)
                built.add(mat.as_pointer())
            faces = sum(p.material_index == idx for p in obj.data.polygons)
            log.info('MAPPING mesh=%s KCD2_ID=%s submaterial=%s Blender_slot=%d faces=%d UV=%s', obj.name, submat['id'], submat['name'], idx, faces, [uv.name for uv in obj.data.uv_layers])
            if not faces: log.warning('Zero polygons: %s slot %d', obj.name, idx)
        invalid = sum(p.material_index >= len(obj.material_slots) for p in obj.data.polygons)
        if invalid: log.error('%s: %d polygons reference nonexistent material slots', obj.name, invalid)
    return len(built)
