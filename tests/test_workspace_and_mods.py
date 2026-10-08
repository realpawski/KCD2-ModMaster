"""Tests for WorkspaceAsset model, ModProject system, and Asset Registry."""
from __future__ import annotations

import json
import shutil
import tempfile
from pathlib import Path

import pytest

from mods.project import ModManager, ModProject, slugify_mod_id
from mods.registry import generate_modmaster_registry
from workspace.asset_model import (
    AssetStatus,
    AssetType,
    WorkspaceAsset,
    list_workspace_assets,
    validate_workspace_asset,
)


@pytest.fixture
def temp_workspace(tmp_path: Path):
    ws = tmp_path / "Workspace"
    ws.mkdir()
    return ws


def test_workspace_asset_lifecycle(temp_workspace: Path):
    asset_dir = temp_workspace / "Assets" / "test_barrel"
    meta_dir = asset_dir / "metadata"
    meta_dir.mkdir(parents=True)

    asset = WorkspaceAsset(
        asset_id="test_barrel",
        name="Test Barrel",
        asset_type=AssetType.STATIC_PROP.value,
        workspace_dir=str(asset_dir),
        status=AssetStatus.EDITING.value,
    )
    asset.save()

    meta_file = meta_dir / ".modmaster_asset.json"
    assert meta_file.is_file()

    loaded = WorkspaceAsset.load(meta_file)
    assert loaded is not None
    assert loaded.asset_id == "test_barrel"
    assert loaded.name == "Test Barrel"
    assert loaded.asset_type == AssetType.STATIC_PROP.value
    assert loaded.status == AssetStatus.EDITING.value

    report = validate_workspace_asset(loaded)
    assert report is not None
    assert loaded.status in (AssetStatus.EDITING.value, AssetStatus.WARNING.value)

    all_assets = list_workspace_assets(temp_workspace)
    assert len(all_assets) == 1
    assert all_assets[0].asset_id == "test_barrel"


def test_mod_project_and_assignment(temp_workspace: Path):
    mgr = ModManager(temp_workspace)
    mod = mgr.create_mod(
        name="PAWSKI Test Mod",
        mod_id="pawski_test_mod",
        author="PAWSKI",
        version="0.1.0",
        description="A testing mod for custom props.",
    )

    assert mod.id == "pawski_test_mod"
    assert Path(mod.project_dir).is_dir()
    assert (Path(mod.project_dir) / "modmaster.json").is_file()

    mod.assign_asset("test_barrel")
    assert "test_barrel" in mod.assets

    loaded_mod = mgr.get_mod("pawski_test_mod")
    assert loaded_mod is not None
    assert "test_barrel" in loaded_mod.assets

    from runtime_tools.packaging import mod_id as packaged_mod_id
    assert slugify_mod_id("My Awesome Mod! 123") == "my_awesome_mod"
    assert packaged_mod_id(slugify_mod_id("2nd-Edition Swords")) == "nd_edition_swords"


def test_asset_registry_generation(temp_workspace: Path):
    asset_dir = temp_workspace / "Assets" / "barrel"
    asset_dir.mkdir(parents=True)
    asset = WorkspaceAsset(
        asset_id="barrel",
        name="Barrel",
        asset_type=AssetType.STATIC_PROP.value,
        workspace_dir=str(asset_dir),
        status=AssetStatus.READY.value,
    )
    asset.save()

    mgr = ModManager(temp_workspace)
    mod = mgr.create_mod("My Test Mod", "my_test_mod")
    mod.assign_asset("barrel")

    reg = generate_modmaster_registry(temp_workspace)
    assert "mods" in reg
    assert len(reg["mods"]) == 1
    assert reg["mods"][0]["id"] == "my_test_mod"
    assert len(reg["mods"][0]["assets"]) == 1
    assert reg["mods"][0]["assets"][0]["id"] == "barrel"

    reg_file = temp_workspace / "Mods" / "modmaster_registry.json"
    assert reg_file.is_file()
