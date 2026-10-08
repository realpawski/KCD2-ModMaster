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
