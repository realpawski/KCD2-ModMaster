"""Unit tests for Houses & Buildings asset classification, index migration, and navigation."""
from __future__ import annotations

import sqlite3
import sys
from pathlib import Path
import pytest
from PySide6.QtWidgets import QApplication

from core.config import Settings
from database.index import AssetIndex
from kcd2.formats import ASSET_CLASSES, asset_class
from ui.context import AppContext
from ui.pages.browser import BrowserPage
from ui.sidebar import NAV_ITEMS, SidebarWidget


@pytest.fixture(scope="session")
def qapp():
    app = QApplication.instance()
    if app is None:
        app = QApplication(sys.argv)
    return app


def test_building_asset_classes_and_heuristics():
    assert "Buildings" in ASSET_CLASSES

    assert asset_class("objects/manmade/structures/living/houses/cv_house_1s_2r_a_001.cgf") == "Buildings"
    assert asset_class("objects/manmade/structures/living/houses/unique/rathaus.cgf") == "Buildings"
    assert asset_class("objects/manmade/structures/living/tents/tent_large.cgf") == "Buildings"

    assert asset_class("objects/manmade/structures/defensive/castles/tower_a.cgf") == "Buildings"
    assert asset_class("objects/manmade/structures/defensive/fortresses/gatehouse.cgf") == "Buildings"
    assert asset_class("objects/manmade/structures/defensive/walls/palisade.cgf") == "Buildings"

    assert asset_class("objects/manmade/structures/industrial/smithery/forge.cgf") == "Buildings"
    assert asset_class("objects/manmade/structures/industrial/barns/barn_large.cgf") == "Buildings"
    assert asset_class("objects/manmade/structures/theological/monasteries/church_main.cgf") == "Buildings"

    assert asset_class("hlods/structures/trotsky_castle_hlod.cgf") == "Buildings"

    assert asset_class("objects/manmade/common_furniture/chair.cgf") == "Props"
    assert asset_class("objects/manmade/weapons/swords/sword.cgf") == "Weapons"
    assert asset_class("objects/characters/humans/cloth/shirt.cgf") == "Characters"


def test_asset_index_buildings_migration(tmp_path: Path):
    db_file = tmp_path / "test_migration.sqlite"
    idx = AssetIndex(db_file)

    aid = idx.replace_archive("C:/fake/Objects.pak", "Objects.pak", "Data", 1000, 123456.0)
    idx.conn.execute(
        "INSERT INTO assets(archive_id, vpath, vpath_lower, filename, ext, category, asset_class, size, csize, is_part) "
        "VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (aid, "Objects/manmade/structures/living/houses/house_01.cgf",
         "objects/manmade/structures/living/houses/house_01.cgf",
         "house_01.cgf", "cgf", "CGF", "Props", 5000, 2000, 0)
    )
    idx.conn.execute("DELETE FROM meta WHERE key='buildings_migrated'")
    idx.conn.commit()

    rows, _ = idx.search("house_01", asset_class="Props")
    assert len(rows) == 1
    rows, _ = idx.search("house_01", asset_class="Buildings")
    assert len(rows) == 0

    idx._migrate()

    rows, _ = idx.search("house_01", asset_class="Buildings")
    assert len(rows) == 1
    assert rows[0].asset_class == "Buildings"
    assert rows[0].filename == "house_01.cgf"


def test_sidebar_and_browser_buildings_integration(qapp, tmp_path: Path):
    keys = [item[0] for item in NAV_ITEMS]
    assert "buildings" in keys

    buildings_nav = next(item for item in NAV_ITEMS if item[0] == "buildings")
    assert buildings_nav[1] == "Houses & Buildings"
    assert buildings_nav[2] == "building"
    assert buildings_nav[3]["asset_class"] == "Buildings"

    cfg_file = tmp_path / "config.json"
    settings = Settings.load(cfg_file)
    ctx = AppContext(settings)
    bp = BrowserPage(ctx)

    bp.apply_options({"asset_class": "Buildings", "title": "Houses & Buildings"})
    assert bp.class_cb.currentData() == "Buildings"
    assert bp.h1.text() == "Houses & Buildings"
