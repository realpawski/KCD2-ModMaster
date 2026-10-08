"""Controlled preview conversion from KCD2's diffuse/reflectance workflow.

Joint diffuse/specular conversion follows the Khronos spec/gloss conversion
quadratic, rather than treating reflectance intensity as a metallic map.
Original KCD2 values are retained separately by the builder.
"""
import numpy as np


def spec_gloss_to_principled(diffuse, specular):
    d = np.clip(np.asarray(diffuse, dtype=np.float32), 0, 1)
    s = np.clip(np.asarray(specular, dtype=np.float32), 0, 1)
    brightness = lambda c: np.sqrt(np.sum(c*c*np.array([.299, .587, .114]), axis=-1))
    db, sb = brightness(d), brightness(s)
    one_minus = 1-np.max(s, axis=-1)
    a = .04
    b = db*one_minus/.96+sb-.08
    c = .04-sb
    metallic = np.where(sb < .04, 0, np.clip((-b+np.sqrt(np.maximum(b*b-4*a*c, 0)))/(2*a), 0, 1))
    m = metallic[..., None]
    from_diffuse = d*one_minus[..., None]/(.96*np.maximum(1-m, 1e-6))
    from_specular = (s-.04*(1-m))/np.maximum(m, 1e-6)
    base = np.clip(from_diffuse*(1-m*m)+from_specular*m*m, 0, 1)
    return base.astype(np.float32), metallic.astype(np.float32)


def preview_parameters(meta):
    gloss = float(meta.get('shininess', 255))/255
    if not np.isfinite(gloss) or not 0 <= gloss <= 1:
        raise ValueError(f'Invalid KCD2 Shininess: {meta.get("shininess")}')
    opacity = float(meta.get('opacity', 1))
    if not np.isfinite(opacity) or not 0 <= opacity <= 1:
        raise ValueError(f'Invalid KCD2 Opacity: {opacity}')
    shader = meta.get('shader', '').lower()
    # Hair.cfx explicitly clamps scalar smoothness and does not sample DDNA gloss.
    if shader == 'hair':
        gloss = min(.9, max(.5, gloss))
    if shader == 'eye':
        gloss = float(meta.get('public_params', {}).get('CorneaSmoothness', gloss))
    return {'IOR': 1.5, 'Specular IOR Level': .5, 'Alpha': opacity,
            'Roughness': 1-gloss, 'Coat Weight': 0., 'Coat Roughness': .03,
            'Transmission Weight': 0., 'Emission Strength': 0.,
            'Anisotropic': 0., 'Subsurface Weight': 0., 'Sheen Weight': 0.,
            'Weight': 1.}


def is_dielectric_shader(meta):
    """Hair, Eye and subsurface permutations model transmitting tissue/fibers.

    Their reflectance must not be reinterpreted as a conductor. Illum with no
    such permutation retains the joint-color preview conversion.
    """
    flags = meta.get('source_attributes', {}).get('StringGenMask', '')
    return meta.get('shader', '').lower() in ('hair', 'eye') or '%SUBSURFACE_SCATTERING' in flags
