"""Regression tests for Generic KCD2 Material Pipeline and UI Window Management."""
from __future__ import annotations

import sys
from pathlib import Path
import numpy as np
import pytest

from materials.mtl_parser import parse_mtl_xml, SubMaterialInfo, MTLDefinition
from materials.semantics import (
    classify_kcd2_material,
    KCD2MaterialDescription,
    MaterialFamily,
    NormalSemantic,
    linearize_srgb,
)
from preview.gltf_loader import load_glb, MeshGeometry, MaterialInfo


def test_linearize_srgb():
    lin = linearize_srgb(0.238)
    assert 0.038 <= lin <= 0.045
    assert linearize_srgb(0.0) == 0.0
    assert linearize_srgb(1.0) == 1.0


def test_boar_materials_classification():
    xml = """
    <Material MtlFlags="524544">
        <SubMaterials>
            <SubMaterial Name="boar" Shader="Illum" StringGenMask="%NORMAL_MAP%SUBSURFACE_SCATTERING" SurfaceType="mat_meat" Diffuse="0.8,0.8,0.8" Specular="0.2,0.2,0.2" Shininess="10">
                <Textures>
                    <Texture Map="Diffuse" File="textures/animals/boar/boar_diff.dds"/>
                    <Texture Map="Bumpmap" File="textures/animals/boar/boar_ddna.dds"/>
                </Textures>
            </SubMaterial>
            <SubMaterial Name="boar_hair" Shader="Hair" StringGenMask="%HAIR%NORMAL_MAP" SurfaceType="mat_fur" AlphaTest="0.4" MtlFlags="526466" Diffuse="0.5,0.4,0.3" Specular="0.2,0.2,0.2">
                <Textures>
                    <Texture Map="Diffuse" File="textures/animals/boar/hair_diff.dds"/>
                    <Texture Map="Bumpmap" File="textures/animals/boar/hair_ddna.dds"/>
                </Textures>
            </SubMaterial>
            <SubMaterial Name="boar_eye" Shader="Eye" SurfaceType="mat_flesh" Diffuse="0.1,0.1,0.1" Specular="0.3,0.3,0.3">
                <PublicParams CorneaSmoothness="0.85"/>
            </SubMaterial>
        </SubMaterials>
    </Material>
    """
    mtl = parse_mtl_xml(xml)
    assert len(mtl.submaterials) == 3

    desc0 = classify_kcd2_material(mtl.submaterials[0])
    assert desc0.metallic == 0.0
    assert desc0.material_family in (MaterialFamily.ORGANIC_DIELECTRIC, MaterialFamily.STANDARD_PBR)
    assert 0.02 <= desc0.specular_f0[0] <= 0.05
    assert desc0.normal_semantic == NormalSemantic.KCD2_DDNA
    assert not desc0.is_hidden

    desc1 = classify_kcd2_material(mtl.submaterials[1])
    assert desc1.metallic == 0.0
    assert desc1.material_family == MaterialFamily.HAIR_FUR
    assert desc1.double_sided is True
    assert desc1.alpha_mode == "MASK"
    assert desc1.alpha_cutoff == 0.4

    desc2 = classify_kcd2_material(mtl.submaterials[2])
    assert desc2.metallic == 0.0
    assert desc2.material_family == MaterialFamily.EYE
    assert desc2.roughness < 0.25  # Smooth cornea


def test_polearm_pile_classification_not_dark():
    """polearm_pile_a must preserve dielectric wood shafts with 0 metallic and full diffuse reflectance."""
    xml = """
    <Material MtlFlags="524544">
        <SubMaterials>
            <SubMaterial Name="wood_shaft" Shader="Illum" SurfaceType="mat_wood" Diffuse="0.55,0.42,0.28" Specular="0.238,0.238,0.238" Shininess="12">
                <Textures>
                    <Texture Map="Diffuse" File="textures/props/weapons/polearm_pile_diff.dds"/>
                    <Texture Map="Bumpmap" File="textures/props/weapons/polearm_pile_ddna.dds"/>
                </Textures>
            </SubMaterial>
            <SubMaterial Name="metal_head" Shader="Illum" SurfaceType="mat_metal" Diffuse="0.2,0.2,0.2" Specular="0.75,0.75,0.75" Shininess="40">
                <Textures>
                    <Texture Map="Diffuse" File="textures/props/weapons/polearm_pile_diff.dds"/>
                    <Texture Map="Bumpmap" File="textures/props/weapons/polearm_pile_ddna.dds"/>
                    <Texture Map="Specular" File="textures/props/weapons/polearm_pile_spec.dds"/>
                </Textures>
            </SubMaterial>
            <SubMaterial Name="rope_binding" Shader="Illum" SurfaceType="mat_fabric" Diffuse="0.4,0.35,0.25" Specular="0.2,0.2,0.2" Shininess="8">
                <Textures>
                    <Texture Map="Diffuse" File="textures/props/weapons/polearm_pile_diff.dds"/>
                </Textures>
            </SubMaterial>
        </SubMaterials>
    </Material>
    """
    mtl = parse_mtl_xml(xml)

    wood = classify_kcd2_material(mtl.submaterials[0])
    assert wood.metallic == 0.0
    assert 0.03 <= wood.specular_f0[0] <= 0.05
    assert wood.material_family == MaterialFamily.STANDARD_PBR

    metal = classify_kcd2_material(mtl.submaterials[1])
    assert metal.metallic > 0.6
    assert metal.specular_f0[0] > 0.5

    rope = classify_kcd2_material(mtl.submaterials[2])
    assert rope.metallic == 0.0
    assert rope.specular_f0[0] < 0.05


def test_wolf_materials_and_purple_suppression():
    """wolf.cgf must suppress the purple eye_overlay secondary AO decal pass and treat body as organic."""
    xml = """
    <Material MtlFlags="524544">
        <SubMaterials>
            <SubMaterial Name="body" Shader="Illum" StringGenMask="%NORMAL_MAP%SUBSURFACE_SCATTERING" SurfaceType="mat_fur" Diffuse="0.8,0.8,0.8" Specular="1,1,1" Shininess="10">
                <Textures>
                    <Texture Map="Diffuse" File="textures/animals/wolf/wolf_diff.dds"/>
                    <Texture Map="Bumpmap" File="textures/animals/wolf/wolf_ddna.dds"/>
                </Textures>
            </SubMaterial>
            <SubMaterial Name="wolf_fur" Shader="Hair" StringGenMask="%HAIR%NORMAL_MAP" SurfaceType="mat_fur" AlphaTest="0.5" MtlFlags="526466" Diffuse="0.8,0.8,0.8" Specular="0.2,0.2,0.2">
                <Textures>
                    <Texture Map="Diffuse" File="textures/animals/wolf/wolf_fur_diff.dds"/>
                    <Texture Map="Bumpmap" File="textures/animals/wolf/wolf_fur_ddna.dds"/>
                </Textures>
            </SubMaterial>
            <SubMaterial Name="eye_overlay" Shader="Eye" StringGenMask="%EYE_AO_OVERLAY%" SurfaceType="mat_flesh" Diffuse="0.2704978,0.02732089,0.2961383" HideMask="0">
                <Textures/>
            </SubMaterial>
            <SubMaterial Name="eye" Shader="Eye" SurfaceType="mat_flesh" Diffuse="0.1,0.1,0.1" Specular="0.3,0.3,0.3">
                <PublicParams CorneaSmoothness="0.88"/>
            </SubMaterial>
        </SubMaterials>
    </Material>
    """
    mtl = parse_mtl_xml(xml)

    body = classify_kcd2_material(mtl.submaterials[0])
    assert body.metallic == 0.0
    assert body.material_family == MaterialFamily.ORGANIC_DIELECTRIC

    fur = classify_kcd2_material(mtl.submaterials[1])
    assert fur.double_sided is True
    assert fur.alpha_mode == "MASK"
    assert fur.alpha_cutoff == 0.5

    overlay = classify_kcd2_material(mtl.submaterials[2])
    assert overlay.is_hidden is True
    assert "EYE_AO_OVERLAY" in overlay.fallback_reason or "overlay" in overlay.name.lower()

    eye = classify_kcd2_material(mtl.submaterials[3])
    assert eye.is_hidden is False
    assert eye.metallic == 0.0


def test_ui_no_extra_top_level_windows():
    """Verify that PreviewContainer does not create unparented top-level buttons or extra windows."""
    from PySide6.QtWidgets import QApplication
    from ui.preview.container import PreviewContainer
    from ui.context import AppContext
    from core.config import Settings
    from database.index import AssetRow

    app = QApplication.instance()
    if app is None:
        app = QApplication([])

    initial_top_levels = len([w for w in QApplication.topLevelWidgets() if w.isVisible()])

    ctx = AppContext(settings=Settings.load())
    container = PreviewContainer(ctx)

    assert not hasattr(container, "btn_create_copy")
    assert not hasattr(container, "btn_open_blender")

    row_3d = AssetRow(
        id=1,
        vpath="Objects/characters/animals/boar/boar.cgf",
        filename="boar.cgf",
        ext="cgf",
        category="Objects",
        asset_class="Model",
        size=100000,
        csize=50000,
        is_part=False,
        archive_id=1,
        archive_name="Characters.pak",
        archive_path="Characters.pak",
    )

    container.set_asset(row_3d)

    current_top_levels = len([w for w in QApplication.topLevelWidgets() if w.isVisible()])
    assert current_top_levels == initial_top_levels
