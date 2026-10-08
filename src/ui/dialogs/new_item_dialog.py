"""Pick an item type and a vanilla base item to start a new mod item from."""
from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QGuiApplication
from PySide6.QtWidgets import (
    QAbstractItemView,
    QButtonGroup,
    QComboBox,
    QDialog,
    QFormLayout,
    QHBoxLayout,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QRadioButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
)

from items.fields import CREATABLE_TYPES, field_info, headline_stats, type_label
from items.gamedata import ItemCatalog, VanillaItem
from items.models import MODE_NEW, MODE_OVERRIDE, GameItemDefinition, new_item_from_base
from ui.icons import get_svg_icon
from ui.widgets import button, configure_table, label
from workspace.asset_model import list_workspace_assets

TYPE_ICONS = {
    "MeleeWeapon": "weapon", "MissileWeapon": "bolt", "Ammo": "bolt", "Armor": "armor",
    "Helmet": "armor", "Hood": "armor", "Food": "beaker", "Ointment": "beaker", "Poison": "beaker",
    "Herb": "sparkles", "CraftingMaterial": "wrench", "QuickSlotContainer": "box", "MiscItem": "cube",
}


def compiled_models(workspace: Path) -> list[tuple[str, str, Path]]:
    """Workspace assets that contain a compiled CGF: (asset_id, name, cgf)."""
    result = []
    for asset in list_workspace_assets(workspace):
        folder = Path(asset.workspace_dir)
        for sub in ("source", "export", ""):
            hits = [p for p in (folder / sub).glob("*.cgf") if p.read_bytes()[:4] == b"CrCh"]
            if hits:
                result.append((asset.asset_id, asset.name, hits[0]))
                break
    return result


class NewItemDialog(QDialog):
    def __init__(self, catalog: ItemCatalog, store, workspace: Path, parent=None):
        super().__init__(parent)
        self.catalog = catalog
        self.store = store
        self.workspace = workspace
        self.result_item: GameItemDefinition | None = None
        self.setWindowTitle("Add item")
        self.setModal(True)
        screen = QGuiApplication.primaryScreen().availableGeometry()
        self.resize(min(1180, screen.width() - 80), min(760, screen.height() - 80))

        root = QVBoxLayout(self)
        root.setContentsMargins(24, 20, 24, 18)
        root.setSpacing(14)
        root.addWidget(label("Add item", "H1"))
        root.addWidget(label("Start from any item in the game. Every value is copied from it, "
                             "so the item works in-game right away and you only change what you need.",
                             "Dim", wrap=True))

        mode_row = QHBoxLayout()
        mode_row.setSpacing(18)
        self.rb_new = QRadioButton("Create a new item")
        self.rb_override = QRadioButton("Change an existing game item")
        self.rb_new.setChecked(True)
        group = QButtonGroup(self)
        group.addButton(self.rb_new)
        group.addButton(self.rb_override)
        self.rb_new.toggled.connect(self._mode_changed)
        mode_row.addWidget(self.rb_new)
        mode_row.addWidget(self.rb_override)
        mode_row.addStretch(1)
        root.addLayout(mode_row)

        body = QHBoxLayout()
        body.setSpacing(16)
        self.list_types = QListWidget()
        self.list_types.setFixedWidth(250)
        for tag in CREATABLE_TYPES:
            schema = catalog.schema(tag)
            if not schema or not schema.count:
                continue
            entry = QListWidgetItem(get_svg_icon(TYPE_ICONS.get(tag, "cube"), "#a2a8b5", 16),
                                    f"{type_label(tag)}")
            entry.setData(Qt.UserRole, tag)
            self.list_types.addItem(entry)
        self.list_types.currentRowChanged.connect(lambda _: self._refresh())
        body.addWidget(self.list_types)

        right = QVBoxLayout()
        right.setSpacing(10)
        self.txt_search = QLineEdit()
        self.txt_search.setObjectName("Search")
        self.txt_search.setPlaceholderText("Search base items by name…")
        self._search_timer = QTimer(self, singleShot=True, interval=180)
        self._search_timer.timeout.connect(self._refresh)
        self.txt_search.textChanged.connect(lambda _: self._search_timer.start())
        right.addWidget(self.txt_search)
        self.table = QTableWidget(0, 3)
        self.table.setHorizontalHeaderLabels(["Item", "Internal name", "Stats"])
        configure_table(self.table, stretch_column=0)
        self.table.setSelectionMode(QAbstractItemView.SingleSelection)
        self.table.itemSelectionChanged.connect(self._selection_changed)
        self.table.doubleClicked.connect(lambda _: self._accept())
        right.addWidget(self.table, 1)
        self.lbl_count = label("", "Muted")
        right.addWidget(self.lbl_count)
        body.addLayout(right, 1)
        root.addLayout(body, 1)

        form = QFormLayout()
        form.setHorizontalSpacing(16)
        form.setVerticalSpacing(10)
        self.txt_name = QLineEdit()
        self.txt_name.setPlaceholderText("e.g. Sword of the Rattay Guard")
        self.txt_name.textChanged.connect(lambda _: self._update_buttons())
        form.addRow("Display name", self.txt_name)
        self.cb_model = QComboBox()
        self.cb_model.addItem("Use the base item's model", None)
        for asset_id, name, cgf in compiled_models(workspace):
            self.cb_model.addItem(f"Workspace model: {name}  ({cgf.name})", (asset_id, cgf.name))
        form.addRow("Model", self.cb_model)
        root.addLayout(form)

        footer = QHBoxLayout()
        footer.addStretch(1)
        cancel = button("Cancel")
        cancel.clicked.connect(self.reject)
        footer.addWidget(cancel)
        self.btn_create = button("Create and edit", "plus", "Primary")
        self.btn_create.clicked.connect(self._accept)
        footer.addWidget(self.btn_create)
        root.addLayout(footer)

        self.list_types.setCurrentRow(0)
        self._update_buttons()

    def _mode_changed(self) -> None:
        new = self.rb_new.isChecked()
        self.txt_name.setEnabled(new)
        self.cb_model.setEnabled(new)
        self.btn_create.setText("Create and edit" if new else "Edit this item")
        self._update_buttons()

    def _current_type(self) -> str | None:
        entry = self.list_types.currentItem()
        return entry.data(Qt.UserRole) if entry else None

    def _refresh(self) -> None:
        tag = self._current_type()
        if not tag:
            return
        items = self.catalog.search(self.txt_search.text(), tag, limit=1500)
        stats = headline_stats(tag)
        self.table.setSortingEnabled(False)
        self.table.setRowCount(len(items))
        for row, item in enumerate(items):
            name = QTableWidgetItem(item.label)
            name.setData(Qt.UserRole, item.guid)
            self.table.setItem(row, 0, name)
            self.table.setItem(row, 1, QTableWidgetItem(item.name))
            parts = []
            for attr in stats:
                if attr in item.attrs:
                    info = field_info(attr)
                    try:
                        value = f"{float(item.attrs[attr]) / info.scale:g}"
                    except ValueError:
                        value = item.attrs[attr]
                    parts.append(f"{info.label} {value}")
            self.table.setItem(row, 2, QTableWidgetItem("   ".join(parts)))
        self.table.setSortingEnabled(True)
        self.lbl_count.setText(f"{len(items)} {type_label(tag).lower()} items")
        if items:
            self.table.selectRow(0)
        self._update_buttons()

    def _selected_base(self) -> VanillaItem | None:
        rows = self.table.selectionModel().selectedRows()
        if not rows:
            return None
        guid = self.table.item(rows[0].row(), 0).data(Qt.UserRole)
        return self.catalog.item(guid)

    def _selection_changed(self) -> None:
        base = self._selected_base()
        if base and self.rb_new.isChecked() and not self.txt_name.isModified():
            self.txt_name.setPlaceholderText(f"e.g. {base.label} (custom)")
        self._update_buttons()

    def _update_buttons(self) -> None:
        base = self._selected_base()
        ok = base is not None and (self.rb_override.isChecked() or bool(self.txt_name.text().strip()))
        self.btn_create.setEnabled(ok)

    def _accept(self) -> None:
        base = self._selected_base()
        if base is None:
            return
        if self.rb_override.isChecked():
            existing = {i.guid for i in self.store.items()}
            if base.guid in existing:
                self.txt_search.setFocus()
                self.lbl_count.setText("This game item is already changed by this mod. Edit it from the item list.")
                return
            item = new_item_from_base(base, self.store.unique_item_id(base.name), "", mode=MODE_OVERRIDE)
        else:
            display = self.txt_name.text().strip()
            item = new_item_from_base(base, self.store.unique_item_id(display), display, mode=MODE_NEW)
            model = self.cb_model.currentData()
            if model:
                asset_id, cgf_name = model
                folder = str(Path(base.attrs.get("Model", "manmade/weapons")).parent.as_posix())
                item.attributes["Model"] = f"{folder}/{cgf_name}" if folder not in ("", ".") else cgf_name
                item.workspace_asset_id = asset_id
        self.result_item = item
        self.accept()
