"""Interactive 3D OpenGL Viewport for KCD2 assets.

Features:
- Pure OpenGL 3.3 Core rendering (no painter state conflicts)
- Orbit, pan, zoom camera with framing & standard views (Front, Top, Left, etc.)
- Shading modes:
  0 = Textured (vanilla textures, normal maps, alpha cutout, multi-material slots)
  1 = Studio Clay (neutral clay shaded surface, no textures, no wireframe)
  2 = Wireframe (neutral solid surface with clean uniform topology wire overlay)
- Real-scale 3D Ground Grid (1.0m major lines, 0.1m minor lines)
- Ground floor plane under model bounding box
- Corner orientation axis gizmo (X, Y, Z) rendered in native OpenGL
- HUD statistics: Triangles, Vertices, Dimensions (X, Y, Z in meters)
"""
from __future__ import annotations

import ctypes
import math
from pathlib import Path
from typing import Any

import numpy as np
from OpenGL import GL

from PySide6.QtCore import QPoint, Qt, Signal
from PySide6.QtGui import (
    QImage,
    QMatrix4x4,
    QMouseEvent,
    QVector3D,
    QVector4D,
    QWheelEvent,
)
from PySide6.QtOpenGL import (
    QOpenGLBuffer,
    QOpenGLShader,
    QOpenGLShaderProgram,
    QOpenGLVertexArrayObject,
)
from PySide6.QtOpenGLWidgets import QOpenGLWidget

from preview.gltf_loader import MaterialInfo, MeshGeometry, PrimitivePart

DEBUG_MATERIAL_PALETTE: list[QVector4D] = [
    QVector4D(0.95, 0.22, 0.22, 1.0),  # 0: Vibrant Red
    QVector4D(0.22, 0.85, 0.30, 1.0),  # 1: Vibrant Green
    QVector4D(0.20, 0.55, 0.98, 1.0),  # 2: Vibrant Blue
    QVector4D(0.98, 0.85, 0.15, 1.0),  # 3: Vibrant Yellow
    QVector4D(0.15, 0.90, 0.90, 1.0),  # 4: Vibrant Cyan
    QVector4D(0.90, 0.20, 0.90, 1.0),  # 5: Vibrant Magenta
    QVector4D(0.98, 0.55, 0.15, 1.0),  # 6: Vibrant Orange
    QVector4D(0.65, 0.25, 0.95, 1.0),  # 7: Vibrant Purple
    QVector4D(0.70, 0.95, 0.20, 1.0),  # 8: Lime Green
    QVector4D(0.15, 0.70, 0.65, 1.0),  # 9: Teal
    QVector4D(0.95, 0.45, 0.65, 1.0),  # 10: Rose Pink
    QVector4D(0.55, 0.80, 0.95, 1.0),  # 11: Sky Blue
]

VERTEX_SHADER_SRC = """#version 330 core
layout(location = 0) in vec3 a_pos;
layout(location = 1) in vec3 a_norm;
layout(location = 2) in vec2 a_uv;
layout(location = 3) in vec4 a_tangent;

uniform mat4 u_mvp;
uniform mat4 u_model;
uniform mat3 u_norm_mat;

out vec3 v_world_pos;
out vec3 v_world_norm;
out vec3 v_world_tangent;
out vec3 v_world_bitangent;
out vec2 v_uv;

void main() {
    vec3 norm = normalize(u_norm_mat * a_norm);
    vec3 tang = normalize(u_norm_mat * a_tangent.xyz);
    // Gram-Schmidt orthogonalization
    tang = normalize(tang - dot(tang, norm) * norm);
    float handedness = (a_tangent.w < 0.0) ? -1.0 : 1.0;
    vec3 bitang = normalize(cross(norm, tang) * handedness);

    v_world_pos = vec3(u_model * vec4(a_pos, 1.0));
    v_world_norm = norm;
    v_world_tangent = tang;
    v_world_bitangent = bitang;
    v_uv = a_uv;
    gl_Position = u_mvp * vec4(a_pos, 1.0);
}
"""

FRAGMENT_SHADER_SRC = """#version 330 core
in vec3 v_world_pos;
in vec3 v_world_norm;
in vec3 v_world_tangent;
in vec3 v_world_bitangent;
in vec2 v_uv;

uniform int u_mode;           // 0 = textured, 1 = clay, 2 = wireframe solid, 3 = mat ID
uniform int u_normal_enabled;  // 1 = normal maps active, 0 = bypassed
uniform vec3 u_cam_pos;

// Material uniforms
uniform vec4 u_base_color;
uniform int u_has_diffuse_tex;
uniform sampler2D u_diffuse_tex;
uniform int u_has_normal_tex;
uniform sampler2D u_normal_tex;
uniform int u_alpha_mode;      // 0 = OPAQUE, 1 = MASK, 2 = BLEND
uniform float u_alpha_cutoff;

// PBR uniforms
uniform float u_roughness;
uniform float u_metallic;
uniform vec3 u_specular_f0;

out vec4 frag_color;

const float PI = 3.141592653589793;

// Decode KCD2 DirectX 2-channel BC5 / DDNA normal map to normalized tangent-space vector
vec3 decode_tangent_normal(vec2 uv) {
    vec3 s = texture(u_normal_tex, uv).xyz;
    // DirectX Green is Y-down; invert to OpenGL Y-up (+Y)
    float nx = s.x * 2.0 - 1.0;
    float ny = 1.0 - s.y * 2.0;
    // Reconstruct Z if 2-channel (BC5/DXT5nm with B ~ 0)
    float nz;
    if (s.z > 0.05) {
        nz = s.z * 2.0 - 1.0;
    } else {
        float r2 = nx * nx + ny * ny;
        nz = sqrt(max(0.0, 1.0 - r2));
    }
    vec3 tn = vec3(nx, ny, nz);
    float len = length(tn);
    if (len < 1e-4 || isnan(len) || isinf(len)) {
        return vec3(0.0, 0.0, 1.0);
    }
    return tn / len;
}

// Microfacet GGX normal distribution function
float distribution_ggx(vec3 N, vec3 H, float roughness) {
    float a = roughness * roughness;
    float a2 = a * a;
    float NdotH = clamp(dot(N, H), 0.0, 1.0);
    float NdotH2 = NdotH * NdotH;
    float denom = (NdotH2 * (a2 - 1.0) + 1.0);
    return a2 / (PI * denom * denom + 1e-7);
}

// Smith GGX geometry shadowing
float geometry_schlick_ggx(float NdotV, float roughness) {
    float r = roughness + 1.0;
    float k = (r * r) / 8.0;
    return NdotV / (NdotV * (1.0 - k) + k + 1e-7);
}

float geometry_smith(vec3 N, vec3 V, vec3 L, float roughness) {
    float NdotV = clamp(dot(N, V), 0.0, 1.0);
    float NdotL = clamp(dot(N, L), 0.0, 1.0);
    return geometry_schlick_ggx(NdotV, roughness) * geometry_schlick_ggx(NdotL, roughness);
}

// Fresnel Schlick approximation
vec3 fresnel_schlick(float cos_theta, vec3 F0) {
    return F0 + (1.0 - F0) * pow(clamp(1.0 - cos_theta, 0.0, 1.0), 5.0);
}

// ACES film tonemapping (industry standard for glTF / PBR viewers)
vec3 aces_film(vec3 x) {
    float a = 2.51;
    float b = 0.03;
    float c = 2.43;
    float d = 0.59;
    float e = 0.14;
    return clamp((x * (a * x + b)) / (x * (c * x + d) + e), 0.0, 1.0);
}

void main() {
    vec3 geom_norm = normalize(v_world_norm);
    vec3 N = gl_FrontFacing ? geom_norm : -geom_norm;

    if (u_mode == 0 && u_has_normal_tex == 1 && u_normal_enabled == 1) {
        vec3 T = normalize(v_world_tangent);
        vec3 B = normalize(v_world_bitangent);
        // Gram-Schmidt orthogonalize T to face normal N
        T = normalize(T - dot(T, N) * N);
        // Gram-Schmidt orthogonalize B to N and T
        B = normalize(B - dot(B, N) * N - dot(B, T) * T);
        if (!gl_FrontFacing) {
            T = -T;
        }
        mat3 TBN = mat3(T, B, N);
        vec3 tn = decode_tangent_normal(v_uv);
        vec3 perturbed = normalize(TBN * tn);
        if (!isnan(perturbed.x) && !isinf(perturbed.x) && length(perturbed) > 0.5) {
            N = perturbed;
        }
    }

    vec3 V = normalize(u_cam_pos - v_world_pos);
    float NdotV = clamp(dot(N, V), 0.001, 1.0);

    // Determine material parameters based on viewport mode
    vec3 base_color;
    float roughness = clamp(u_roughness, 0.12, 1.0);
    float metallic = clamp(u_metallic, 0.0, 1.0);
    vec3 f0 = u_specular_f0;

    if (u_mode == 1) {
        // Clay studio mode (warm neutral buff tone, no textures)
        base_color = vec3(0.78, 0.74, 0.70);
        roughness = 0.75;
        metallic = 0.0;
        f0 = vec3(0.04);
    } else if (u_mode == 2) {
        // Wireframe underlying solid surface (neutral dark slate)
        base_color = vec3(0.22, 0.24, 0.27);
        roughness = 0.85;
        metallic = 0.0;
        f0 = vec3(0.04);
    } else if (u_mode == 3) {
        // Material IDs debug mode (flat distinct color per material slot)
        base_color = u_base_color.rgb;
        roughness = 0.8;
        metallic = 0.0;
        f0 = vec3(0.04);
    } else {
        // Mode 0: Textured / Standard
        vec4 tex_col = vec4(1.0);
        if (u_has_diffuse_tex == 1) {
            tex_col = texture(u_diffuse_tex, v_uv);
            if (u_alpha_mode == 1 && tex_col.a < u_alpha_cutoff) {
                discard;
            }
        }
        // Decode diffuse texture from sRGB to Linear space for physically correct lighting
        vec3 tex_linear = pow(tex_col.rgb, vec3(2.2));
        vec3 mat_linear = pow(u_base_color.rgb, vec3(2.2));
        base_color = tex_linear * mat_linear;
    }

    // Material ID mode: clean flat shaded with gentle directionality
    if (u_mode == 3) {
        vec3 L1 = normalize(vec3(0.5, 1.0, 0.8));
        float diff1 = max(dot(N, L1), 0.0);
        vec3 out_col = base_color * (0.35 + diff1 * 0.65);
        frag_color = vec4(out_col, 1.0);
        return;
    }

    // PBR Lighting setup
    vec3 F0 = mix(f0, base_color, metallic);
    vec3 albedo = base_color;

    // Broad 3-point neutral asset inspection lighting
    vec3 lights[3];
    lights[0] = normalize(vec3(0.5, 1.0, 0.8));    // Key light (warm high front-right)
    lights[1] = normalize(vec3(-0.8, 0.3, -0.6));  // Fill light (cool side left-rear)
    lights[2] = normalize(vec3(0.1, -0.4, -0.9));  // Rim light (soft lower-back)

    vec3 light_cols[3];
    light_cols[0] = vec3(1.0, 0.98, 0.95) * 1.05;
    light_cols[1] = vec3(0.92, 0.95, 1.0) * 0.45;
    light_cols[2] = vec3(0.95, 0.95, 0.95) * 0.30;

    vec3 direct_lighting = vec3(0.0);
    for (int i = 0; i < 3; ++i) {
        vec3 L = lights[i];
        vec3 H = normalize(V + L);
        float NdotL = clamp(dot(N, L), 0.0, 1.0);
        if (NdotL > 0.0) {
            float D = distribution_ggx(N, H, roughness);
            float G = geometry_smith(N, V, L, roughness);
            vec3 F = fresnel_schlick(clamp(dot(H, V), 0.0, 1.0), F0);

            float denom = max(4.0 * NdotV * NdotL, 0.001);
            vec3 spec = (D * G * F) / denom;
            vec3 kD = (vec3(1.0) - F) * (1.0 - metallic);
            vec3 diff = kD * albedo;

            direct_lighting += (diff + spec) * light_cols[i] * NdotL;
        }
    }

    // Hemispherical ambient environment (Studio sky + ground bounce)
    float hemi = clamp(N.y * 0.5 + 0.5, 0.0, 1.0);
    vec3 sky_amb = vec3(0.38, 0.40, 0.44);
    vec3 ground_amb = vec3(0.24, 0.22, 0.21);
    vec3 amb_env = mix(ground_amb, sky_amb, hemi);

    vec3 ambient_diff = (vec3(1.0) - F0) * (1.0 - metallic) * albedo * amb_env;
    vec3 ambient_spec = F0 * (0.08 * (1.0 - roughness * 0.5));
    vec3 ambient = ambient_diff + ambient_spec;

    vec3 final_linear = ambient + direct_lighting;

    // ACES Film Tonemapping + sRGB gamma encode
    vec3 mapped = aces_film(final_linear);
    vec3 final_srgb = pow(mapped, vec3(1.0 / 2.2));

    float out_alpha = 1.0;
    if (u_alpha_mode == 2) {
        float tex_a = (u_has_diffuse_tex == 1) ? texture(u_diffuse_tex, v_uv).a : 1.0;
        out_alpha = clamp(u_base_color.a * tex_a, 0.0, 1.0);
    }
    frag_color = vec4(final_srgb, out_alpha);
}
"""

LINE_VERTEX_SHADER = """#version 330 core
layout(location = 0) in vec3 a_pos;
layout(location = 1) in vec4 a_color;

uniform mat4 u_mvp;
uniform int u_use_uniform_color;
uniform vec4 u_color;

out vec4 v_color;

void main() {
    if (u_use_uniform_color == 1) {
        v_color = u_color;
    } else {
        v_color = a_color;
    }
    gl_Position = u_mvp * vec4(a_pos, 1.0);
}
"""

LINE_FRAGMENT_SHADER = """#version 330 core
in vec4 v_color;
out vec4 frag_color;

void main() {
    frag_color = v_color;
}
"""


class _GLMaterialBinding:
    def __init__(
        self,
        base_color: QVector4D,
        diffuse_tex_id: int = 0,
        normal_tex_id: int = 0,
        alpha_mode: int = 0,
        alpha_cutoff: float = 0.5,
        double_sided: bool = False,
        roughness: float = 0.65,
        metallic: float = 0.0,
        specular_f0: QVector3D = QVector3D(0.04, 0.04, 0.04),
        name: str = "",
        is_hidden: bool = False,
        is_proxy: bool = False,
        normal_semantic: str = "STANDARD_NORMAL",
    ):
        self.base_color = base_color
        self.diffuse_tex_id = diffuse_tex_id
        self.normal_tex_id = normal_tex_id
        self.alpha_mode = alpha_mode
        self.alpha_cutoff = alpha_cutoff
        self.double_sided = double_sided
        self.roughness = roughness
        self.metallic = metallic
        self.specular_f0 = specular_f0
        self.name = name
        self.is_hidden = is_hidden
        self.is_proxy = is_proxy
        self.normal_semantic = normal_semantic


class ModelViewport3D(QOpenGLWidget):
    dimensions_updated = Signal(float, float, float, int, int)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFocusPolicy(Qt.StrongFocus)

        # Camera state (Orbit around target)
        self.target = QVector3D(0.0, 0.0, 0.0)
        self.yaw = 35.0        # Azimuth angle (degrees)
        self.pitch = 22.0      # Elevation angle (degrees)
        self.distance = 2.5    # Distance from target (meters)
        self.fov = 45.0

        # Viewport toggles
        self.mode = 0          # 0 = Textured, 1 = Clay, 2 = Wireframe
        self.normal_enabled = True
        self.show_grid = True
        self.show_ground = True

        # Mouse tracking
        self._last_mouse_pos = QPoint()
        self._is_orbiting = False
        self._is_panning = False

        # Current loaded geometry
        self.geom: MeshGeometry | None = None
        self._buffers_dirty = False

        # OpenGL objects
        self.mesh_shader: QOpenGLShaderProgram | None = None
        self.line_shader: QOpenGLShaderProgram | None = None

        self.mesh_vao: QOpenGLVertexArrayObject | None = None
        self.wire_vao: QOpenGLVertexArrayObject | None = None
        self.vbo: QOpenGLBuffer | None = None
        self.ibo: QOpenGLBuffer | None = None
        self.wire_ibo: QOpenGLBuffer | None = None

        self.grid_vao: QOpenGLVertexArrayObject | None = None
        self.grid_vbo: QOpenGLBuffer | None = None
        self.ground_vao: QOpenGLVertexArrayObject | None = None
        self.ground_vbo: QOpenGLBuffer | None = None
        self.gizmo_vao: QOpenGLVertexArrayObject | None = None
        self.gizmo_vbo: QOpenGLBuffer | None = None

        self._mesh_indices_count = 0
        self._wire_indices_count = 0
        self._grid_lines_count = 0
        self._ground_lines_count = 0
        self._gizmo_lines_count = 0

        # Texture bindings
        self._gl_textures: list[int] = []
        self._material_bindings: list[_GLMaterialBinding] = []

    def set_geometry(self, geom: MeshGeometry | None) -> None:
        self.geom = geom
        if geom is not None:
            self.dimensions_updated.emit(
                float(geom.dim[0]),
                float(geom.dim[1]),
                float(geom.dim[2]),
                geom.triangles,
                geom.vertices,
            )
            self._log_diagnostics(geom)
            self.frame_camera()

        self._buffers_dirty = True
        if self.isValid():
            self.makeCurrent()
            self._sync_buffers()
            self.doneCurrent()
        self.update()

    def _log_diagnostics(self, geom: MeshGeometry) -> None:
        """Logs developer material diagnostics to console."""
        import logging
        logger = logging.getLogger("preview.viewport_3d")
        asset_label = getattr(geom, "asset_vpath", "") or "Current Asset"
        logger.info("================================================================================")
        logger.info("KCD2 VIEWPORT 3D PREVIEW - GEOMETRY & MATERIAL DIAGNOSTICS: %s", asset_label)
        logger.info("================================================================================")
        logger.info("Vertices: %s | Triangles: %s | Parts: %s | Materials: %s",
                    f"{geom.vertices:,}", f"{geom.triangles:,}", len(geom.parts), len(geom.materials))
        tan_status = "valid (VEC4)" if geom.tangents is not None else "missing"
        logger.info("Tangent basis: %s | UV coordinates: %s", tan_status, "valid" if geom.uvs is not None else "missing")
        for i, mat in enumerate(geom.materials):
            tris = sum(p.triangle_count for p in geom.parts if p.material_idx == i)
            logger.info("--------------------------------------------------------------------------------")
            logger.info("Material [%d]: %s (Shader: %s, Family: %s)", i, mat.name, mat.shader_type, mat.material_family)
            logger.info("  Roughness: %.2f | Metallic: %.2f | IOR: %.2f | Specular F0: (%.3f, %.3f, %.3f)",
                        mat.roughness, mat.metallic, mat.ior, mat.specular_f0[0], mat.specular_f0[1], mat.specular_f0[2])
            logger.info("  Normal Semantic: %s | Decoder: DirectX BC5 (+Y inv, Z recon)", mat.normal_semantic)
            logger.info("  Alpha Mode: %s (Cutoff: %.2f, 2-Sided: %s, Hidden: %s, Proxy: %s)",
                        mat.alpha_mode, mat.alpha_cutoff, mat.double_sided, mat.is_hidden, mat.is_proxy)
            logger.info("  Diffuse Texture: %s", f"{len(mat.diffuse_texture_bytes):,} bytes" if mat.diffuse_texture_bytes else "None")
            logger.info("  Normal Texture: %s", f"{len(mat.normal_texture_bytes):,} bytes" if mat.normal_texture_bytes else "None")
            logger.info("  Submesh Triangles: %s", f"{tris:,}")
            if mat.is_hidden or mat.fallback_reason:
                logger.warning(
                    "[FALLBACK MATERIAL]\nAsset:\n%s\n\nSubmaterial:\n%s\n\nShader:\n%s\n\nDiffuse:\n%s\n\nStatus:\n%s\n\nReason:\n%s",
                    asset_label,
                    mat.name,
                    mat.shader_type,
                    f"{len(mat.diffuse_texture_bytes):,} bytes" if mat.diffuse_texture_bytes else "None",
                    "FALLBACK / SUPPRESSED",
                    mat.fallback_reason or ("Secondary decal/overlay pass suppressed in visual preview" if mat.is_hidden else "Unclassified"),
                )
        logger.info("================================================================================")

    def toggle_normal(self, enabled: bool) -> None:
        """Toggles normal map contribution on/off."""
        self.normal_enabled = enabled
        self.update()

    def set_mode(self, mode: int) -> None:
        """0 = Textured, 1 = Clay, 2 = Wireframe."""
        self.mode = mode
        self.update()

    def toggle_grid(self, enabled: bool) -> None:
        self.show_grid = enabled
        self.update()

    def toggle_ground(self, enabled: bool) -> None:
        self.show_ground = enabled
        self.update()

    def set_camera_view(self, view_name: str) -> None:
        """Sets standard camera orientation presets."""
        views = {
            "front": (0.0, 0.0),
            "back": (180.0, 0.0),
            "left": (90.0, 0.0),
            "right": (-90.0, 0.0),
            "top": (0.0, 89.9),
            "bottom": (0.0, -89.9),
            "perspective": (35.0, 22.0),
        }
        if view_name in views:
            self.yaw, self.pitch = views[view_name]
            self.update()
        elif view_name == "frame":
            self.frame_camera()

    def frame_camera(self) -> None:
        """Frames the camera to focus on the model's bounding box."""
        if self.geom is None:
            self.target = QVector3D(0.0, 0.0, 0.0)
            self.distance = 2.5
        else:
            c = self.geom.center
            self.target = QVector3D(c[0], c[1], c[2])
            half_dim = self.geom.dim * 0.5
            radius = math.sqrt(np.sum(half_dim ** 2))
            self.distance = max(radius / math.sin(math.radians(self.fov * 0.5)) * 1.25, 0.3)
        self.update()

    def initializeGL(self) -> None:
        self.mesh_shader = QOpenGLShaderProgram(self)
        self.mesh_shader.addShaderFromSourceCode(QOpenGLShader.Vertex, VERTEX_SHADER_SRC)
        self.mesh_shader.addShaderFromSourceCode(QOpenGLShader.Fragment, FRAGMENT_SHADER_SRC)
        self.mesh_shader.link()

        self.line_shader = QOpenGLShaderProgram(self)
        self.line_shader.addShaderFromSourceCode(QOpenGLShader.Vertex, LINE_VERTEX_SHADER)
        self.line_shader.addShaderFromSourceCode(QOpenGLShader.Fragment, LINE_FRAGMENT_SHADER)
        self.line_shader.link()

        self._init_grid_buffers()
        self._init_gizmo_buffers()

        if self.geom is not None or self._buffers_dirty:
            self._sync_buffers()

    def _sync_buffers(self) -> None:
        self.update_mesh_buffers()
        self.update_ground_buffers()
        self._buffers_dirty = False

    def _init_grid_buffers(self) -> None:
        """Builds a real-world scale ground grid (major=1.0m, minor=0.1m)."""
        lines = []

        grid_size = 5.0  # 5 meters in each direction
        step_minor = 0.1 # 10 cm
        steps = int(grid_size / step_minor)

        col_axis_x = [0.85, 0.25, 0.25, 0.9]  # Red (+X)
        col_axis_z = [0.25, 0.45, 0.95, 0.9]  # Blue (+Z)
        col_major  = [0.38, 0.40, 0.44, 0.6]  # 1-meter major lines
        col_minor  = [0.22, 0.24, 0.26, 0.35] # 10-cm minor lines

        for i in range(-steps, steps + 1):
            coord = i * step_minor
            is_zero = (i == 0)
            is_major = (i % 10 == 0)

            c = col_axis_z if is_zero else (col_major if is_major else col_minor)
            lines.extend([coord, 0.0, -grid_size, *c])
            lines.extend([coord, 0.0, grid_size, *c])

            c = col_axis_x if is_zero else (col_major if is_major else col_minor)
            lines.extend([-grid_size, 0.0, coord, *c])
            lines.extend([grid_size, 0.0, coord, *c])

        grid_data = np.array(lines, dtype=np.float32)
        self._grid_lines_count = len(grid_data) // 7

        self.grid_vao = QOpenGLVertexArrayObject(self)
        self.grid_vao.create()
        self.grid_vao.bind()

        self.grid_vbo = QOpenGLBuffer(QOpenGLBuffer.VertexBuffer)
        self.grid_vbo.create()
        self.grid_vbo.bind()
        self.grid_vbo.allocate(grid_data.tobytes(), grid_data.nbytes)

        stride = 7 * 4
        GL.glEnableVertexAttribArray(0)
        GL.glVertexAttribPointer(0, 3, GL.GL_FLOAT, GL.GL_FALSE, stride, None)
        GL.glEnableVertexAttribArray(1)
        GL.glVertexAttribPointer(1, 4, GL.GL_FLOAT, GL.GL_FALSE, stride, GL.ctypes.c_void_p(3 * 4))

        self.grid_vao.release()

    def _init_gizmo_buffers(self) -> None:
        """Orientation Axis Gizmo (X=Red, Y=Green, Z=Blue)."""
        lines = [
            # X Axis (Red)
            0.0, 0.0, 0.0, 0.95, 0.2, 0.2, 1.0,
            1.0, 0.0, 0.0, 0.95, 0.2, 0.2, 1.0,
            # Y Axis (Green)
            0.0, 0.0, 0.0, 0.2, 0.95, 0.2, 1.0,
            0.0, 1.0, 0.0, 0.2, 0.95, 0.2, 1.0,
            # Z Axis (Blue)
            0.0, 0.0, 0.0, 0.2, 0.45, 0.95, 1.0,
            0.0, 0.0, 1.0, 0.2, 0.45, 0.95, 1.0,
        ]
        g_data = np.array(lines, dtype=np.float32)
        self._gizmo_lines_count = len(g_data) // 7

        self.gizmo_vao = QOpenGLVertexArrayObject(self)
        self.gizmo_vao.create()
        self.gizmo_vao.bind()

        self.gizmo_vbo = QOpenGLBuffer(QOpenGLBuffer.VertexBuffer)
        self.gizmo_vbo.create()
        self.gizmo_vbo.bind()
        self.gizmo_vbo.allocate(g_data.tobytes(), g_data.nbytes)

        stride = 7 * 4
        GL.glEnableVertexAttribArray(0)
        GL.glVertexAttribPointer(0, 3, GL.GL_FLOAT, GL.GL_FALSE, stride, None)
        GL.glEnableVertexAttribArray(1)
        GL.glVertexAttribPointer(1, 4, GL.GL_FLOAT, GL.GL_FALSE, stride, GL.ctypes.c_void_p(3 * 4))

        self.gizmo_vao.release()

    def update_ground_buffers(self) -> None:
        """Ground plane perimeter sitting at min height under the model."""
        ground_y = 0.0
        if self.geom is not None:
            ground_y = float(self.geom.bounds_min[1])

        lines = []
        c = [0.35, 0.38, 0.42, 0.5]
        extent = 3.0
        if self.geom is not None:
            extent = max(float(self.geom.dim[0]), float(self.geom.dim[2])) * 1.5

        p = [
            (-extent, ground_y, -extent),
            (extent, ground_y, -extent),
            (extent, ground_y, extent),
            (-extent, ground_y, extent),
        ]
        for i in range(4):
            p1 = p[i]
            p2 = p[(i + 1) % 4]
            lines.extend([*p1, *c])
            lines.extend([*p2, *c])

        g_data = np.array(lines, dtype=np.float32)
        self._ground_lines_count = len(g_data) // 7

        if self.ground_vao is None:
            self.ground_vao = QOpenGLVertexArrayObject(self)
            self.ground_vao.create()
        self.ground_vao.bind()

        if self.ground_vbo is None:
            self.ground_vbo = QOpenGLBuffer(QOpenGLBuffer.VertexBuffer)
            self.ground_vbo.create()
        self.ground_vbo.bind()
        self.ground_vbo.allocate(g_data.tobytes(), g_data.nbytes)

        stride = 7 * 4
        GL.glEnableVertexAttribArray(0)
        GL.glVertexAttribPointer(0, 3, GL.GL_FLOAT, GL.GL_FALSE, stride, None)
        GL.glEnableVertexAttribArray(1)
        GL.glVertexAttribPointer(1, 4, GL.GL_FLOAT, GL.GL_FALSE, stride, GL.ctypes.c_void_p(3 * 4))

        self.ground_vao.release()

    def _destroy_mesh_buffers(self) -> None:
        if self.mesh_vao is not None:
            self.mesh_vao.destroy()
            self.mesh_vao = None
        if self.wire_vao is not None:
            self.wire_vao.destroy()
            self.wire_vao = None
        if self.ibo is not None:
            self.ibo.destroy()
            self.ibo = None
        if self.wire_ibo is not None:
            self.wire_ibo.destroy()
            self.wire_ibo = None
        if self.vbo is not None:
            self.vbo.destroy()
            self.vbo = None

        if self._gl_textures:
            GL.glDeleteTextures(self._gl_textures)
            self._gl_textures = []
        self._material_bindings = []

    def _upload_texture(self, raw_bytes: bytes) -> int:
        """Loads PNG bytes into an OpenGL 2D texture with mipmapping."""
        qimg = QImage.fromData(raw_bytes)
        if qimg.isNull():
            return 0

        rgba_img = qimg.convertToFormat(QImage.Format.Format_RGBA8888)
        w = rgba_img.width()
        h = rgba_img.height()
        pixel_bytes = bytes(rgba_img.bits())

        tex_id = GL.glGenTextures(1)
        GL.glBindTexture(GL.GL_TEXTURE_2D, tex_id)
        GL.glTexParameteri(GL.GL_TEXTURE_2D, GL.GL_TEXTURE_WRAP_S, GL.GL_REPEAT)
        GL.glTexParameteri(GL.GL_TEXTURE_2D, GL.GL_TEXTURE_WRAP_T, GL.GL_REPEAT)
        GL.glTexParameteri(GL.GL_TEXTURE_2D, GL.GL_TEXTURE_MIN_FILTER, GL.GL_LINEAR_MIPMAP_LINEAR)
        GL.glTexParameteri(GL.GL_TEXTURE_2D, GL.GL_TEXTURE_MAG_FILTER, GL.GL_LINEAR)

        GL.glTexImage2D(
            GL.GL_TEXTURE_2D,
            0,
            GL.GL_RGBA,
            w,
            h,
            0,
            GL.GL_RGBA,
            GL.GL_UNSIGNED_BYTE,
            pixel_bytes,
        )
        GL.glGenerateMipmap(GL.GL_TEXTURE_2D)
        GL.glBindTexture(GL.GL_TEXTURE_2D, 0)
        return tex_id

    def update_mesh_buffers(self) -> None:
        self._destroy_mesh_buffers()

        if self.geom is None:
            self._mesh_indices_count = 0
            self._wire_indices_count = 0
            return

        for mat in self.geom.materials:
            diff_id = 0
            if mat.diffuse_texture_bytes:
                diff_id = self._upload_texture(mat.diffuse_texture_bytes)
                if diff_id:
                    self._gl_textures.append(diff_id)

            norm_id = 0
            if mat.normal_texture_bytes:
                norm_id = self._upload_texture(mat.normal_texture_bytes)
                if norm_id:
                    self._gl_textures.append(norm_id)

            alpha_m = 0
            if mat.alpha_mode == "MASK":
                alpha_m = 1
            elif mat.alpha_mode == "BLEND":
                alpha_m = 2

            b_col = QVector4D(*mat.base_color)
            f0_vec = QVector3D(*mat.specular_f0)
            self._material_bindings.append(
                _GLMaterialBinding(
                    base_color=b_col,
                    diffuse_tex_id=diff_id,
                    normal_tex_id=norm_id,
                    alpha_mode=alpha_m,
                    alpha_cutoff=mat.alpha_cutoff,
                    double_sided=mat.double_sided,
                    roughness=mat.roughness,
                    metallic=mat.metallic,
                    specular_f0=f0_vec,
                    name=mat.name,
                    is_hidden=mat.is_hidden,
                    is_proxy=mat.is_proxy,
                    normal_semantic=mat.normal_semantic,
                )
            )

        n_verts = self.geom.vertices
        vdata = np.zeros((n_verts, 12), dtype=np.float32)
        vdata[:, 0:3] = self.geom.positions
        vdata[:, 3:6] = self.geom.normals
        if self.geom.uvs is not None and len(self.geom.uvs) == n_verts:
            vdata[:, 6:8] = self.geom.uvs
        if self.geom.tangents is not None and len(self.geom.tangents) == n_verts:
            vdata[:, 8:12] = self.geom.tangents
        else:
            vdata[:, 8] = 1.0
            vdata[:, 11] = 1.0

        stride = 12 * 4  # 48 bytes

        self.vbo = QOpenGLBuffer(QOpenGLBuffer.VertexBuffer)
        self.vbo.create()
        self.vbo.bind()
        self.vbo.allocate(vdata.tobytes(), vdata.nbytes)
        self.vbo.release()

        ind = self.geom.indices.astype(np.uint32)
        self._mesh_indices_count = len(ind)

        self.mesh_vao = QOpenGLVertexArrayObject(self)
        self.mesh_vao.create()
        self.mesh_vao.bind()

        self.vbo.bind()
        GL.glEnableVertexAttribArray(0)
        GL.glVertexAttribPointer(0, 3, GL.GL_FLOAT, GL.GL_FALSE, stride, None)
        GL.glEnableVertexAttribArray(1)
        GL.glVertexAttribPointer(1, 3, GL.GL_FLOAT, GL.GL_FALSE, stride, GL.ctypes.c_void_p(3 * 4))
        GL.glEnableVertexAttribArray(2)
        GL.glVertexAttribPointer(2, 2, GL.GL_FLOAT, GL.GL_FALSE, stride, GL.ctypes.c_void_p(6 * 4))
        GL.glEnableVertexAttribArray(3)
        GL.glVertexAttribPointer(3, 4, GL.GL_FLOAT, GL.GL_FALSE, stride, GL.ctypes.c_void_p(8 * 4))

        self.ibo = QOpenGLBuffer(QOpenGLBuffer.IndexBuffer)
        self.ibo.create()
        self.ibo.bind()
        self.ibo.allocate(ind.tobytes(), ind.nbytes)

        self.mesh_vao.release()

        tris = ind.reshape(-1, 3)
        e0 = tris[:, [0, 1]]
        e1 = tris[:, [1, 2]]
        e2 = tris[:, [2, 0]]
        edges = np.vstack([e0, e1, e2]).reshape(-1)
        self._wire_indices_count = len(edges)

        self.wire_vao = QOpenGLVertexArrayObject(self)
        self.wire_vao.create()
        self.wire_vao.bind()

        self.vbo.bind()
        GL.glEnableVertexAttribArray(0)
        GL.glVertexAttribPointer(0, 3, GL.GL_FLOAT, GL.GL_FALSE, stride, None)

        self.wire_ibo = QOpenGLBuffer(QOpenGLBuffer.IndexBuffer)
        self.wire_ibo.create()
        self.wire_ibo.bind()
        self.wire_ibo.allocate(edges.tobytes(), edges.nbytes)

        self.wire_vao.release()

    def resizeGL(self, w: int, h: int) -> None:
        GL.glViewport(0, 0, w, h)

    def paintGL(self) -> None:
        if self._buffers_dirty:
            self._sync_buffers()

        w, h = self.width(), self.height()
        GL.glViewport(0, 0, w, h)

        GL.glClearColor(0.11, 0.12, 0.14, 1.0)
        GL.glClear(GL.GL_COLOR_BUFFER_BIT | GL.GL_DEPTH_BUFFER_BIT)
        GL.glEnable(GL.GL_DEPTH_TEST)
        GL.glEnable(GL.GL_CULL_FACE)
        GL.glCullFace(GL.GL_BACK)
        GL.glEnable(GL.GL_BLEND)
        GL.glBlendFunc(GL.GL_SRC_ALPHA, GL.GL_ONE_MINUS_SRC_ALPHA)

        # Calculate Camera Matrices
        aspect = w / max(h, 1)
        proj = QMatrix4x4()
        proj.perspective(self.fov, aspect, 0.05, 500.0)

        rad_pitch = math.radians(self.pitch)
        rad_yaw = math.radians(self.yaw)
        cam_x = self.target.x() + self.distance * math.cos(rad_pitch) * math.sin(rad_yaw)
        cam_y = self.target.y() + self.distance * math.sin(rad_pitch)
        cam_z = self.target.z() + self.distance * math.cos(rad_pitch) * math.cos(rad_yaw)
        cam_pos = QVector3D(cam_x, cam_y, cam_z)

        view = QMatrix4x4()
        view.lookAt(cam_pos, self.target, QVector3D(0.0, 1.0, 0.0))

        model = QMatrix4x4()
        mvp = proj * view * model

        if self.show_grid and self.grid_vao and self.line_shader:
            self.line_shader.bind()
            self.line_shader.setUniformValue("u_mvp", mvp)
            GL.glUniform1i(self.line_shader.uniformLocation("u_use_uniform_color"), 0)
            self.grid_vao.bind()
            GL.glDrawArrays(GL.GL_LINES, 0, self._grid_lines_count)
            self.grid_vao.release()
            self.line_shader.release()

        if self.show_ground and self.ground_vao and self.line_shader:
            self.line_shader.bind()
            self.line_shader.setUniformValue("u_mvp", mvp)
            GL.glUniform1i(self.line_shader.uniformLocation("u_use_uniform_color"), 0)
            self.ground_vao.bind()
            GL.glDrawArrays(GL.GL_LINES, 0, self._ground_lines_count)
            self.ground_vao.release()
            self.line_shader.release()

        if self.geom is not None and self.mesh_vao and self.mesh_shader and self._mesh_indices_count > 0:
            self.mesh_shader.bind()
            self.mesh_shader.setUniformValue("u_mvp", mvp)
            self.mesh_shader.setUniformValue("u_model", model)
            norm_mat = model.normalMatrix()
            self.mesh_shader.setUniformValue("u_norm_mat", norm_mat)
            self.mesh_shader.setUniformValue("u_cam_pos", cam_pos)
            GL.glUniform1i(self.mesh_shader.uniformLocation("u_mode"), int(self.mode))
            GL.glUniform1i(self.mesh_shader.uniformLocation("u_normal_enabled"), 1 if self.normal_enabled else 0)

            self.mesh_vao.bind()

            if self.mode in (1, 2) or not self.geom.parts:
                # Clay, or the solid pass under the wireframe
                self.mesh_shader.setUniformValue("u_base_color", QVector4D(0.82, 0.75, 0.65, 1.0))
                GL.glUniform1i(self.mesh_shader.uniformLocation("u_has_diffuse_tex"), 0)
                GL.glUniform1i(self.mesh_shader.uniformLocation("u_has_normal_tex"), 0)
                GL.glUniform1i(self.mesh_shader.uniformLocation("u_alpha_mode"), 0)
                GL.glUniform1f(self.mesh_shader.uniformLocation("u_alpha_cutoff"), 0.5)
                GL.glUniform1f(self.mesh_shader.uniformLocation("u_roughness"), 0.75 if self.mode == 1 else 0.85)
                GL.glUniform1f(self.mesh_shader.uniformLocation("u_metallic"), 0.0)
                self.mesh_shader.setUniformValue("u_specular_f0", QVector3D(0.04, 0.04, 0.04))
                GL.glDrawElements(GL.GL_TRIANGLES, self._mesh_indices_count, GL.GL_UNSIGNED_INT, ctypes.c_void_p(0))
            elif self.mode == 3:
                # Material ID view
                for part in self.geom.parts:
                    mat_binding = None
                    if 0 <= part.material_idx < len(self._material_bindings):
                        mat_binding = self._material_bindings[part.material_idx]
                    if mat_binding is not None and (mat_binding.is_hidden or mat_binding.is_proxy):
                        continue
                    dbg_color = DEBUG_MATERIAL_PALETTE[part.material_idx % len(DEBUG_MATERIAL_PALETTE)]
                    self.mesh_shader.setUniformValue("u_base_color", dbg_color)
                    GL.glUniform1i(self.mesh_shader.uniformLocation("u_has_diffuse_tex"), 0)
                    GL.glUniform1i(self.mesh_shader.uniformLocation("u_has_normal_tex"), 0)
                    GL.glUniform1i(self.mesh_shader.uniformLocation("u_alpha_mode"), 0)
                    GL.glUniform1f(self.mesh_shader.uniformLocation("u_alpha_cutoff"), 0.5)
                    GL.glUniform1f(self.mesh_shader.uniformLocation("u_roughness"), 0.8)
                    GL.glUniform1f(self.mesh_shader.uniformLocation("u_metallic"), 0.0)
                    self.mesh_shader.setUniformValue("u_specular_f0", QVector3D(0.04, 0.04, 0.04))
                    byte_offset = part.index_start * 4
                    GL.glDrawElements(
                        GL.GL_TRIANGLES,
                        part.index_count,
                        GL.GL_UNSIGNED_INT,
                        ctypes.c_void_p(byte_offset),
                    )
            else:
                # Textured
                for part in self.geom.parts:
                    mat_binding = None
                    if 0 <= part.material_idx < len(self._material_bindings):
                        mat_binding = self._material_bindings[part.material_idx]

                    if mat_binding is not None:
                        if mat_binding.is_hidden or mat_binding.is_proxy:
                            continue

                        self.mesh_shader.setUniformValue("u_base_color", mat_binding.base_color)
                        GL.glUniform1f(self.mesh_shader.uniformLocation("u_roughness"), mat_binding.roughness)
                        GL.glUniform1f(self.mesh_shader.uniformLocation("u_metallic"), mat_binding.metallic)
                        self.mesh_shader.setUniformValue("u_specular_f0", mat_binding.specular_f0)

                        if mat_binding.diffuse_tex_id > 0:
                            GL.glActiveTexture(GL.GL_TEXTURE0)
                            GL.glBindTexture(GL.GL_TEXTURE_2D, mat_binding.diffuse_tex_id)
                            GL.glUniform1i(self.mesh_shader.uniformLocation("u_diffuse_tex"), 0)
                            GL.glUniform1i(self.mesh_shader.uniformLocation("u_has_diffuse_tex"), 1)
                        else:
                            GL.glUniform1i(self.mesh_shader.uniformLocation("u_has_diffuse_tex"), 0)

                        if mat_binding.normal_tex_id > 0 and mat_binding.normal_semantic != "NO_NORMAL":
                            GL.glActiveTexture(GL.GL_TEXTURE1)
                            GL.glBindTexture(GL.GL_TEXTURE_2D, mat_binding.normal_tex_id)
                            GL.glUniform1i(self.mesh_shader.uniformLocation("u_normal_tex"), 1)
                            GL.glUniform1i(self.mesh_shader.uniformLocation("u_has_normal_tex"), 1)
                        else:
                            GL.glUniform1i(self.mesh_shader.uniformLocation("u_has_normal_tex"), 0)

                        GL.glUniform1i(self.mesh_shader.uniformLocation("u_alpha_mode"), mat_binding.alpha_mode)
                        GL.glUniform1f(self.mesh_shader.uniformLocation("u_alpha_cutoff"), mat_binding.alpha_cutoff)

                        if mat_binding.double_sided:
                            GL.glDisable(GL.GL_CULL_FACE)
                        else:
                            GL.glEnable(GL.GL_CULL_FACE)
                    else:
                        self.mesh_shader.setUniformValue("u_base_color", QVector4D(0.82, 0.75, 0.65, 1.0))
                        GL.glUniform1i(self.mesh_shader.uniformLocation("u_has_diffuse_tex"), 0)
                        GL.glUniform1i(self.mesh_shader.uniformLocation("u_has_normal_tex"), 0)
                        GL.glUniform1i(self.mesh_shader.uniformLocation("u_alpha_mode"), 0)
                        GL.glUniform1f(self.mesh_shader.uniformLocation("u_alpha_cutoff"), 0.5)
                        GL.glUniform1f(self.mesh_shader.uniformLocation("u_roughness"), 0.65)
                        GL.glUniform1f(self.mesh_shader.uniformLocation("u_metallic"), 0.0)
                        self.mesh_shader.setUniformValue("u_specular_f0", QVector3D(0.04, 0.04, 0.04))
                        GL.glEnable(GL.GL_CULL_FACE)

                    byte_offset = part.index_start * 4
                    GL.glDrawElements(
                        GL.GL_TRIANGLES,
                        part.index_count,
                        GL.GL_UNSIGNED_INT,
                        ctypes.c_void_p(byte_offset),
                    )

                GL.glEnable(GL.GL_CULL_FACE)

            self.mesh_vao.release()
            self.mesh_shader.release()

            if self.mode == 2 and self.wire_vao and self.line_shader:
                self.line_shader.bind()
                self.line_shader.setUniformValue("u_mvp", mvp)
                GL.glUniform1i(self.line_shader.uniformLocation("u_use_uniform_color"), 1)
                # Clean, consistent neutral light-slate topology color
                self.line_shader.setUniformValue("u_color", QVector4D(0.80, 0.84, 0.90, 0.95))
                self.wire_vao.bind()

                GL.glEnable(GL.GL_POLYGON_OFFSET_LINE)
                GL.glPolygonOffset(-1.0, -1.0)
                GL.glDepthFunc(GL.GL_LEQUAL)
                GL.glDisable(GL.GL_CULL_FACE)
                GL.glDrawElements(GL.GL_LINES, self._wire_indices_count, GL.GL_UNSIGNED_INT, ctypes.c_void_p(0))
                GL.glEnable(GL.GL_CULL_FACE)
                GL.glDepthFunc(GL.GL_LESS)
                GL.glDisable(GL.GL_POLYGON_OFFSET_LINE)

                self.wire_vao.release()
                self.line_shader.release()

        if self.gizmo_vao and self.line_shader:
            gizmo_size = 90
            GL.glViewport(10, 10, gizmo_size, gizmo_size)
            GL.glClear(GL.GL_DEPTH_BUFFER_BIT)

            gizmo_proj = QMatrix4x4()
            gizmo_proj.ortho(-1.5, 1.5, -1.5, 1.5, -5.0, 5.0)

            gizmo_cam = QVector3D(
                math.cos(rad_pitch) * math.sin(rad_yaw),
                math.sin(rad_pitch),
                math.cos(rad_pitch) * math.cos(rad_yaw),
            )
            gizmo_view = QMatrix4x4()
            gizmo_view.lookAt(gizmo_cam * 2.0, QVector3D(0, 0, 0), QVector3D(0, 1, 0))

            gizmo_mvp = gizmo_proj * gizmo_view

            self.line_shader.bind()
            self.line_shader.setUniformValue("u_mvp", gizmo_mvp)
            GL.glUniform1i(self.line_shader.uniformLocation("u_use_uniform_color"), 0)
            self.gizmo_vao.bind()
            GL.glLineWidth(2.5)
            GL.glDrawArrays(GL.GL_LINES, 0, self._gizmo_lines_count)
            GL.glLineWidth(1.0)
            self.gizmo_vao.release()
            self.line_shader.release()

            # Reset viewport back to full window
            GL.glViewport(0, 0, w, h)

    def mousePressEvent(self, event: QMouseEvent) -> None:
        self._last_mouse_pos = event.pos()
        if event.button() == Qt.LeftButton:
            self._is_orbiting = True
        elif event.button() in (Qt.RightButton, Qt.MiddleButton):
            self._is_panning = True

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:
        if event.button() == Qt.LeftButton:
            self._is_orbiting = False
        elif event.button() in (Qt.RightButton, Qt.MiddleButton):
            self._is_panning = False

    def mouseMoveEvent(self, event: QMouseEvent) -> None:
        delta = event.pos() - self._last_mouse_pos
        self._last_mouse_pos = event.pos()

        if self._is_orbiting:
            self.yaw += delta.x() * 0.4
            self.pitch -= delta.y() * 0.4
            self.pitch = max(min(self.pitch, 89.9), -89.9)
            self.update()
        elif self._is_panning:
            factor = self.distance * 0.0015
            rad_pitch = math.radians(self.pitch)
            rad_yaw = math.radians(self.yaw)

            right = QVector3D(math.cos(rad_yaw), 0, -math.sin(rad_yaw))
            up = QVector3D(
                -math.sin(rad_pitch) * math.sin(rad_yaw),
                math.cos(rad_pitch),
                -math.sin(rad_pitch) * math.cos(rad_yaw),
            )

            pan = (-right * delta.x() + up * delta.y()) * factor
            self.target += pan
            self.update()

    def wheelEvent(self, event: QWheelEvent) -> None:
        delta = event.angleDelta().y()
        factor = 0.9 if delta > 0 else 1.1
        self.distance = max(min(self.distance * factor, 150.0), 0.05)
        self.update()
