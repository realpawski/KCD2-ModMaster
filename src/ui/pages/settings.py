"""Settings: paths, asset index, in-game tools, Blender, updates and about."""
from __future__ import annotations

import subprocess
import webbrowser
from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QCheckBox,
    QFileDialog,
    QGridLayout,
    QHBoxLayout,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QScrollArea,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from app.version import APP_NAME, HOMEPAGE, PUBLISHER, REPOSITORY, display_version
from blender.bridge_manager import CURRENT_BRIDGE_VERSION, BlenderBridgeManager, BridgeStatus
from kcd2.detect import (
    detect_blender_candidates,
    detect_game_dir,
    detect_tools_dir,
    validate_game_dir,
    validate_tools_dir,
)
from ui import theme
from ui.context import AppContext
from ui.icons import get_svg_icon
from ui.pages.runtime_tools import RuntimeToolsPanel
from ui.widgets import Card, PageHeader, StatusPill, button, label, page_layout
from utils.helpers import reveal_in_explorer

SECTIONS = (
    ("game", "Game & folders", "home"),
    ("index", "Asset index", "search"),
    ("ingame", "In-game menu", "play"),
    ("blender", "Blender", "blender"),
    ("updates", "Updates", "arrow-down-tray"),
    ("about", "About", "information-circle"),
)


class PathRow(QWidget):
    def __init__(self, title: str, hint: str, browse, detect=None, file_filter: str = "", parent=None):
        super().__init__(parent)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 4)
        lay.setSpacing(6)
        lay.addWidget(label(title, "H3"))
        if hint:
            lay.addWidget(label(hint, "Muted", wrap=True))
        row = QHBoxLayout()
        row.setSpacing(8)
        self.edit = QLineEdit()
        row.addWidget(self.edit, 1)
        browse_btn = button("Browse", "folder")
        browse_btn.clicked.connect(browse)
        row.addWidget(browse_btn)
        if detect:
            detect_btn = button("Detect", "sparkles")
            detect_btn.clicked.connect(detect)
            row.addWidget(detect_btn)
        lay.addLayout(row)
        self.status = label("", "Muted", wrap=True)
        lay.addWidget(self.status)

    def set_status(self, ok: bool | None, text: str) -> None:
        color = theme.OK if ok else (theme.TEXT_MUTED if ok is None else theme.WARN)
        self.status.setStyleSheet(f"color: {color};")
        self.status.setText(text)


class SettingsPage(QWidget):
    def __init__(self, ctx: AppContext, parent=None):
        super().__init__(parent)
        self.ctx = ctx
        self.bridge_mgr = BlenderBridgeManager.get_instance(self.ctx.settings)
        self._dirty = False

        lay = page_layout(self)
        header = PageHeader("Settings", "Game files are only ever read. Your work lives in the workspace folder.")
        self.btn_save = header.add_action(button("Save changes", "check", "Primary"))
        self.btn_save.clicked.connect(self._save_settings)
        lay.addWidget(header)

        body = QHBoxLayout()
        body.setSpacing(24)
        self.nav = QListWidget()
        self.nav.setObjectName("Nav")
        self.nav.setFixedWidth(220)
        self.nav.setStyleSheet(f"QListWidget#Nav {{ background: transparent; border: none; }}")
        self.pages = QStackedWidget()
        for key, title, icon in SECTIONS:
            entry = QListWidgetItem(get_svg_icon(icon, theme.TEXT_DIM, 18), f"  {title}")
            entry.setData(Qt.UserRole, key)
            self.nav.addItem(entry)
            self.pages.addWidget(self._wrap(getattr(self, f"_build_{key}")()))
        self.nav.currentRowChanged.connect(self.pages.setCurrentIndex)
        self.nav.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        body.addWidget(self.nav)
        body.addWidget(self.pages, 1)
        lay.addLayout(body, 1)
        self.nav.setCurrentRow(0)
        self.load_from_config()

    def _wrap(self, content: QWidget) -> QScrollArea:
        holder = QWidget()
        col = QVBoxLayout(holder)
        col.setContentsMargins(0, 0, 8, 0)
        col.addWidget(content)
        col.addStretch(1)
        holder.setMaximumWidth(1100)
        area = QScrollArea()
        area.setWidgetResizable(True)
        area.setWidget(holder)
        return area

    def show_section(self, key: str) -> None:
        for i, (k, _t, _i) in enumerate(SECTIONS):
            if k == key:
                self.nav.setCurrentRow(i)


    def _build_game(self) -> QWidget:
        card = Card("Folders")
        self.row_game = PathRow("Kingdom Come: Deliverance II",
                                "The folder that contains Bin, Data and Mods.",
                                self._browse_game, self._detect_game)
        self.row_tools = PathRow("KCD2 Modding Tools (optional)",
                                 "Warhorse's free modding tools from Steam. Used for compiling models.",
                                 self._browse_tools, self._detect_tools)
        self.row_ws = PathRow("Workspace",
                              "Your mods, edited assets, extracted files and caches.",
                              self._browse_workspace)
        for row in (self.row_game, self.row_tools, self.row_ws):
            card.add(row)
            row.edit.textEdited.connect(self._mark_dirty)
        self.row_game.edit.textChanged.connect(lambda _: self._validate_ui_paths())
        self.row_tools.edit.textChanged.connect(lambda _: self._validate_ui_paths())
        open_ws = button("Open workspace folder", "folder", "Ghost")
        open_ws.clicked.connect(self._open_workspace)
        card.add(open_ws)
        return card

    def _build_index(self) -> QWidget:
        page = QWidget()
        col = QVBoxLayout(page)
        col.setContentsMargins(0, 0, 0, 0)
        col.setSpacing(16)
        scan = Card("What to index")
        self.chk_engine = QCheckBox("Engine archives (Engine/*.pak)")
        self.chk_level = QCheckBox("Level archives (Data/Levels) — slower, adds terrain and level objects")
        self.chk_media = QCheckBox("Media archives (videos, music, sounds) — large, no 3D models")
        for chk in (self.chk_engine, self.chk_level, self.chk_media):
            scan.add(chk)
            chk.toggled.connect(self._mark_dirty)
        rescan = button("Save and rescan now", "arrow-path")
        rescan.clicked.connect(self._save_and_rescan)
        scan.add(rescan)
        col.addWidget(scan)
        extract = Card("Extracting files")
        self.chk_companions = QCheckBox("Also extract companion files (.cgfm mesh data, .dds mip parts)")
        self.chk_companions.setToolTip("KCD2 keeps geometry in .cgfm next to the .cgf header. "
                                       "Without it, an extracted model is incomplete.")
        self.chk_ask_dest = QCheckBox("Ask for a destination folder every time")
        for chk in (self.chk_companions, self.chk_ask_dest):
            extract.add(chk)
            chk.toggled.connect(self._mark_dirty)
        col.addWidget(extract)
        return page

    def _build_ingame(self) -> QWidget:
        self.runtime_panel = RuntimeToolsPanel(self.ctx)
        return self.runtime_panel

    def _build_blender(self) -> QWidget:
        card = Card("Blender")
        self.row_blender = PathRow("Blender executable", "Blender 5.1 or newer.", self._browse_blender,
                                   self._detect_blender)
        self.row_blender.edit.textEdited.connect(self._mark_dirty)
        card.add(self.row_blender)
        bridge = Card("ModMaster bridge add-on", inset=True)
        status = QHBoxLayout()
        self.pill_bridge = StatusPill()
        status.addWidget(self.pill_bridge)
        self.lbl_bridge_version = label("", "Muted")
        status.addWidget(self.lbl_bridge_version)
        status.addStretch(1)
        bridge.body.addLayout(status)
        self.lbl_bridge_details = label("", "Dim", wrap=True)
        bridge.add(self.lbl_bridge_details)
        actions = QHBoxLayout()
        self.btn_install_bridge = button("Install add-on", "wrench")
        self.btn_install_bridge.clicked.connect(self._install_or_repair_bridge)
        self.btn_open_blender = button("Open Blender", "blender")
        self.btn_open_blender.clicked.connect(self._open_blender_app)
        self.btn_test_conn = button("Test connection", "arrow-path")
        self.btn_test_conn.clicked.connect(self._test_bridge_connection)
        for b in (self.btn_install_bridge, self.btn_open_blender, self.btn_test_conn):
            actions.addWidget(b)
        actions.addStretch(1)
        bridge.body.addLayout(actions)
        card.add(bridge)
        return card

    def _build_updates(self) -> QWidget:
        card = Card("Updates")
        grid = QGridLayout()
        grid.setHorizontalSpacing(18)
        grid.setVerticalSpacing(8)
        grid.addWidget(label("Installed version", "Muted"), 0, 0)
        grid.addWidget(label(display_version(), "H3"), 0, 1)
        grid.addWidget(label("Status", "Muted"), 1, 0)
        self.pill_update = StatusPill("Not checked yet", "muted")
        grid.addWidget(self.pill_update, 1, 1, Qt.AlignLeft)
        grid.setColumnStretch(2, 1)
        card.body.addLayout(grid)
        self.chk_auto_update = QCheckBox("Check for updates when ModMaster starts")
        self.chk_auto_update.toggled.connect(self._mark_dirty)
        card.add(self.chk_auto_update)
        row = QHBoxLayout()
        self.btn_check_update = button("Check now", "arrow-path")
        self.btn_check_update.clicked.connect(self._check_updates)
        row.addWidget(self.btn_check_update)
        row.addStretch(1)
        card.body.addLayout(row)
        card.add(label("Updates are downloaded from the official GitHub releases and verified before "
                       "the installer runs. Your workspace and mods are never touched by an update.",
                       "Muted", wrap=True))
        return card

    def _build_about(self) -> QWidget:
        card = Card("About")
        card.add(label(APP_NAME, "H2"))
        card.add(label(f"Version {display_version()}  ·  by {PUBLISHER}", "Dim"))
        card.add(label("ModMaster is a fan-made tool and is not affiliated with or endorsed by "
                       "Warhorse Studios or Deep Silver. Kingdom Come: Deliverance is a trademark of "
                       "its respective owners.", "Muted", wrap=True))
        row = QHBoxLayout()
        for text, url, icon in (("Website", HOMEPAGE, "arrow-top-right-on-square"),
                                ("GitHub", f"https://github.com/{REPOSITORY}", "arrow-top-right-on-square"),
                                ("Report a bug", f"https://github.com/{REPOSITORY}/issues/new", "warning")):
            b = button(text, icon)
            b.clicked.connect(lambda _=False, u=url: webbrowser.open(u))
            row.addWidget(b)
        row.addStretch(1)
        card.body.addLayout(row)
        logs = button("Open log folder", "folder", "Ghost")
        logs.clicked.connect(self._open_logs)
        card.add(logs)
        return card


    def _mark_dirty(self, *_):
        self._dirty = True
        self.btn_save.setEnabled(True)

    def load_from_config(self) -> None:
        cfg = self.ctx.settings
        self.row_game.edit.setText(cfg.game_dir)
        self.row_tools.edit.setText(cfg.tools_dir)
        self.row_blender.edit.setText(cfg.blender_exe)
        self.row_ws.edit.setText(cfg.workspace_dir)
        self.row_ws.set_status(None, "")
        for chk, value in ((self.chk_engine, cfg.include_engine_paks), (self.chk_level, cfg.include_level_paks),
                           (self.chk_media, cfg.include_media_paks), (self.chk_companions, cfg.extract_companions),
                           (self.chk_ask_dest, cfg.ask_extract_destination),
                           (self.chk_auto_update, cfg.check_updates_on_start)):
            chk.blockSignals(True)
            chk.setChecked(value)
            chk.blockSignals(False)
        self._validate_ui_paths()
        self._update_bridge_ui()
        self.runtime_panel.refresh()
        self._dirty = False
        self.btn_save.setEnabled(False)

    def _validate_ui_paths(self) -> None:
        game = validate_game_dir(self.row_game.edit.text().strip())
        if game.ok:
            self.row_game.set_status(True, "Found  ·  " + ", ".join(game.info))
        else:
            self.row_game.set_status(False, game.problems[0] if game.problems else "Not a valid game folder.")
        tools = validate_tools_dir(self.row_tools.edit.text().strip())
        if tools.ok:
            self.row_tools.set_status(True, "Found  ·  " + ", ".join(tools.info))
        else:
            self.row_tools.set_status(None, "Not set. Only needed for compiling your own models.")

    def _update_bridge_ui(self) -> None:
        det = self.bridge_mgr.detect_addon_status()
        if self.bridge_mgr.is_blender_connected():
            self.pill_bridge.set("Connected", "ok")
        elif det.status == BridgeStatus.INSTALLED:
            self.pill_bridge.set("Installed", "ok")
        else:
            self.pill_bridge.set(str(det.status).replace("_", " ").title(), "warn")
        self.lbl_bridge_version.setText(f"Add-on {det.version or CURRENT_BRIDGE_VERSION}")
        self.lbl_bridge_details.setText(det.details)
        self.btn_install_bridge.setText("Repair add-on" if det.status == BridgeStatus.INSTALLED else "Install add-on")

    def _install_or_repair_bridge(self) -> None:
        ok, msg = self.bridge_mgr.install_or_update_addon()
        self._update_bridge_ui()
        if ok:
            QMessageBox.information(self, "Blender bridge", "The add-on is installed. Restart Blender to load it.")
        else:
            QMessageBox.warning(self, "Blender bridge", f"Could not install the add-on:\n{msg}")

    def _open_blender_app(self) -> None:
        exe = self.row_blender.edit.text().strip()
        if not exe or not Path(exe).is_file():
            QMessageBox.warning(self, "Blender", "Set a valid Blender executable first.")
            return
        try:
            subprocess.Popen([exe])
        except OSError as exc:
            QMessageBox.critical(self, "Blender", f"Could not start Blender:\n{exc}")

    def _test_bridge_connection(self) -> None:
        if self.bridge_mgr.is_blender_connected():
            QMessageBox.information(self, "Blender bridge", "Blender is connected.")
        else:
            QMessageBox.information(self, "Blender bridge",
                                    "Blender is not connected. Start Blender with the ModMaster add-on enabled.")
        self._update_bridge_ui()

    def _browse_game(self) -> None:
        d = QFileDialog.getExistingDirectory(self, "Kingdom Come: Deliverance II folder", self.row_game.edit.text())
        if d:
            self.row_game.edit.setText(d)
            self._mark_dirty()

    def _browse_tools(self) -> None:
        d = QFileDialog.getExistingDirectory(self, "KCD2 Modding Tools folder", self.row_tools.edit.text())
        if d:
            self.row_tools.edit.setText(d)
            self._mark_dirty()

    def _browse_blender(self) -> None:
        f, _ = QFileDialog.getOpenFileName(self, "Blender executable", self.row_blender.edit.text(),
                                           "Programs (*.exe)")
        if f:
            self.row_blender.edit.setText(f)
            self._mark_dirty()

    def _browse_workspace(self) -> None:
        d = QFileDialog.getExistingDirectory(self, "Workspace folder", self.row_ws.edit.text())
        if d:
            self.row_ws.edit.setText(d)
            self._mark_dirty()

    def _open_workspace(self) -> None:
        path = Path(self.row_ws.edit.text().strip() or self.ctx.settings.workspace)
        path.mkdir(parents=True, exist_ok=True)
        reveal_in_explorer(path)

    def _open_logs(self) -> None:
        from core.config import app_data_dir
        path = app_data_dir() / "logs"
        path.mkdir(parents=True, exist_ok=True)
        reveal_in_explorer(path)

    def _detect_game(self) -> None:
        found = detect_game_dir()
        if found:
            self.row_game.edit.setText(str(found))
            self._mark_dirty()
        else:
            QMessageBox.information(self, "Detect", "Kingdom Come: Deliverance II was not found in your Steam libraries.")

    def _detect_tools(self) -> None:
        found = detect_tools_dir()
        if found:
            self.row_tools.edit.setText(str(found))
            self._mark_dirty()
        else:
            QMessageBox.information(self, "Detect", "The KCD2 Modding Tools were not found in your Steam libraries.")

    def _detect_blender(self) -> None:
        candidates = detect_blender_candidates()
        if candidates:
            self.row_blender.edit.setText(str(candidates[0]))
            self._mark_dirty()
        else:
            QMessageBox.information(self, "Detect", "No Blender installation was found.")

    def _save_settings(self) -> None:
        cfg = self.ctx.settings
        old_ws = cfg.workspace_dir
        cfg.game_dir = self.row_game.edit.text().strip()
        cfg.tools_dir = self.row_tools.edit.text().strip()
        cfg.blender_exe = self.row_blender.edit.text().strip()
        cfg.workspace_dir = self.row_ws.edit.text().strip()
        cfg.include_engine_paks = self.chk_engine.isChecked()
        cfg.include_level_paks = self.chk_level.isChecked()
        cfg.include_media_paks = self.chk_media.isChecked()
        cfg.extract_companions = self.chk_companions.isChecked()
        cfg.ask_extract_destination = self.chk_ask_dest.isChecked()
        cfg.check_updates_on_start = self.chk_auto_update.isChecked()
        cfg.save()
        cfg.ensure_workspace()
        if cfg.workspace_dir != old_ws:
            self.ctx.reopen_index()
        self.ctx.settings_changed.emit()
        self._validate_ui_paths()
        self._update_bridge_ui()
        self._dirty = False
        self.btn_save.setEnabled(False)

    def _save_and_rescan(self) -> None:
        self._save_settings()
        self.ctx.navigate.emit("scan_trigger", {})

    def _check_updates(self) -> None:
        self.ctx.navigate.emit("check_updates", {"manual": True})

    def set_update_status(self, text: str, state: str) -> None:
        self.pill_update.set(text, state)
