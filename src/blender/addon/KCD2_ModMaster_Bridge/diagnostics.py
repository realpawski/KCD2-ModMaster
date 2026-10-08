"""Material graph sanity checks and source-to-Blender diagnostics."""
import json
import logging
import math
log = logging.getLogger('KCD2_ModMaster_Bridge.diagnostics')


def diagnose_material(mat, bsdf, source, warnings):
    values = {}
    for socket in bsdf.inputs:
        if socket.type == 'VALUE':
            value = float(socket.default_value)
            values[socket.name] = {'default': value, 'connected': socket.is_linked}
            if not math.isfinite(value): warnings.append('Nonfinite '+socket.name)
    for name in ('Metallic', 'Roughness', 'Alpha', 'Specular IOR Level', 'Coat Weight', 'Coat Roughness', 'Transmission Weight', 'Anisotropic'):
        if name in bsdf.inputs and not 0 <= bsdf.inputs[name].default_value <= 1:
            warnings.append('Out of range '+name)
    if not 1 <= bsdf.inputs['IOR'].default_value <= 4: warnings.append('Suspicious IOR')
    for n in mat.node_tree.nodes:
        if n.name == 'KCD2_NORMAL' and n.image.colorspace_settings.name != 'Non-Color':
            warnings.append('Normal texture is not Non-Color')
    report = {'material': source.get('name'), 'id': source.get('id'),
              'mtl': source.get('mtl_path'), 'shader': source.get('shader'),
              'textures': source.get('resolved_textures'), 'principled': values,
              'normal_connected': bsdf.inputs['Normal'].is_linked,
              'metallic_range': list(mat.get('kcd2_metallic_range', [])), 'warnings': warnings}
    mat['kcd2_diagnostics'] = json.dumps(report)
    mat['kcd2_warnings'] = json.dumps(warnings)
    log.info('MATERIAL %s', json.dumps(report))
    for warning in warnings: log.warning('%s: %s', mat.name, warning)
