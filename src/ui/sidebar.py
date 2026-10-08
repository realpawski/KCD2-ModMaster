"""Left navigation with grouped sections and an optional compact mode."""
from __future__ import annotations

from PySide6.QtCore import QSize, Qt, Signal
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from app.version import display_version
from ui import theme
from ui.context import AppContext
from ui.icons import get_svg_icon

# (key, label, icon, navigation options); a None key starts a section.
NAV_ITEMS = [
    ("home", "Home", "home", {}),
    (None, "Game files", "", {}),
    ("browser", "Asset Browser", "search", {}),
    ("weapons", "Weapons", "weapon", {"asset_class": "Weapons", "title": "Weapons"}),
    ("armor", "Armor", "armor", {"asset_class": "Armor", "title": "Armor"}),
    ("characters", "Characters", "character", {"asset_class": "Characters", "title": "Characters"}),
    ("buildings", "Houses & Buildings", "building", {"asset_class": "Buildings", "title": "Houses & Buildings"}),
    ("props", "Props", "cube", {"asset_class": "Props", "title": "Props"}),
    ("materials", "Materials", "material", {"type": "MTL", "title": "Materials"}),
    ("textures", "Textures", "photo", {"type": "Textures", "title": "Textures"}),
    (None, "Create", "", {}),
    ("mods", "Mods", "puzzle", {}),
    ("my_assets", "Workspace Assets", "folder", {}),
]

WIDTH_EXPANDED = 236
WIDTH_COMPACT = 64


class SidebarWidget(QFrame):
    page_selected = Signal(str, dict)
    compact_toggled = Signal(bool)

    def __init__(self, ctx: AppContext, parent=None):
        super().__init__(parent)
        self.ctx = ctx
        self.setObjectName("Sidebar")
        self._is_compact = False
        self._manual_override = False
        self.item_map: dict[str, QListWidgetItem] = {}
        self._labels: dict[str, str] = {}
        self._sections: list[QListWidgetItem] = []
        self.setFixedWidth(WIDTH_EXPANDED)

        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 12)
        lay.setSpacing(0)

        header = QWidget()
        h = QHBoxLayout(header)
        h.setContentsMargins(18, 18, 10, 14)
        h.setSpacing(10)
        self.logo = QLabel()
        self.logo.setPixmap(get_svg_icon("logo", theme.ACCENT, 28).pixmap(28, 28))
        h.addWidget(self.logo)
        self.brand_box = QWidget()
        b = QVBoxLayout(self.brand_box)
        b.setContentsMargins(0, 0, 0, 0)
        b.setSpacing(0)
        brand = QLabel("ModMaster")
        brand.setObjectName("Brand")
        sub = QLabel("KINGDOM COME II")
        sub.setObjectName("BrandSub")
        b.addWidget(brand)
        b.addWidget(sub)
        h.addWidget(self.brand_box, 1)
        self.toggle_btn = QPushButton()
        self.toggle_btn.setObjectName("Ghost")
        self.toggle_btn.setFixedSize(28, 28)
        self.toggle_btn.clicked.connect(lambda: self.set_compact(not self._is_compact, manual=True))
        h.addWidget(self.toggle_btn)
        lay.addWidget(header)

        self.nav = QListWidget()
        self.nav.setObjectName("Nav")
        self.nav.setFocusPolicy(Qt.NoFocus)
        self.nav.setIconSize(QSize(18, 18))
        self.nav.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        self.nav.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.nav.setFrameShape(QFrame.NoFrame)
        for key, text, icon, args in NAV_ITEMS:
            self._add_entry(key, text, icon, args)
        self.nav.currentRowChanged.connect(self._on_row)
        lay.addWidget(self.nav, 1)

        bottom = QListWidget()
        bottom.setObjectName("Nav")
        bottom.setFocusPolicy(Qt.NoFocus)
        bottom.setIconSize(QSize(18, 18))
        bottom.setFrameShape(QFrame.NoFrame)
        bottom.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        bottom.setFixedHeight(52)
        self.bottom = bottom
        settings = QListWidgetItem(get_svg_icon("cog", theme.TEXT_DIM, 18), "  Settings")
        settings.setData(Qt.UserRole, ("settings", {}))
        bottom.addItem(settings)
        self.item_map["settings"] = settings
        self._labels["settings"] = "Settings"
        bottom.currentRowChanged.connect(self._on_bottom_row)
        lay.addWidget(bottom)

        self.footer = QLabel(f"Version {display_version()}")
        self.footer.setObjectName("Muted")
        self.footer.setContentsMargins(22, 4, 12, 0)
        lay.addWidget(self.footer)

        self._update_toggle()
        self.select_page("home")

    def _add_entry(self, key, text, icon, args) -> None:
        if key is None:
            item = QListWidgetItem(text.upper())
            item.setFlags(Qt.NoItemFlags)
            self._sections.append(item)
            self.nav.addItem(item)
            return
        item = QListWidgetItem(get_svg_icon(icon, theme.TEXT_DIM, 18), f"  {text}")
        item.setData(Qt.UserRole, (key, args))
        item.setToolTip(text)
        self.nav.addItem(item)
        self.item_map[key] = item
        self._labels[key] = text

    def _on_row(self, row: int) -> None:
        item = self.nav.item(row)
        if item is None or not item.data(Qt.UserRole):
            return
        self.bottom.blockSignals(True)
        self.bottom.setCurrentRow(-1)
        self.bottom.clearSelection()
        self.bottom.blockSignals(False)
        key, args = item.data(Qt.UserRole)
        self.page_selected.emit(key, args)

    def _on_bottom_row(self, row: int) -> None:
        item = self.bottom.item(row)
        if item is None:
            return
        self.nav.blockSignals(True)
        self.nav.setCurrentRow(-1)
        self.nav.clearSelection()
        self.nav.blockSignals(False)
        key, args = item.data(Qt.UserRole)
        self.page_selected.emit(key, args)

    def select_page(self, key: str) -> None:
        item = self.item_map.get(key)
        if item is None:
            return
        target = self.bottom if item.listWidget() is self.bottom else self.nav
        other = self.nav if target is self.bottom else self.bottom
        for w in (self.nav, self.bottom):
            w.blockSignals(True)
        other.setCurrentRow(-1)
        other.clearSelection()
        target.setCurrentItem(item)
        for w in (self.nav, self.bottom):
            w.blockSignals(False)

    def is_compact(self) -> bool:
        return self._is_compact

    def _update_toggle(self) -> None:
        icon = "chevron-right" if self._is_compact else "chevron-left"
        self.toggle_btn.setIcon(get_svg_icon(icon, theme.TEXT_MUTED, 14))
        self.toggle_btn.setToolTip("Expand navigation" if self._is_compact else "Collapse navigation")

    def set_compact(self, compact: bool, manual: bool = False) -> None:
        if manual:
            self._manual_override = True
        if self._is_compact == compact:
            return
        self._is_compact = compact
        self.setFixedWidth(WIDTH_COMPACT if compact else WIDTH_EXPANDED)
        self.brand_box.setVisible(not compact)
        self.logo.setVisible(not compact)
        self.footer.setVisible(not compact)
        for section in self._sections:
            section.setHidden(compact)
        for key, item in self.item_map.items():
            item.setText("" if compact else f"  {self._labels[key]}")
        self._update_toggle()
        self.compact_toggled.emit(compact)

    def auto_collapse_for_3d(self) -> None:
        if not self._manual_override:
            self.set_compact(True)
