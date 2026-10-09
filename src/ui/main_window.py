"""Main window: navigation, page stack, task console."""
from __future__ import annotations

import logging
import sys
from pathlib import Path

from PySide6.QtCore import QByteArray, Qt, QTimer
from PySide6.QtGui import QCloseEvent
from PySide6.QtWidgets import (
    QFileDialog,
    QHBoxLayout,
    QMainWindow,
    QMessageBox,
    QSplitter,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from assets.extract import build_plan, run_extraction
from core.config import Settings
from core.logging_bridge import setup_logging
from core.tasks import Task
from database.index import AssetRow
from database.scanner import scan
from ui import theme
from ui.console import ConsoleWidget
from app import updater
from app.version import APP_NAME, CHANNEL, VERSION, display_version
from ui.dialogs.update_dialog import UpdateDialog
from ui.context import AppContext
from ui.icons import get_svg_icon
from ui.pages.browser import BrowserPage
from ui.pages.home import HomePage
from ui.pages.mods import ModsPage
from ui.pages.settings import SettingsPage
from ui.pages.workspace_assets import WorkspaceAssetsPage
from ui.sidebar import SidebarWidget

log = logging.getLogger(__name__)


class MainWindow(QMainWindow):
    def __init__(self, settings: Settings, parent=None):
        super().__init__(parent)
        self.settings = settings
        self.ctx = AppContext(settings)

        self.setWindowTitle(f"{APP_NAME} {display_version()}")
        self.setWindowIcon(get_svg_icon("logo", theme.ACCENT, 64))
        self.setMinimumSize(1180, 720)
        self.resize(1600, 960)
        self.setStyleSheet(theme.QSS)
        self.log_handler = setup_logging()

        # Top Workspace: Sidebar + Stacked content pages
        self.top_workspace = QWidget()
        self.top_workspace.setObjectName("TopWorkspace")
        top_lay = QHBoxLayout(self.top_workspace)
        top_lay.setContentsMargins(0, 0, 0, 0)
        top_lay.setSpacing(0)

        self.sidebar = SidebarWidget(self.ctx)
        self.sidebar.page_selected.connect(self._on_navigate)
        top_lay.addWidget(self.sidebar)

        self.stack = QStackedWidget()
        self.home_page = HomePage(self.ctx)
        self.browser_page = BrowserPage(self.ctx)
        self.settings_page = SettingsPage(self.ctx)
        self.workspace_page = WorkspaceAssetsPage(self.ctx)
        self.mods_page = ModsPage(self.ctx)

        self.stack.addWidget(self.home_page)       # index 0: home
        self.stack.addWidget(self.browser_page)    # index 1: browser
        self.stack.addWidget(self.settings_page)   # index 2: settings
        self.stack.addWidget(self.workspace_page)  # index 3: my_assets
        self.stack.addWidget(self.mods_page)       # index 4: mods

        top_lay.addWidget(self.stack, 1)

        # Reference to Inspector in BrowserPage for backward compatibility
        self.inspector = self.browser_page.inspector

        # Bottom Operation Console with vertical resizability
        self.console = ConsoleWidget(self)
        self._saved_console_height = 160
        self.console.collapse_toggled.connect(self._on_console_collapse_toggled)

        # Responsive Vertical Splitter: [Top Workspace] / [Task Console]
        self.v_splitter = QSplitter(Qt.Vertical)
        self.v_splitter.setObjectName("MainVerticalSplitter")
        self.v_splitter.setChildrenCollapsible(False)
        self.v_splitter.addWidget(self.top_workspace)
        self.v_splitter.addWidget(self.console)
        self.v_splitter.setStretchFactor(0, 6)
        self.v_splitter.setStretchFactor(1, 1)
        console_sizes = self.settings.console_splitter_sizes or [720, 160]
        self.v_splitter.setSizes(console_sizes)
        self.v_splitter.splitterMoved.connect(self._on_console_splitter_moved)

        self.setCentralWidget(self.v_splitter)

        # Restore window geometry if saved
        if self.settings.window_geometry:
            try:
                self.restoreGeometry(QByteArray.fromHex(self.settings.window_geometry.encode("ascii")))
            except Exception:
                pass

        # Sidebar compact state initialization & auto-compact connection
        if self.settings.sidebar_compact:
            self.sidebar.set_compact(True, manual=True)
        self.sidebar.compact_toggled.connect(lambda comp: setattr(self.settings, "sidebar_compact", comp))
        self.ctx.asset_selected.connect(self._on_asset_selected_auto_compact)

        # Wire logging records to console
        self.log_handler.emitter.record.connect(self.console.append)

        # Wire context signals
        self.ctx.navigate.connect(self._handle_navigation_request)
        self.ctx.extract_requested.connect(self._handle_extract)
        self.ctx.extract_to_requested.connect(lambda rows, comp: self._handle_extract(rows, comp, choose_dest=True))

        self.statusBar().hide()
        self.console.set_collapsed(self.settings.console_collapsed)
        if not self.settings.window_geometry:
            QTimer.singleShot(0, self.showMaximized)
        if getattr(sys, "frozen", False) and self.settings.check_updates_on_start:
            QTimer.singleShot(4000, self.check_for_updates)
        if getattr(sys, "frozen", False) and self.settings.last_run_version != VERSION:
            QTimer.singleShot(2500, self._after_update)

        # First-run auto-detection if game path is unset
        if not self.settings.game_dir:
            QTimer.singleShot(100, self._auto_detect_first_run)

    def _on_console_splitter_moved(self, pos: int, index: int) -> None:
        sizes = self.v_splitter.sizes()
        if len(sizes) >= 2 and sizes[1] > 40:
            self.settings.console_splitter_sizes = sizes

    def _on_asset_selected_auto_compact(self, row: AssetRow | None) -> None:
        if row and row.ext.lower() in ("cgf", "skin", "chr", "cga"):
            self.sidebar.auto_collapse_for_3d()

    def _on_console_collapse_toggled(self, collapsed: bool) -> None:
        sizes = self.v_splitter.sizes()
        total = sum(sizes) or self.height()
        if collapsed:
            if len(sizes) >= 2 and sizes[1] > 40:
                self._saved_console_height = sizes[1]
            self.console.setFixedHeight(36)
            self.v_splitter.setSizes([total - 36, 36])
        else:
            self.console.setMinimumHeight(120)
            self.console.setMaximumHeight(16777215)
            target_h = getattr(self, "_saved_console_height", 220) or 220
            self.v_splitter.setSizes([max(300, total - target_h), target_h])

    def _on_navigate(self, key: str, args: dict) -> None:
        if key == "home":
            self.stack.setCurrentIndex(0)
            self.home_page.refresh()
        elif key in ("browser", "weapons", "armor", "characters", "buildings", "props", "materials", "textures"):
            self.stack.setCurrentIndex(1)
            self.browser_page.apply_options(args)
        elif key == "settings":
            self.stack.setCurrentIndex(2)
            self.settings_page.load_from_config()
        elif key == "my_assets":
            self.stack.setCurrentIndex(3)
            self.workspace_page.refresh()
        elif key in ("mods", "build"):
            self.stack.setCurrentIndex(4)
            if args.get("mod_id"):
                self.mods_page.select_mod(args["mod_id"])
            else:
                self.mods_page.refresh()

    def _handle_navigation_request(self, key: str, args: dict) -> None:
        if key == "scan_trigger":
            self.start_scan_task()
        elif key == "check_updates":
            self.check_for_updates(manual=bool(args.get("manual")))
        else:
            self.sidebar.select_page("mods" if key == "build" else key)
            self._on_navigate(key, args)

    def check_for_updates(self, manual: bool = False) -> None:
        if self.ctx.tasks.is_running("Check for updates"):
            return
        include_beta = bool(CHANNEL)
        task = Task("Check for updates", lambda _ctx: updater.check_for_update(include_beta))

        def done(release):
            if release is None:
                self.settings_page.set_update_status("Up to date", "ok")
                if manual:
                    QMessageBox.information(self, "Updates", f"You are running the latest version ({display_version()}).")
                return
            self.settings_page.set_update_status(f"{release.version} available", "accent")
            if not manual and release.version == self.settings.skipped_update:
                return
            UpdateDialog(self.ctx, release, self).exec()

        def failed(message):
            self.settings_page.set_update_status("Check failed", "warn")
            if manual:
                QMessageBox.warning(self, "Updates", message)

        task.signals.finished.connect(done)
        task.signals.failed.connect(failed)
        self.ctx.tasks.start(task)

    def _after_update(self) -> None:
        """Brings the in-game menu and the Blender add-on up to the version that just got installed."""
        # Versions before 0.9.7 did not record themselves; a configured game folder means an update.
        previous = self.settings.last_run_version or ("an earlier version" if self.settings.game_dir else "")
        self.settings.last_run_version = VERSION
        self.settings.save()
        if not previous:
            return
        self.console.append("OK", f"Updated from {previous} to {VERSION}. Your settings and workspace were kept.")
        try:
            from blender.bridge_manager import BlenderBridgeManager
            refreshed = BlenderBridgeManager.get_instance(self.settings).refresh_installed_addons()
            if refreshed:
                self.console.append("OK", "Blender add-on updated. Restart Blender to load it.")
        except Exception as e:
            log.warning("Blender add-on refresh after update failed: %s", e)
        if not self.settings.game_dir:
            return
        from runtime_tools.manager import RuntimeManager
        from ui.pages.runtime_tools import game_running
        manager = RuntimeManager(Path(self.settings.game_dir), self.settings.workspace)
        if manager.status().state != "Update available":
            return
        if game_running() == "Running":
            self.console.append("WARN", "Close the game, then update the in-game menu under Settings > In-game menu.")
            return
        task = Task("Update in-game menu", lambda _ctx: manager.sync())
        task.signals.finished.connect(lambda _r: self.console.append("OK", "In-game menu updated. Restart the game to load it."))
        task.signals.failed.connect(lambda m: self.console.append("WARN", f"In-game menu not updated: {m}"))
        self.ctx.tasks.start(task)

    def _auto_detect_first_run(self) -> None:
        from kcd2.detect import detect_game_dir, detect_tools_dir, detect_blender_candidates
        found_game = detect_game_dir()
        found_tools = detect_tools_dir()
        found_blender = detect_blender_candidates()

        changed = False
        if found_game:
            self.settings.game_dir = str(found_game)
            log.info("Auto-detected KCD2: %s", found_game)
            changed = True
        if found_tools:
            self.settings.tools_dir = str(found_tools)
            log.info("Auto-detected KCD2 Modding Tools: %s", found_tools)
            changed = True
        if found_blender:
            self.settings.blender_exe = str(found_blender[0])
            log.info("Auto-detected Blender: %s", found_blender[0])
            changed = True

        if changed:
            self.settings.save()
            self.settings.ensure_workspace()
            self.ctx.settings_changed.emit()
            self.home_page.refresh()
            self.settings_page.load_from_config()

            # Offer to scan now if index is empty
            if self.ctx.index.stats()["assets"] == 0:
                res = QMessageBox.question(
                    self,
                    "KCD2 Installation Detected",
                    f"Found Kingdom Come: Deliverance II at:\n{self.settings.game_dir}\n\n"
                    "Would you like to scan game archives now to build the local asset index?",
                    QMessageBox.Yes | QMessageBox.No,
                    QMessageBox.Yes,
                )
                if res == QMessageBox.Yes:
                    self.start_scan_task()

    def start_scan_task(self, force: bool = False) -> None:
        if self.ctx.tasks.is_running("Scan Archives"):
            QMessageBox.information(self, "Task Running", "An archive scan is already in progress.")
            return

        if not self.settings.game_dir:
            QMessageBox.warning(self, "Missing Path", "Please set the KCD2 installation path in Settings first.")
            self.sidebar.select_page("settings")
            return

        task = Task("Scan Archives", scan, self.settings, force=force)

        # Wire task signals to UI console
        task.signals.progress.connect(self.console.set_progress)
        self.console.cancel_btn.clicked.connect(task.ctx.cancel)

        def on_finished(res):
            self.console.idle("Scan complete.")
            self.console.append(
                "OK",
                f"Scan finished in {res['seconds']}s! Indexed {res['assets']:,} assets across {res['archives']} archives."
            )
            self.ctx.index_changed.emit()
            self.home_page.refresh()
            self.browser_page.reload_archives()
            self.console.idle(f"Asset index updated: {res['assets']:,} assets available.")

        def on_failed(err_msg):
            self.console.idle("Scan stopped.")
            self.console.append("ERROR", f"Scan error: {err_msg}")
            QMessageBox.critical(self, "Scan Failed", err_msg)

        task.signals.finished.connect(on_finished)
        task.signals.failed.connect(on_failed)

        self.console.append("TASK", f"Starting scan of KCD2 archives from {self.settings.game_dir}...")
        self.ctx.tasks.start(task)

    def _handle_extract(self, rows: list[AssetRow], companions: bool, choose_dest: bool = False) -> None:
        if not rows:
            return

        dest = self.settings.workspace / "extracted"
        if choose_dest or self.settings.ask_extract_destination:
            chosen = QFileDialog.getExistingDirectory(self, "Select Extraction Folder", str(dest))
            if not chosen:
                return
            dest = Path(chosen)

        try:
            plan = build_plan(
                self.ctx.index,
                rows,
                dest,
                companions,
                protected_dirs=self.ctx.protected_dirs(),
            )
        except Exception as e:
            QMessageBox.critical(self, "Extraction Error", str(e))
            return

        conflicts = plan.conflicts()
        if conflicts:
            msg = (
                f"{len(conflicts)} file(s) already exist at the destination and differ in size.\n"
                "Overwrite them with original vanilla files?"
            )
            res = QMessageBox.warning(self, "Existing Files", msg, QMessageBox.Yes | QMessageBox.No, QMessageBox.No)
            if res != QMessageBox.Yes:
                return

        task = Task("Extract Assets", run_extraction, plan)
        task.signals.progress.connect(self.console.set_progress)
        self.console.cancel_btn.clicked.connect(task.ctx.cancel)

        def on_done(extracted_paths):
            self.console.idle("Extraction complete.")
            self.console.append(
                "OK",
                f"Successfully extracted {len(extracted_paths)} file(s) to:\n{dest}"
            )
            self.ctx.extracted.emit(extracted_paths)
            self.console.idle(f"Extracted {len(extracted_paths)} asset(s).")

        def on_failed(err_msg):
            self.console.idle("Extraction stopped.")
            self.console.append("ERROR", f"Extraction error: {err_msg}")
            QMessageBox.critical(self, "Extraction Failed", err_msg)

        task.signals.finished.connect(on_done)
        task.signals.failed.connect(on_failed)

        self.console.append("TASK", f"Extracting {len(plan.items)} asset(s) to {dest}...")
        self.ctx.tasks.start(task)

    def closeEvent(self, event: QCloseEvent) -> None:
        try:
            self.settings.window_geometry = self.saveGeometry().toHex().data().decode("ascii")
            if hasattr(self.browser_page, "saved_splitter_sizes") and self.browser_page.saved_splitter_sizes:
                self.settings.browser_splitter_sizes = self.browser_page.saved_splitter_sizes
            self.settings.console_collapsed = self.console.is_collapsed
            c_sizes = self.v_splitter.sizes()
            if len(c_sizes) >= 2 and c_sizes[1] > 40:
                self.settings.console_splitter_sizes = c_sizes
            self.settings.save()
        except Exception as e:
            log.debug("Settings save on close failed: %s", e)
        try:
            from blender.bridge_manager import BlenderBridgeManager
            BlenderBridgeManager.get_instance(self.settings).stop_ipc_server()
        except Exception:
            pass
        self.ctx.shutdown()
        event.accept()
