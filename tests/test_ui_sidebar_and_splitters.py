"""Unit tests for Sidebar compact mode, tooltips, and BrowserPage splitter constraints."""
from __future__ import annotations

import sys
from pathlib import Path
import pytest
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication

from core.config import Settings
from ui.context import AppContext
from ui.sidebar import SidebarWidget, WIDTH_EXPANDED, WIDTH_COMPACT
from ui.pages.browser import BrowserPage


@pytest.fixture(scope="session")
def qapp():
    app = QApplication.instance()
    if app is None:
        app = QApplication(sys.argv)
    return app


def test_sidebar_compact_mode_and_tooltips(qapp, tmp_path: Path):
    s = Settings.load(tmp_path / "config.json")
    ctx = AppContext(s)
    sb = SidebarWidget(ctx)

    assert sb.is_compact() is False
    assert sb.width() == WIDTH_EXPANDED
    assert sb.item_map["home"].text().strip() == "Home"
    assert sb.item_map["home"].toolTip() == "Home"

    sb.set_compact(True)
    assert sb.is_compact() is True
    assert sb.width() == WIDTH_COMPACT
    assert sb.item_map["home"].text() == ""
    assert sb.item_map["home"].toolTip() == "Home"
    assert sb.item_map["weapons"].toolTip() == "Weapons"
    assert sb.item_map["buildings"].toolTip() == "Houses & Buildings"

    sb.set_compact(False)
    assert sb.is_compact() is False
    assert sb.width() == WIDTH_EXPANDED
    assert sb.item_map["home"].text().strip() == "Home"


def test_browser_page_splitter_constraints(qapp, tmp_path: Path):
    s = Settings.load(tmp_path / "config.json")
    ctx = AppContext(s)
    bp = BrowserPage(ctx)

    assert bp.left_pane.minimumWidth() >= 300
    assert bp.preview_container.minimumWidth() >= 360
    assert bp.inspector_pane.minimumWidth() >= 280

    bp.resize(1600, 900)
    bp.show()
    qapp.processEvents()

    sizes = bp.splitter.sizes()
    assert len(sizes) == 3
    assert sizes[0] >= 300
    assert sizes[2] >= 280
    bp.close()


def test_your_work_comes_before_the_game_files_and_only_your_own_collapse_is_kept(qapp, tmp_path: Path):
    from ui.sidebar import NAV_ITEMS

    keys = [key for key, *_ in NAV_ITEMS]
    assert keys.index("mods") < keys.index("browser") and keys.index("my_assets") < keys.index("browser")
    sb = SidebarWidget(AppContext(Settings.load(tmp_path / "config.json")))
    remembered = []
    sb.compact_toggled.connect(remembered.append)
    sb.set_compact(True)  # the app collapsing it on its own
    sb.set_compact(False)
    sb.set_compact(True, manual=True)
    assert remembered == [True]


def test_mod_list_names_the_contents_instead_of_repeating_the_name(qapp):
    from types import SimpleNamespace
    from ui.pages.mods import ModListEntry

    from PySide6.QtWidgets import QLabel
    boar = ModListEntry(SimpleNamespace(id="raincoat_boar", name="Raincoat_Boar", version="0.1.2"), 0, 1)
    assert boar.findChildren(QLabel)[1].text() == "v0.1.2  ·  1 creature"
    renamed = ModListEntry(SimpleNamespace(id="old_id", name="New Name", version="1.0.0"), 0, 0)
    assert renamed.findChildren(QLabel)[1].text() == "old_id  ·  v1.0.0  ·  Empty"
