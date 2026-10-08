"""Home: setup checklist, quick actions and recent mods."""
from __future__ import annotations

import time
from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from app.version import display_version
from blender.bridge_manager import BlenderBridgeManager, BridgeStatus
from items.store import ModItemStore
from kcd2.detect import validate_game_dir
from mods.project import ModManager
from ui import theme
from ui.context import AppContext
from ui.icons import get_svg_icon
from ui.widgets import Card, ClickableCard, PageHeader, StatusPill, button, label
from utils.helpers import reveal_in_explorer


class ChecklistRow(QWidget):
    def __init__(self, number: int, title: str, parent=None):
        super().__init__(parent)
        lay = QHBoxLayout(self)
        lay.setContentsMargins(0, 6, 0, 6)
        lay.setSpacing(14)
        self.badge = QLabel(str(number))
        self.badge.setFixedSize(26, 26)
        self.badge.setAlignment(Qt.AlignCenter)
        lay.addWidget(self.badge)
        text = QVBoxLayout()
        text.setSpacing(1)
        text.addWidget(label(title, "H3"))
        self.detail = label("", "Muted")
        self.detail.setTextInteractionFlags(Qt.TextSelectableByMouse)
        text.addWidget(self.detail)
        lay.addLayout(text, 1)
        self.pill = StatusPill()
        lay.addWidget(self.pill)
        self.action = button("")
        self.action.setMinimumWidth(150)
        policy = self.action.sizePolicy()
        policy.setRetainSizeWhenHidden(True)
        self.action.setSizePolicy(policy)
        lay.addWidget(self.action)

    def set(self, done: bool, detail: str, state_text: str, action_text: str = "", optional: bool = False):
        if done:
            style = f"background: {theme.ACCENT}; color: {theme.ACCENT_TEXT};"
            self.pill.set(state_text, "ok")
        else:
            style = f"background: {theme.BG3}; color: {theme.TEXT_DIM}; border: 1px solid {theme.BORDER_LIGHT};"
            self.pill.set(state_text, "muted" if optional else "warn")
        self.badge.setStyleSheet(style + " border-radius: 13px; font-weight: 700;")
        self.detail.setText(detail)
        self.action.setVisible(bool(action_text))
        self.action.setText(action_text)


class ActionTile(ClickableCard):
    def __init__(self, icon: str, title: str, text: str, parent=None):
        super().__init__(parent)
        self.setMinimumHeight(88)
        lay = QHBoxLayout(self)
        lay.setContentsMargins(16, 14, 16, 14)
        lay.setSpacing(14)
        art = QLabel()
        art.setPixmap(get_svg_icon(icon, theme.ACCENT, 26).pixmap(26, 26))
        lay.addWidget(art, 0, Qt.AlignTop)
        col = QVBoxLayout()
        col.setSpacing(3)
        for w in (label(title, "H3"), label(text, "Muted", wrap=True)):
            col.addWidget(w)
        col.addStretch(1)
        lay.addLayout(col, 1)


class HomePage(QWidget):
    def __init__(self, ctx: AppContext, parent=None):
        super().__init__(parent)
        self.ctx = ctx
        self.bridge_mgr = BlenderBridgeManager.get_instance(self.ctx.settings)

        scroll = QScrollArea(self)
        scroll.setWidgetResizable(True)
        body = QWidget()
        body.setObjectName("Page")
        scroll.setWidget(body)
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.addWidget(scroll)

        lay = QVBoxLayout(body)
        lay.setContentsMargins(28, 22, 28, 28)
        lay.setSpacing(18)
        lay.addWidget(PageHeader(
            "KCD2 ModMaster",
            "Browse the game's files, create new weapons, armor and items, and install your mods "
            f"into Kingdom Come: Deliverance II.  ·  Version {display_version()}"))

        grid = QGridLayout()
        grid.setHorizontalSpacing(18)
        grid.setVerticalSpacing(18)
        grid.setColumnStretch(0, 3)
        grid.setColumnStretch(1, 2)

        setup = Card("Setup")
        self.row_game = ChecklistRow(1, "Game folder")
        self.row_game.action.clicked.connect(lambda: self.ctx.navigate.emit("settings", {}))
        self.row_index = ChecklistRow(2, "Index game files")
        self.row_index.action.clicked.connect(lambda: self.ctx.navigate.emit("scan_trigger", {}))
        self.row_blender = ChecklistRow(3, "Blender bridge")
        self.row_blender.action.clicked.connect(lambda: self.ctx.navigate.emit("settings", {}))
        self.row_mod = ChecklistRow(4, "Create a mod")
        self.row_mod.action.clicked.connect(lambda: self.ctx.navigate.emit("mods", {}))
        for row in (self.row_game, self.row_index, self.row_blender, self.row_mod):
            setup.add(row)
        grid.addWidget(setup, 0, 0)

        recent = Card("Recent mods")
        self.recent_box = QVBoxLayout()
        self.recent_box.setSpacing(6)
        recent.body.addLayout(self.recent_box)
        recent.body.addStretch(1)
        all_mods = button("Open mods", "puzzle")
        all_mods.clicked.connect(lambda: self.ctx.navigate.emit("mods", {}))
        recent.add(all_mods)
        grid.addWidget(recent, 0, 1)
        lay.addLayout(grid)

        lay.addWidget(label("QUICK ACTIONS", "Section"))
        tiles = QGridLayout()
        tiles.setHorizontalSpacing(14)
        tiles.setVerticalSpacing(14)
        entries = [
            ("puzzle", "New mod", "Start a mod project for items, models and textures.", ("mods", {})),
            ("weapon", "Browse weapons", "Inspect every weapon model and texture in 3D.",
             ("weapons", {"asset_class": "Weapons", "title": "Weapons"})),
            ("armor", "Browse armor", "Helmets, hoods and clothing straight from the game files.",
             ("armor", {"asset_class": "Armor", "title": "Armor"})),
            ("building", "Houses & buildings", "Explore structures, props and their materials.",
             ("buildings", {"asset_class": "Buildings", "title": "Houses & Buildings"})),
            ("search", "Search everything", "Full-text search across all indexed game archives.", ("browser", {})),
            ("folder", "Workspace", "Assets you edit in Blender and their export status.", ("my_assets", {})),
        ]
        for i, (icon, title, text, (key, args)) in enumerate(entries):
            tile = ActionTile(icon, title, text)
            tile.clicked.connect(lambda k=key, a=args: self.ctx.navigate.emit(k, a))
            tiles.addWidget(tile, i // 3, i % 3)
        lay.addLayout(tiles)

        footer = QHBoxLayout()
        footer.addWidget(label("Workspace", "Muted"))
        self.ws_path = label("", "Mono")
        footer.addWidget(self.ws_path)
        open_ws = button("Open", "folder", "Ghost")
        open_ws.clicked.connect(self._open_workspace)
        footer.addWidget(open_ws)
        footer.addStretch(1)
        lay.addLayout(footer)
        lay.addStretch(1)

        self.ctx.index_changed.connect(self.refresh)
        self.ctx.mods_changed.connect(self.refresh)
        self.refresh()

    def refresh(self) -> None:
        cfg = self.ctx.settings
        game = validate_game_dir(cfg.game_dir)
        if game.ok:
            self.row_game.set(True, cfg.game_dir, "Found", "")
        else:
            problem = game.problems[0] if game.problems else "Select the game folder in Settings."
            self.row_game.set(False, problem, "Missing", "Open settings")

        stats = self.ctx.index.stats()
        if stats.get("assets", 0):
            when = ""
            last = stats.get("last_scan")
            try:
                when = f"  ·  updated {time.strftime('%d %b %Y', time.localtime(float(last)))}" if last else ""
            except (TypeError, ValueError):
                when = ""
            self.row_index.set(True, f"{stats['assets']:,} files in {stats['archives']} archives{when}",
                               "Indexed", "Rescan")
        else:
            self.row_index.set(False, "Needed for browsing and previews. Takes about a minute.",
                               "Not indexed", "Scan now")

        detection = self.bridge_mgr.detect_addon_status()
        if self.bridge_mgr.is_blender_connected():
            self.row_blender.set(True, "Blender is connected.", "Connected", "")
        elif detection.status == BridgeStatus.INSTALLED:
            self.row_blender.set(True, f"Add-on {detection.version} installed. Start Blender to connect.",
                                 "Installed", "Settings")
        else:
            self.row_blender.set(False, "Optional. Needed to edit models in Blender.", "Optional",
                                 "Set up", optional=True)

        mods = ModManager(cfg.workspace).list_mods()
        if mods:
            self.row_mod.set(True, f"{len(mods)} mod{'s' * (len(mods) != 1)} in your workspace.", "Done", "Open mods")
        else:
            self.row_mod.set(False, "Bundle new and changed items into a mod.", "Next step", "New mod")
        self._fill_recent(mods[:5])
        self.ws_path.setText(str(cfg.workspace))

    def _fill_recent(self, mods) -> None:
        while self.recent_box.count():
            w = self.recent_box.takeAt(0).widget()
            if w:
                w.deleteLater()
        if not mods:
            self.recent_box.addWidget(label("No mods yet. Your mods will show up here.", "Muted", wrap=True))
            return
        game_mods = Path(self.ctx.settings.game_dir or ".") / "Mods"
        for mod in mods:
            items = len(ModItemStore(mod, self.ctx.settings.workspace).list())
            entry = ClickableCard()
            entry.setMinimumHeight(58)
            row = QHBoxLayout(entry)
            row.setContentsMargins(14, 8, 14, 8)
            col = QVBoxLayout()
            col.setSpacing(1)
            name = label(mod.name, "H3")
            meta = label(f"v{mod.version}  ·  {items} item{'s' * (items != 1)}", "Muted")
            for w in (name, meta):
                col.addWidget(w)
            row.addLayout(col, 1)
            installed = (game_mods / mod.id / "mod.manifest").is_file()
            pill = StatusPill("Installed" if installed else "Not installed", "ok" if installed else "muted")
            row.addWidget(pill)
            entry.clicked.connect(lambda m=mod.id: self.ctx.navigate.emit("mods", {"mod_id": m}))
            self.recent_box.addWidget(entry)

    def _open_workspace(self) -> None:
        path = self.ctx.settings.workspace
        path.mkdir(parents=True, exist_ok=True)
        reveal_in_explorer(path)
