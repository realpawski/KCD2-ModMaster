"""Workspace assets: models you edit in Blender and their export state."""
from __future__ import annotations

import logging
import subprocess
from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QAbstractItemView,
    QComboBox,
    QDialog,
    QHBoxLayout,
    QLineEdit,
    QMenu,
    QMessageBox,
    QStackedWidget,
    QTableWidget,
    QTableWidgetItem,
    QWidget,
)

from blender.bridge_manager import BlenderBridgeManager
from compiler import compiled_models
from mods.project import ModManager
from ui import theme
from ui.context import AppContext
from ui.dialogs.new_asset_wizard import NewAssetWizard
from ui.widgets import EmptyState, PageHeader, button, configure_table, label, page_layout, set_cell_pill
from utils.helpers import reveal_in_explorer
from workspace.asset_model import AssetStatus, WorkspaceAsset, list_workspace_assets, validate_workspace_asset

log = logging.getLogger(__name__)

STATUS_STATE = {
    AssetStatus.READY.value: "ok",
    AssetStatus.BUILT.value: "info",
    AssetStatus.INSTALLED.value: "ok",
    AssetStatus.WARNING.value: "warn",
    AssetStatus.INVALID.value: "error",
    AssetStatus.EDITING.value: "muted",
}


class WorkspaceAssetsPage(QWidget):
    def __init__(self, ctx: AppContext, parent=None):
        super().__init__(parent)
        self.ctx = ctx
        self.bridge_mgr = BlenderBridgeManager.get_instance(self.ctx.settings)
        self.assets: list[WorkspaceAsset] = []
        self.owners: dict[str, list[str]] = {}

        lay = page_layout(self)
        header = PageHeader("Workspace Assets",
                            "Models you import, copy from the game or edit in Blender. Add them to a mod "
                            "to package them, and pick them as the model of a new item.")
        self.btn_refresh = header.add_action(button("Refresh", "arrow-path", tooltip="Reload assets from the workspace folder"))
        self.btn_refresh.clicked.connect(self.refresh)
        self.btn_new_asset = header.add_action(button("New asset", "plus", "Primary"))
        self.btn_new_asset.clicked.connect(self._open_new_asset_wizard)
        lay.addWidget(header)

        bar = QHBoxLayout()
        bar.setSpacing(10)
        self.txt_search = QLineEdit()
        self.txt_search.setPlaceholderText("Filter assets…")
        self.txt_search.setMaximumWidth(380)
        self.txt_search.textChanged.connect(self._apply_filter)
        bar.addWidget(self.txt_search)
        self.cb_status = QComboBox()
        self.cb_status.addItem("Any status", None)
        for s in AssetStatus:
            self.cb_status.addItem(s.value.title(), s.value)
        self.cb_status.currentIndexChanged.connect(self._apply_filter)
        bar.addWidget(self.cb_status)
        self.cb_mod_filter = QComboBox()
        self.cb_mod_filter.setMinimumWidth(180)
        self.cb_mod_filter.currentIndexChanged.connect(self._apply_filter)
        bar.addWidget(self.cb_mod_filter)
        bar.addStretch(1)
        self.lbl_count = label("", "Muted")
        bar.addWidget(self.lbl_count)
        lay.addLayout(bar)

        self.stack = QStackedWidget()
        self.table = QTableWidget(0, 6)
        self.table.setHorizontalHeaderLabels(["Asset", "Type", "Status", "In mods", "Blend file", "Export"])
        configure_table(self.table, stretch_column=0, row_height=38)
        self.table.setSelectionMode(QAbstractItemView.SingleSelection)
        self.table.itemSelectionChanged.connect(self._on_selection_changed)
        self.table.doubleClicked.connect(lambda _: self._open_selected_in_blender())
        self.stack.addWidget(self.table)
        empty = EmptyState("folder", "No workspace assets",
                           "Copy a model from the Asset Browser or import your own to start editing it in Blender.")
        new = button("New asset", "plus", "Primary")
        new.clicked.connect(self._open_new_asset_wizard)
        empty.actions.addWidget(new)
        self.stack.addWidget(empty)
        lay.addWidget(self.stack, 1)

        actions = QHBoxLayout()
        actions.setSpacing(8)
        self.btn_open_blender = button("Open in Blender", "blender")
        self.btn_open_blender.clicked.connect(self._open_selected_in_blender)
        self.btn_open_folder = button("Open folder", "folder")
        self.btn_open_folder.clicked.connect(self._open_selected_folder)
        self.btn_validate = button("Validate", "check-badge")
        self.btn_validate.clicked.connect(self._validate_selected)
        self.btn_add_to_mod = button("Add to mod", "puzzle")
        self.btn_add_to_mod.clicked.connect(self._add_to_mod_menu)
        for b in (self.btn_open_blender, self.btn_open_folder, self.btn_validate, self.btn_add_to_mod):
            actions.addWidget(b)
        actions.addStretch(1)
        lay.addLayout(actions)
        self._set_actions_enabled(False)
        self.ctx.mods_changed.connect(self.refresh)
        self.bridge_mgr.signals.asset_exported.connect(self._on_asset_exported)
        self.refresh()

    def _on_asset_exported(self, *_args) -> None:
        self.refresh()

    def showEvent(self, event) -> None:
        super().showEvent(event)
        self.refresh()

    def refresh(self) -> None:
        self.assets = list_workspace_assets(self.ctx.settings.workspace)
        mods = ModManager(self.ctx.settings.workspace).list_mods()
        self.owners = {}
        for mod in mods:
            for asset_id in mod.assets:
                self.owners.setdefault(asset_id, []).append(mod.name)
        current = self.cb_mod_filter.currentData()
        self.cb_mod_filter.blockSignals(True)
        self.cb_mod_filter.clear()
        self.cb_mod_filter.addItem("Any mod", None)
        self.cb_mod_filter.addItem("Not in a mod", "__none__")
        for mod in mods:
            self.cb_mod_filter.addItem(mod.name, mod.name)
        self.cb_mod_filter.setCurrentIndex(max(0, self.cb_mod_filter.findData(current)))
        self.cb_mod_filter.blockSignals(False)
        self._apply_filter()

    def _apply_filter(self) -> None:
        needle = self.txt_search.text().strip().lower()
        status = self.cb_status.currentData()
        mod = self.cb_mod_filter.currentData()
        rows = []
        for a in self.assets:
            owners = self.owners.get(a.asset_id, [])
            if needle and needle not in a.name.lower() and needle not in a.asset_id.lower():
                continue
            if status and a.status.upper() != status:
                continue
            if mod == "__none__" and owners:
                continue
            if mod and mod != "__none__" and mod not in owners:
                continue
            rows.append(a)
        self.lbl_count.setText(f"{len(rows)} of {len(self.assets)} assets")
        self.stack.setCurrentIndex(0 if self.assets else 1)
        self._populate_table(rows)

    def _populate_table(self, assets: list[WorkspaceAsset]) -> None:
        self.table.setRowCount(len(assets))
        for row, a in enumerate(assets):
            name = QTableWidgetItem(a.name)
            name.setData(Qt.UserRole, a.asset_id)
            name.setToolTip(a.workspace_dir)
            self.table.setItem(row, 0, name)
            self.table.setItem(row, 1, QTableWidgetItem(a.asset_type))
            set_cell_pill(self.table, row, 2, a.status.title(), STATUS_STATE.get(a.status, "muted"))
            self.table.setItem(row, 3, QTableWidgetItem(", ".join(self.owners.get(a.asset_id, [])) or "—"))
            has_blend = bool(a.blend_file and Path(a.blend_file).is_file())
            self.table.setItem(row, 4, QTableWidgetItem("Yes" if has_blend else "No"))
            models = compiled_models(Path(a.workspace_dir))
            if models:
                export = "Rigged (.skin)" if any(m.lower().endswith(".cdf") for m in models) else "Compiled (.cgf)"
            elif a.export_file and Path(a.export_file).is_file():
                export = "GLB only"
            else:
                export = "Not exported"
            self.table.setItem(row, 5, QTableWidgetItem(export))
        self._set_actions_enabled(False)

    def _on_selection_changed(self) -> None:
        self._set_actions_enabled(self._get_selected_asset() is not None)

    def _set_actions_enabled(self, enabled: bool) -> None:
        for b in (self.btn_open_blender, self.btn_open_folder, self.btn_validate, self.btn_add_to_mod):
            b.setEnabled(enabled)

    def _get_selected_asset(self) -> WorkspaceAsset | None:
        rows = self.table.selectionModel().selectedRows()
        if not rows:
            return None
        asset_id = self.table.item(rows[0].row(), 0).data(Qt.UserRole)
        return next((a for a in self.assets if a.asset_id == asset_id), None)

    def _open_new_asset_wizard(self) -> None:
        wizard = NewAssetWizard(self.ctx, self)
        if wizard.exec() == QDialog.Accepted and wizard.created_asset:
            self.refresh()

    def _open_selected_in_blender(self) -> None:
        asset = self._get_selected_asset()
        if not asset:
            return
        blender = self.ctx.settings.blender_exe
        if not blender or not Path(blender).is_file():
            QMessageBox.warning(self, "Blender not set up", "Set the Blender executable in Settings first.")
            return
        blend = Path(asset.blend_file) if asset.blend_file else None
        if blend and blend.is_file():
            subprocess.Popen([blender, str(blend)])
        else:
            QMessageBox.information(self, "No .blend file", f"No .blend file found in:\n{asset.workspace_dir}")

    def _open_selected_folder(self) -> None:
        asset = self._get_selected_asset()
        if asset and Path(asset.workspace_dir).is_dir():
            reveal_in_explorer(Path(asset.workspace_dir))

    def _validate_selected(self) -> None:
        asset = self._get_selected_asset()
        if not asset:
            return
        report = validate_workspace_asset(asset)
        asset.save()
        lines = [f"{i.severity.title()}: {i.message}" for i in report.issues] or ["No issues found."]
        box = QMessageBox.information if report.is_valid else QMessageBox.warning
        box(self, f"Validation — {asset.name}", "\n".join(lines))
        self.refresh()

    def _add_to_mod_menu(self) -> None:
        asset = self._get_selected_asset()
        if not asset:
            return
        menu = QMenu(self)
        manager = ModManager(self.ctx.settings.workspace)
        mods = manager.list_mods()
        for mod in mods:
            act = menu.addAction(mod.name)
            act.setCheckable(True)
            act.setChecked(asset.asset_id in mod.assets)
            act.triggered.connect(lambda checked, m=mod: self._toggle_membership(m, asset.asset_id, checked))
        if not mods:
            menu.addAction("Create a mod first").setEnabled(False)
        menu.exec(self.btn_add_to_mod.mapToGlobal(self.btn_add_to_mod.rect().bottomLeft()))

    def _toggle_membership(self, mod, asset_id: str, checked: bool) -> None:
        if checked:
            mod.assign_asset(asset_id)
        else:
            mod.remove_asset(asset_id)
        self.ctx.mods_changed.emit()
