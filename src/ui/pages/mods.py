"""Mods: projects, their items and assets, building and installing."""
from __future__ import annotations

import copy
import logging
import os
import time
from pathlib import Path

from PySide6.QtCore import QSize, Qt
from PySide6.QtWidgets import (
    QAbstractItemView,
    QApplication,
    QDialog,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMenu,
    QMessageBox,
    QPlainTextEdit,
    QStackedWidget,
    QTableWidget,
    QTableWidgetItem,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from core.tasks import Task
from items.fields import field_info, headline_stats, type_label
from items.gamedata import GameDataUnavailable
from items.models import MODE_OVERRIDE, new_guid
from items.store import ModItemStore, StoredItem
from items.validator import ERROR, validate_game_item
from mods.project import ModManager, ModProject
from runtime_tools.manager import RuntimeManager
from ui import theme
from ui.context import AppContext
from ui.dialogs.create_mod_dialog import CreateModDialog
from ui.dialogs.item_editor import ItemEditorDialog
from ui.dialogs.new_item_dialog import NewItemDialog
from ui.widgets import (
    EmptyState,
    PageHeader,
    StatusPill,
    button,
    configure_table,
    label,
    page_layout,
    set_cell_pill,
)
from utils.helpers import reveal_in_explorer
from workspace.asset_model import list_workspace_assets

log = logging.getLogger(__name__)
STEAM_RUN = "steam://rungameid/1771300"


def _stat_summary(item) -> str:
    parts = []
    for attr in headline_stats(item.item_type):
        if attr in item.attributes:
            info = field_info(attr)
            try:
                value = f"{float(item.attributes[attr]) / info.scale:g}"
            except ValueError:
                continue
            parts.append(f"{info.label} {value}")
    return "   ".join(parts)


class ModListEntry(QWidget):
    def __init__(self, mod: ModProject, item_count: int):
        super().__init__()
        lay = QVBoxLayout(self)
        lay.setContentsMargins(12, 9, 12, 9)
        lay.setSpacing(2)
        lay.addWidget(label(mod.name, "H3"))
        detail = f"{mod.id}  ·  v{mod.version}  ·  {item_count} item{'s' * (item_count != 1)}"
        lay.addWidget(label(detail, "Muted"))


class ModWorkspace(QWidget):
    def __init__(self, page: "ModsPage"):
        super().__init__()
        self.page = page
        self.ctx = page.ctx
        self.mod: ModProject | None = None
        self.stored: list[StoredItem] = []

        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(12)

        head = QHBoxLayout()
        head.setSpacing(8)
        info = QVBoxLayout()
        info.setSpacing(4)
        self.lbl_name = label("", "H2")
        self.lbl_name.setStyleSheet("font-size: 14pt;")
        info.addWidget(self.lbl_name)
        meta = QHBoxLayout()
        meta.setSpacing(8)
        self.pill_id = StatusPill("", "muted")
        self.pill_version = StatusPill("", "muted")
        self.pill_build = StatusPill("", "muted")
        meta.addWidget(self.pill_id)
        meta.addWidget(self.pill_version)
        meta.addWidget(self.pill_build)
        meta.addStretch(1)
        info.addLayout(meta)
        self.lbl_desc = label("", "Dim", wrap=True)
        info.addWidget(self.lbl_desc)
        head.addLayout(info, 1)

        self.btn_details = button("Details", "pencil")
        self.btn_details.clicked.connect(self._edit_details)
        self.btn_folder = button("Folder", "folder")
        self.btn_folder.clicked.connect(self._open_folder)
        self.btn_build = button("Build", "wrench")
        self.btn_build.clicked.connect(lambda: self._run_build(install=False))
        self.btn_install = button("Build & install", "arrow-down-tray", "Primary")
        self.btn_install.clicked.connect(lambda: self._run_build(install=True))
        self.btn_launch = button("Launch KCD2", "play")
        self.btn_launch.clicked.connect(self._launch)
        for b in (self.btn_details, self.btn_folder, self.btn_build, self.btn_install, self.btn_launch):
            head.addWidget(b, 0, Qt.AlignTop)
        lay.addLayout(head)

        self.tabs = QTabWidget()
        self.tabs.setDocumentMode(True)
        self.tabs.addTab(self._build_items_tab(), "Items")
        self.tabs.addTab(self._build_assets_tab(), "Assets")
        self.tabs.addTab(self._build_log_tab(), "Build log")
        lay.addWidget(self.tabs, 1)


    def _build_items_tab(self) -> QWidget:
        tab = QWidget()
        lay = QVBoxLayout(tab)
        lay.setContentsMargins(0, 12, 0, 0)
        lay.setSpacing(10)
        bar = QHBoxLayout()
        bar.setSpacing(8)
        self.txt_item_filter = QLineEdit()
        self.txt_item_filter.setPlaceholderText("Filter items…")
        self.txt_item_filter.setMaximumWidth(320)
        self.txt_item_filter.textChanged.connect(lambda _: self._fill_items())
        bar.addWidget(self.txt_item_filter)
        bar.addStretch(1)
        self.btn_edit_item = button("Edit", "pencil")
        self.btn_edit_item.clicked.connect(self._edit_item)
        self.btn_dup_item = button("Duplicate", "document-duplicate")
        self.btn_dup_item.clicked.connect(self._duplicate_item)
        self.btn_del_item = button("Delete", "trash", "Danger")
        self.btn_del_item.clicked.connect(self._delete_item)
        self.btn_add_item = button("Add item", "plus", "Primary")
        self.btn_add_item.clicked.connect(self._add_item)
        for b in (self.btn_edit_item, self.btn_dup_item, self.btn_del_item, self.btn_add_item):
            bar.addWidget(b)
        lay.addLayout(bar)

        self.items_stack = QStackedWidget()
        self.table_items = QTableWidget(0, 6)
        self.table_items.setHorizontalHeaderLabels(["Item", "Type", "Change", "Stats", "Based on", "Status"])
        configure_table(self.table_items, stretch_column=3, row_height=40)
        self.table_items.setSelectionMode(QAbstractItemView.SingleSelection)
        self.table_items.itemSelectionChanged.connect(self._update_item_buttons)
        self.table_items.doubleClicked.connect(lambda _: self._edit_item())
        self.items_stack.addWidget(self.table_items)
        self.items_empty = EmptyState(
            "sparkles", "No items yet",
            "Add a new weapon, armor piece, food or any other item, or change the stats of "
            "an item that already exists in the game.")
        add = button("Add item", "plus", "Primary")
        add.clicked.connect(self._add_item)
        self.items_empty.actions.addWidget(add)
        self.items_stack.addWidget(self.items_empty)
        lay.addWidget(self.items_stack, 1)
        return tab

    def _catalog(self, quiet: bool = False):
        try:
            QApplication.setOverrideCursor(Qt.WaitCursor)
            return self.ctx.item_catalog()
        except (GameDataUnavailable, OSError) as exc:
            if not quiet:
                QMessageBox.warning(self, "Game data unavailable", str(exc))
            return None
        finally:
            QApplication.restoreOverrideCursor()

    def _store(self) -> ModItemStore:
        return ModItemStore(self.mod, self.ctx.settings.workspace)

    def _fill_items(self) -> None:
        if not self.mod:
            return
        self.stored = self._store().list()
        catalog = self._catalog(quiet=True)
        needle = self.txt_item_filter.text().strip().lower()
        rows = [s for s in self.stored
                if not needle or needle in (s.item.display_name + " " + s.item.name).lower()]
        self.items_stack.setCurrentIndex(0 if self.stored else 1)
        self.table_items.setSortingEnabled(False)
        self.table_items.setRowCount(len(rows))
        for r, stored in enumerate(rows):
            item = stored.item
            name = QTableWidgetItem(item.display_name or item.name)
            name.setData(Qt.UserRole, item.item_id)
            name.setToolTip(f"{item.name}\n{item.guid}")
            self.table_items.setItem(r, 0, name)
            self.table_items.setItem(r, 1, QTableWidgetItem(type_label(item.item_type)))
            change = "Changes game item" if item.mode == MODE_OVERRIDE else "New item"
            self.table_items.setItem(r, 2, QTableWidgetItem(change))
            self.table_items.setItem(r, 3, QTableWidgetItem(_stat_summary(item)))
            base = catalog.item(item.base_guid) if catalog and item.base_guid else None
            self.table_items.setItem(r, 4, QTableWidgetItem(base.label if base else (item.base_name or "—")))
            if catalog is None:
                status = ("Game data missing", "muted")
            else:
                issues = validate_game_item(item, catalog, self.mod.id, stored.asset_dir)
                errors = sum(1 for i in issues if i.severity == ERROR)
                hints = len(issues) - errors
                if errors:
                    status = (f"{errors} error{'s' * (errors != 1)}", "error")
                elif hints:
                    status = (f"Ready · {hints} hint{'s' * (hints != 1)}", "warn")
                else:
                    status = ("Ready", "ok")
            set_cell_pill(self.table_items, r, 5, *status)
        self.table_items.setSortingEnabled(True)
        self.tabs.setTabText(0, f"Items  {len(self.stored)}")
        self._update_item_buttons()

    def _selected_stored(self) -> StoredItem | None:
        rows = self.table_items.selectionModel().selectedRows()
        if not rows:
            return None
        item_id = self.table_items.item(rows[0].row(), 0).data(Qt.UserRole)
        return next((s for s in self.stored if s.item.item_id == item_id), None)

    def _update_item_buttons(self) -> None:
        has = self._selected_stored() is not None
        for b in (self.btn_edit_item, self.btn_dup_item, self.btn_del_item):
            b.setEnabled(has)

    def _open_editor(self, stored_item, asset_dir) -> None:
        catalog = self._catalog()
        if catalog is None:
            return
        if catalog.schema(stored_item.item_type) is None:
            QMessageBox.warning(self, "Unknown item type",
                                f"{stored_item.item_type} does not exist in this game version.")
            return
        dlg = ItemEditorDialog(stored_item, catalog, self.mod.id, asset_dir, self)
        if dlg.exec() == QDialog.Accepted and dlg.saved:
            self._store().save(dlg.saved)
            self._fill_items()
            self.page.refresh_list(keep=self.mod.id)
            self._select_item(dlg.saved.item_id)

    def _select_item(self, item_id: str) -> None:
        for r in range(self.table_items.rowCount()):
            if self.table_items.item(r, 0).data(Qt.UserRole) == item_id:
                self.table_items.selectRow(r)
                return

    def _add_item(self) -> None:
        catalog = self._catalog()
        if catalog is None:
            return
        store = self._store()
        dlg = NewItemDialog(catalog, store, self.ctx.settings.workspace, self)
        if dlg.exec() == QDialog.Accepted and dlg.result_item:
            item = dlg.result_item
            store.save(item)
            self._fill_items()
            self.page.refresh_list(keep=self.mod.id)
            self._select_item(item.item_id)
            self._open_editor(item, store.asset_dir_for(item))

    def _edit_item(self) -> None:
        stored = self._selected_stored()
        if stored:
            self._open_editor(stored.item, stored.asset_dir)

    def _duplicate_item(self) -> None:
        stored = self._selected_stored()
        if not stored:
            return
        store = self._store()
        item = copy.deepcopy(stored.item)
        label_text = (item.display_name or item.name) + " (copy)"
        item.item_id = store.unique_item_id(label_text)
        item.name = item.item_id
        item.guid = new_guid()
        item.display_name = label_text
        item.ui_name = f"ui_nm_{item.item_id}"
        item.ui_info = f"ui_in_{item.item_id}"
        item.mode = "new"
        item.write_text = True
        item.created_at = item.updated_at = time.time()
        store.save(item)
        self._fill_items()
        self.page.refresh_list(keep=self.mod.id)
        self._select_item(item.item_id)

    def _delete_item(self) -> None:
        stored = self._selected_stored()
        if not stored:
            return
        name = stored.item.display_name or stored.item.name
        answer = QMessageBox.question(self, "Delete item",
                                      f"Delete '{name}' from {self.mod.name}?\n\n"
                                      "The game copy is updated the next time you build and install.")
        if answer == QMessageBox.Yes:
            self._store().delete(stored.item)
            self._fill_items()
            self.page.refresh_list(keep=self.mod.id)


    def _build_assets_tab(self) -> QWidget:
        tab = QWidget()
        lay = QVBoxLayout(tab)
        lay.setContentsMargins(0, 12, 0, 0)
        lay.setSpacing(10)
        bar = QHBoxLayout()
        bar.addWidget(label("Workspace assets packaged with this mod. Their compiled models can be used by items.",
                            "Dim"))
        bar.addStretch(1)
        self.btn_unassign = button("Remove from mod", "x-mark")
        self.btn_unassign.clicked.connect(self._unassign_asset)
        self.btn_assign = button("Add asset", "plus")
        self.btn_assign.clicked.connect(self._assign_menu)
        bar.addWidget(self.btn_unassign)
        bar.addWidget(self.btn_assign)
        lay.addLayout(bar)
        self.table_assets = QTableWidget(0, 3)
        self.table_assets.setHorizontalHeaderLabels(["Asset", "Type", "Status"])
        configure_table(self.table_assets, stretch_column=0)
        self.table_assets.itemSelectionChanged.connect(
            lambda: self.btn_unassign.setEnabled(bool(self.table_assets.selectionModel().selectedRows())))
        lay.addWidget(self.table_assets, 1)
        return tab

    def _fill_assets(self) -> None:
        assets = {a.asset_id: a for a in list_workspace_assets(self.ctx.settings.workspace)}
        ids = list(self.mod.assets)
        self.table_assets.setRowCount(len(ids))
        for r, asset_id in enumerate(ids):
            asset = assets.get(asset_id)
            name = QTableWidgetItem(asset.name if asset else asset_id)
            name.setData(Qt.UserRole, asset_id)
            self.table_assets.setItem(r, 0, name)
            self.table_assets.setItem(r, 1, QTableWidgetItem(asset.asset_type if asset else "—"))
            self.table_assets.setItem(r, 2, QTableWidgetItem(asset.status.title() if asset else "Missing"))
        self.tabs.setTabText(1, f"Assets  {len(ids)}")
        self.btn_unassign.setEnabled(False)

    def _assign_menu(self) -> None:
        menu = QMenu(self)
        available = [a for a in list_workspace_assets(self.ctx.settings.workspace)
                     if a.asset_id not in self.mod.assets]
        for asset in available:
            menu.addAction(asset.name, lambda a=asset.asset_id: self._assign(a))
        if not available:
            menu.addAction("No unassigned workspace assets").setEnabled(False)
        menu.exec(self.btn_assign.mapToGlobal(self.btn_assign.rect().bottomLeft()))

    def _assign(self, asset_id: str) -> None:
        self.mod.assign_asset(asset_id)
        self.load(self.mod)
        self.page.refresh_list(keep=self.mod.id)

    def _unassign_asset(self) -> None:
        rows = self.table_assets.selectionModel().selectedRows()
        if rows:
            self.mod.remove_asset(self.table_assets.item(rows[0].row(), 0).data(Qt.UserRole))
            self.load(self.mod)
            self.page.refresh_list(keep=self.mod.id)


    def _build_log_tab(self) -> QWidget:
        tab = QWidget()
        lay = QVBoxLayout(tab)
        lay.setContentsMargins(0, 12, 0, 0)
        self.txt_log = QPlainTextEdit()
        self.txt_log.setObjectName("Log")
        self.txt_log.setReadOnly(True)
        self.txt_log.setPlaceholderText("Build and install results appear here.")
        lay.addWidget(self.txt_log, 1)
        return tab

    def _log(self, text: str) -> None:
        self.txt_log.appendPlainText(f"[{time.strftime('%H:%M:%S')}] {text}")

    def _set_busy(self, busy: bool) -> None:
        for b in (self.btn_build, self.btn_install, self.btn_details):
            b.setEnabled(not busy)
        if busy:
            self.pill_build.set("Building…", "accent")

    def _run_build(self, install: bool) -> None:
        if not self.mod:
            return
        if not self.ctx.settings.game_dir:
            QMessageBox.warning(self, "Game folder missing", "Set the Kingdom Come: Deliverance II folder in Settings.")
            return
        manager = RuntimeManager(Path(self.ctx.settings.game_dir), self.ctx.settings.workspace)
        mod = self.mod
        self._set_busy(True)
        self.tabs.setCurrentIndex(2)
        self._log(f"{'Building and installing' if install else 'Building'} {mod.name} {mod.version}…")

        def work(_ctx):
            return manager.build_install(mod) if install else manager.build_project(mod)

        task = Task("Build mod", work)

        def done(path):
            self._set_busy(False)
            if install:
                self._log(f"Installed to {path}. Restart the game to load the changes.")
                self.pill_build.set("Installed", "ok")
            else:
                self._log(f"Build ready in {path}.")
                self.pill_build.set("Built", "ok")

        def failed(message):
            self._set_busy(False)
            self._log(f"Failed: {message}")
            self.pill_build.set("Build failed", "error")
            QMessageBox.warning(self, "Build failed", message)

        task.signals.finished.connect(done)
        task.signals.failed.connect(failed)
        self.ctx.tasks.start(task)

    def _launch(self) -> None:
        os.startfile(STEAM_RUN)


    def _edit_details(self) -> None:
        dlg = CreateModDialog(self.ctx, self, mod=self.mod)
        if dlg.exec() == QDialog.Accepted:
            self.load(self.mod)
            self.page.refresh_list(keep=self.mod.id)

    def _open_folder(self) -> None:
        if self.mod and Path(self.mod.project_dir).is_dir():
            reveal_in_explorer(Path(self.mod.project_dir))

    def load(self, mod: ModProject) -> None:
        changed = self.mod is None or self.mod.id != mod.id
        self.mod = mod
        self.lbl_name.setText(mod.name)
        self.pill_id.set(mod.id, "muted")
        self.pill_version.set(f"v{mod.version}", "muted")
        self.lbl_desc.setText(mod.description or "No description.")
        installed = Path(self.ctx.settings.game_dir or ".") / "Mods" / mod.id / "mod.manifest"
        if installed.is_file():
            self.pill_build.set("Installed", "ok")
        elif (Path(mod.project_dir) / "build" / mod.id).is_dir():
            self.pill_build.set("Built", "info")
        else:
            self.pill_build.set("Not built", "muted")
        if changed:
            self.txt_log.clear()
            self.txt_item_filter.clear()
        self._fill_items()
        self._fill_assets()


class ModsPage(QWidget):
    def __init__(self, ctx: AppContext, parent=None):
        super().__init__(parent)
        self.ctx = ctx
        self.mod_mgr = ModManager(self.ctx.settings.workspace)
        lay = page_layout(self)

        self.header = PageHeader("Mods", "Create mods, add or change items, then build and install "
                                          "them into the game. Everything stays editable.")
        btn_new = self.header.add_action(button("New mod", "plus", "Primary"))
        btn_new.clicked.connect(self._create_mod)
        lay.addWidget(self.header)

        body = QHBoxLayout()
        body.setSpacing(20)
        left = QVBoxLayout()
        left.setSpacing(8)
        self.txt_filter = QLineEdit()
        self.txt_filter.setPlaceholderText("Filter mods…")
        self.txt_filter.textChanged.connect(lambda _: self.refresh_list())
        left.addWidget(self.txt_filter)
        self.list_mods = QListWidget()
        self.list_mods.setObjectName("ModList")
        self.list_mods.setFixedWidth(300)
        self.list_mods.currentItemChanged.connect(self._on_mod_selected)
        left.addWidget(self.list_mods, 1)
        body.addLayout(left)

        self.stack = QStackedWidget()
        self.workspace = ModWorkspace(self)
        self.empty = EmptyState("puzzle", "Create your first mod",
                                "A mod bundles new and changed items, models and textures. "
                                "ModMaster builds it into a package the game loads from its Mods folder.")
        first = button("New mod", "plus", "Primary")
        first.clicked.connect(self._create_mod)
        self.empty.actions.addWidget(first)
        self.stack.addWidget(self.workspace)
        self.stack.addWidget(self.empty)
        body.addWidget(self.stack, 1)
        lay.addLayout(body, 1)
        self.refresh()

    def refresh(self) -> None:
        self.mod_mgr = ModManager(self.ctx.settings.workspace)
        self.refresh_list(keep=self.workspace.mod.id if self.workspace.mod else None)

    def refresh_list(self, keep: str | None = None) -> None:
        needle = self.txt_filter.text().strip().lower()
        mods = [m for m in self.mod_mgr.list_mods()
                if not needle or needle in m.name.lower() or needle in m.id]
        self.list_mods.blockSignals(True)
        self.list_mods.clear()
        selected_row = 0
        for row, mod in enumerate(mods):
            count = len(ModItemStore(mod, self.ctx.settings.workspace).list())
            entry = QListWidgetItem()
            entry.setData(Qt.UserRole, mod.id)
            widget = ModListEntry(mod, count)
            entry.setSizeHint(QSize(0, 62))
            self.list_mods.addItem(entry)
            self.list_mods.setItemWidget(entry, widget)
            if mod.id == keep:
                selected_row = row
        self.list_mods.blockSignals(False)
        if mods:
            self.stack.setCurrentIndex(0)
            self.list_mods.setCurrentRow(selected_row)
            self._on_mod_selected(self.list_mods.currentItem(), None)
        else:
            self.stack.setCurrentIndex(1)

    def _on_mod_selected(self, current, _previous) -> None:
        if current is None:
            return
        mod = self.mod_mgr.get_mod(current.data(Qt.UserRole))
        if mod:
            self.workspace.load(mod)

    def select_mod(self, mod_id: str) -> None:
        self.refresh_list(keep=mod_id)

    def _create_mod(self) -> None:
        dlg = CreateModDialog(self.ctx, self)
        if dlg.exec() == QDialog.Accepted and dlg.created_mod:
            self.ctx.mods_changed.emit()
            self.refresh_list(keep=dlg.created_mod.id)
