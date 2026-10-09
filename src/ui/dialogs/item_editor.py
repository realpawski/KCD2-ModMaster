"""Editor for one game item: every attribute of its type, grouped and validated live."""
from __future__ import annotations

import copy
from pathlib import Path

from PySide6.QtCore import QLocale, Qt, QTimer
from PySide6.QtGui import QGuiApplication, QPixmap
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QDoubleSpinBox,
    QFileDialog,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QPlainTextEdit,
    QScrollArea,
    QSpinBox,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from items.fields import GROUP_ORDER, IDENTITY_ATTRS, field_info, type_label
from items.gamedata import AttrSpec, ItemCatalog
from items.models import MODE_OVERRIDE, GameItemDefinition, format_number
from items.validator import ERROR, validate_game_item
from items.icons import ICON_HINT, ICON_SIZE, icon_id, store_icon
from ui.dialogs.new_item_dialog import compiled_models, item_model
from ui import theme
from ui.icons import get_svg_icon
from ui.widgets import StatusPill, button, label

NUM_MIN = -1_000_000
NUM_MAX = 100_000_000
MANAGED_ATTRS = set(IDENTITY_ATTRS)


def _refresh_style(widget: QWidget) -> None:
    widget.style().unpolish(widget)
    widget.style().polish(widget)


class NumberSpin(QDoubleSpinBox):
    def textFromValue(self, value: float) -> str:
        text = f"{value:.{self.decimals()}f}"
        return text.rstrip("0").rstrip(".") if "." in text else text


class AttrEditor:
    """One attribute row: editor widget plus vanilla range, base value and delta."""

    def __init__(self, name: str, spec: AttrSpec, value: str, base_value: str | None, on_change):
        self.name = name
        self.spec = spec
        self.info = field_info(name)
        self.original = value
        self.base_value = base_value
        self.on_change = on_change
        self.touched = False
        self.widget = self._make_editor(value)
        self.hint = label("", "Muted")
        self.delta = QLabel()
        self.delta.setMinimumWidth(70)
        self.title = label(self.info.label)
        self.title.setToolTip(self.info.help or name)
        self.widget.setToolTip(f"{name}\n{self.info.help}".strip())
        self._update_hint()

    def _make_editor(self, value: str) -> QWidget:
        if self.spec.is_bool:
            box = QCheckBox()
            box.setChecked(value == "true")
            box.toggled.connect(self._changed)
            return box
        if self.spec.numeric:
            scale = self.info.scale
            if self.spec.numeric == "int" and scale == 1.0:
                spin = QSpinBox()
                spin.setRange(-2_000_000_000, 2_000_000_000)
                spin.setValue(int(float(value or 0)))
                spin.valueChanged.connect(self._changed)
            else:
                spin = NumberSpin()
                spin.setDecimals(1 if scale != 1.0 else 4)
                spin.setRange(NUM_MIN, NUM_MAX)
                spin.setSingleStep(1 if scale != 1.0 else 0.05)
                spin.setValue(float(value or 0) / scale)
                spin.valueChanged.connect(self._changed)
            spin.setLocale(QLocale.c())
            if self.info.unit:
                spin.setSuffix(f" {self.info.unit}")
            spin.setFixedWidth(180)
            spin.setKeyboardTracking(False)
            return spin
        edit = QLineEdit(value)
        edit.textEdited.connect(self._changed)
        edit.setMinimumWidth(320)
        return edit

    def value(self) -> str:
        w = self.widget
        if isinstance(w, QCheckBox):
            return "true" if w.isChecked() else "false"
        if isinstance(w, (QSpinBox, QDoubleSpinBox)):
            if not self.touched:
                return self.original
            raw = w.value() * self.info.scale
            return format_number(raw, self.spec.numeric)
        return w.text().strip()

    def set_value(self, value: str) -> None:
        w = self.widget
        w.blockSignals(True)
        if isinstance(w, QCheckBox):
            w.setChecked(value == "true")
        elif isinstance(w, (QSpinBox, QDoubleSpinBox)):
            number = float(value or 0) / self.info.scale
            w.setValue(int(number) if isinstance(w, QSpinBox) else number)
        else:
            w.setText(value)
        w.blockSignals(False)
        self.original = value
        self.touched = False
        self._update_hint()

    def _changed(self, *_):
        self.touched = True
        self._update_hint()
        self.on_change()

    def _fmt(self, raw: str) -> str:
        try:
            number = float(raw) / self.info.scale
        except (TypeError, ValueError):
            return raw
        return f"{number:g}"

    def _update_hint(self) -> None:
        parts = []
        if self.spec.numeric and self.spec.lo is not None:
            lo = self.spec.lo / self.info.scale
            hi = self.spec.hi / self.info.scale
            parts.append(f"Vanilla {lo:g} – {hi:g}")
        if self.base_value is not None:
            parts.append(f"Base {self._fmt(self.base_value)}")
        self.hint.setText("   ·   ".join(parts))
        changed = self.base_value is not None and self.value() != self.base_value
        self.widget.setProperty("changed", changed)
        _refresh_style(self.widget)
        if changed and self.spec.numeric:
            try:
                diff = (float(self.value()) - float(self.base_value)) / self.info.scale
                self.delta.setText(f"{diff:+g}")
                color = theme.OK if diff > 0 else theme.WARN
                self.delta.setStyleSheet(f"color: {color}; font-weight: 700;")
            except ValueError:
                self.delta.setText("")
        elif changed:
            self.delta.setText("changed")
            self.delta.setStyleSheet(f"color: {theme.ACCENT}; font-weight: 600;")
        else:
            self.delta.setText("")

    def set_invalid(self, invalid: bool) -> None:
        self.widget.setProperty("invalid", invalid)
        _refresh_style(self.widget)


class ItemEditorDialog(QDialog):
    def __init__(self, item: GameItemDefinition, catalog: ItemCatalog, mod_id: str,
                 asset_dir=None, parent=None, workspace=None, project_dir=None):
        super().__init__(parent)
        self.workspace = workspace
        self.project_dir = project_dir
        self.item = copy.deepcopy(item)
        self.catalog = catalog
        self.mod_id = mod_id
        self.asset_dir = asset_dir
        self.schema = catalog.schema(item.item_type)
        self.base = catalog.item(item.base_guid) if item.base_guid else None
        self.editors: dict[str, AttrEditor] = {}
        self.saved: GameItemDefinition | None = None

        self.setWindowTitle(f"Edit item — {item.display_name or item.name}")
        self.setModal(True)
        screen = QGuiApplication.primaryScreen().availableGeometry()
        self.resize(min(1240, screen.width() - 80), min(820, screen.height() - 80))

        root = QVBoxLayout(self)
        root.setContentsMargins(24, 20, 24, 18)
        root.setSpacing(14)
        root.addLayout(self._build_header())

        body = QHBoxLayout()
        body.setSpacing(18)
        self.tabs = QTabWidget()
        self.tabs.setDocumentMode(True)
        body.addWidget(self.tabs, 1)
        body.addWidget(self._build_validation_panel())
        root.addLayout(body, 1)
        root.addLayout(self._build_footer())

        self._build_general_tab()
        self._build_attribute_tabs()

        self._validate_timer = QTimer(self, singleShot=True, interval=150)
        self._validate_timer.timeout.connect(self._validate)
        self._validate()


    def _build_header(self) -> QHBoxLayout:
        row = QHBoxLayout()
        row.setSpacing(10)
        col = QVBoxLayout()
        col.setSpacing(4)
        self.lbl_title = label(self.item.display_name or self.item.name, "H1")
        col.addWidget(self.lbl_title)
        meta = QHBoxLayout()
        meta.setSpacing(8)
        meta.addWidget(StatusPill(type_label(self.item.item_type), "accent"))
        if self.item.mode == MODE_OVERRIDE:
            meta.addWidget(StatusPill("Changes a game item", "info"))
        else:
            meta.addWidget(StatusPill("New item", "ok"))
        if self.item.uses_custom_model:
            meta.addWidget(StatusPill("Custom model", "muted"))
        if self.base:
            meta.addWidget(label(f"Based on {self.base.label}  ·  {self.base.name}", "Muted"))
        meta.addStretch(1)
        col.addLayout(meta)
        row.addLayout(col, 1)
        return row

    def _build_validation_panel(self) -> QWidget:
        panel = QWidget()
        panel.setFixedWidth(320)
        lay = QVBoxLayout(panel)
        lay.setContentsMargins(0, 8, 0, 0)
        lay.setSpacing(8)
        lay.addWidget(label("VALIDATION", "Section"))
        self.pill_validation = StatusPill("Checking…", "muted")
        lay.addWidget(self.pill_validation)
        self.list_issues = QListWidget()
        self.list_issues.setWordWrap(True)
        self.list_issues.itemClicked.connect(self._focus_issue)
        lay.addWidget(self.list_issues, 1)
        hint = label("Checks run against the item schema shipped with your copy of the game. "
                     "Errors block the build; warnings are balance hints.", "Muted", wrap=True)
        lay.addWidget(hint)
        return panel

    def _build_footer(self) -> QHBoxLayout:
        row = QHBoxLayout()
        row.setSpacing(8)
        self.btn_reset = button("Reset to base item", "arrow-path", "Ghost")
        self.btn_reset.setEnabled(self.base is not None)
        self.btn_reset.clicked.connect(self._reset_to_base)
        row.addWidget(self.btn_reset)
        row.addStretch(1)
        cancel = button("Cancel")
        cancel.clicked.connect(self.reject)
        row.addWidget(cancel)
        self.btn_save = button("Save item", "check", "Primary")
        self.btn_save.setDefault(True)
        self.btn_save.clicked.connect(self._save)
        row.addWidget(self.btn_save)
        return row

    def _scroll_page(self) -> tuple[QScrollArea, QGridLayout]:
        holder = QWidget()
        grid = QGridLayout(holder)
        grid.setContentsMargins(4, 16, 12, 16)
        grid.setHorizontalSpacing(16)
        grid.setVerticalSpacing(12)
        grid.setColumnMinimumWidth(0, 190)
        grid.setColumnStretch(3, 1)
        area = QScrollArea()
        area.setWidgetResizable(True)
        area.setWidget(holder)
        return area, grid

    def _build_general_tab(self) -> None:
        area, grid = self._scroll_page()
        r = 0
        new_item = self.item.mode != MODE_OVERRIDE

        self.txt_display = QLineEdit(self.item.display_name)
        self.txt_display.setPlaceholderText("Name shown in the inventory")
        self.txt_display.textEdited.connect(self._on_text_changed)
        grid.addWidget(label("Display name"), r, 0)
        grid.addWidget(self.txt_display, r, 1, 1, 3)
        r += 1

        self.txt_description = QPlainTextEdit(self.item.description)
        self.txt_description.setFixedHeight(96)
        self.txt_description.textChanged.connect(self._on_text_changed)
        grid.addWidget(label("Description"), r, 0, Qt.AlignTop)
        grid.addWidget(self.txt_description, r, 1, 1, 3)
        r += 1

        if not new_item:
            note = label("Name and description stay as in the game unless you change them here.", "Muted")
            grid.addWidget(note, r, 1, 1, 3)
            r += 1

        self.txt_name = QLineEdit(self.item.name)
        self.txt_name.setReadOnly(not new_item)
        self.txt_name.setToolTip("Internal name used by the game and by inventory presets.")
        self.txt_name.textEdited.connect(self._schedule_validation)
        self.txt_name.setMinimumWidth(340)
        grid.addWidget(label("Internal name"), r, 0)
        grid.addWidget(self.txt_name, r, 1, 1, 2, Qt.AlignLeft)
        r += 1

        guid_row = QHBoxLayout()
        self.txt_guid = QLineEdit(self.item.guid)
        self.txt_guid.setReadOnly(True)
        self.txt_guid.setMinimumWidth(340)
        self.txt_guid.setCursorPosition(0)
        guid_row.setSpacing(8)
        guid_row.addWidget(self.txt_guid)
        copy_btn = button("Copy", "document-duplicate", "Ghost")
        copy_btn.clicked.connect(lambda: QGuiApplication.clipboard().setText(self.item.guid))
        guid_row.addWidget(copy_btn)
        guid_row.addStretch(1)
        grid.addWidget(label("GUID"), r, 0)
        grid.addLayout(guid_row, r, 1, 1, 2)
        r += 1

        if new_item and self.workspace is not None:
            self.cb_model = QComboBox()
            self.cb_model.setMinimumWidth(340)
            base_model = self.base.attrs.get("Model", "") if self.base else ""
            self.cb_model.addItem(f"Base item's model  ({Path(base_model).name or 'none'})", ("", base_model))
            for asset_id, title, model in compiled_models(self.workspace):
                self.cb_model.addItem(f"Workspace model: {title}", (asset_id, item_model(base_model, model)))
            current = next((i for i in range(self.cb_model.count())
                            if self.cb_model.itemData(i)[0] == self.item.workspace_asset_id), 0)
            self.cb_model.setCurrentIndex(current)
            self.cb_model.currentIndexChanged.connect(self._model_changed)
            grid.addWidget(label("Model"), r, 0)
            grid.addWidget(self.cb_model, r, 1, 1, 2, Qt.AlignLeft)
            r += 1
            grid.addWidget(label("Your model is held like the base item, so keep its grip where the base "
                                 "item's grip is.", "Muted", wrap=True), r, 1, 1, 3)
            r += 1

        if new_item and self.project_dir is not None:
            icon_row = QHBoxLayout()
            icon_row.setSpacing(10)
            self.lbl_icon = QLabel()
            self.lbl_icon.setFixedSize(ICON_SIZE * 2 + 4, ICON_SIZE * 2 + 4)
            self.lbl_icon.setAlignment(Qt.AlignCenter)
            self.lbl_icon.setStyleSheet(f"background: #0d0f14; border: 1px solid {theme.BORDER}; border-radius: 6px;")
            icon_row.addWidget(self.lbl_icon)
            icon_buttons = QVBoxLayout()
            choose = button("Choose image…", "photo")
            choose.clicked.connect(self._choose_icon)
            self.btn_icon_reset = button("Use base item's icon", "arrow-path", "Ghost")
            self.btn_icon_reset.clicked.connect(self._reset_icon)
            icon_buttons.addWidget(choose)
            icon_buttons.addWidget(self.btn_icon_reset)
            icon_buttons.addWidget(label(ICON_HINT, "Muted", wrap=True))
            icon_buttons.addStretch(1)
            icon_row.addLayout(icon_buttons, 1)
            grid.addWidget(label("Inventory icon"), r, 0, Qt.AlignTop)
            grid.addLayout(icon_row, r, 1, 1, 3)
            r += 1
            self._show_icon()

        self.chk_inventory = QCheckBox("Add one to Henry's starting inventory (new games)")
        self.chk_inventory.setChecked(self.item.add_to_player_inventory)
        self.chk_inventory.setEnabled(new_item)
        grid.addWidget(label("Starting inventory"), r, 0)
        grid.addWidget(self.chk_inventory, r, 1, 1, 3)
        r += 1

        add_row = QHBoxLayout()
        add_row.setSpacing(8)
        self.cb_add_attr = QComboBox()
        self.cb_add_attr.setMinimumWidth(340)
        self._fill_optional_attrs()
        add_row.addWidget(self.cb_add_attr)
        btn_add = button("Add field", "plus")
        btn_add.clicked.connect(self._add_optional_attr)
        add_row.addWidget(btn_add)
        add_row.addStretch(1)
        grid.addWidget(label("Optional fields"), r, 0)
        grid.addLayout(add_row, r, 1, 1, 3)
        r += 1
        grid.setRowStretch(r, 1)
        self.tabs.addTab(area, "General")

    def _show_icon(self) -> None:
        path = Path(self.project_dir) / self.item.icon_image if self.item.icon_image else None
        if path is not None and path.is_file():
            pixmap = QPixmap(str(path)).scaled(ICON_SIZE * 2, ICON_SIZE * 2, Qt.KeepAspectRatio,
                                               Qt.FastTransformation)
            self.lbl_icon.setPixmap(pixmap)
            self.btn_icon_reset.setEnabled(True)
        else:
            self.lbl_icon.setPixmap(QPixmap())
            self.lbl_icon.setText("Game\nicon")
            self.btn_icon_reset.setEnabled(False)

    def _set_icon_id(self, value: str) -> None:
        self.item.attributes["IconId"] = value
        if "IconId" in self.editors:
            self.editors["IconId"].set_value(value)
            self.editors["IconId"].touched = True

    def _choose_icon(self) -> None:
        source, _ = QFileDialog.getOpenFileName(self, "Choose an inventory icon", "",
                                                "Images (*.png *.jpg *.jpeg *.webp *.bmp *.tga)")
        if not source:
            return
        try:
            self.item.icon_image = store_icon(Path(source), Path(self.project_dir), self.item.item_id)
        except (OSError, ValueError) as exc:
            QMessageBox.warning(self, "Inventory icon", f"The image could not be read:\n{exc}")
            return
        self._set_icon_id(icon_id(self.mod_id, self.item.item_id))
        self._show_icon()
        self._schedule_validation()

    def _reset_icon(self) -> None:
        self.item.icon_image = ""
        self._set_icon_id(self.base.attrs.get("IconId", "") if self.base else "")
        self._show_icon()
        self._schedule_validation()

    def _model_changed(self) -> None:
        asset_id, model = self.cb_model.currentData()
        self.item.workspace_asset_id = asset_id
        self.asset_dir = Path(self.workspace) / "Assets" / asset_id if asset_id else None
        if "Model" in self.editors:
            self.editors["Model"].set_value(model)
            self.editors["Model"].touched = True
        self.item.attributes["Model"] = model
        self._schedule_validation()

    def _fill_optional_attrs(self) -> None:
        self.cb_add_attr.clear()
        missing = [a for a in self.schema.attrs if a not in self.item.attributes and a not in MANAGED_ATTRS]
        for name in sorted(missing, key=lambda n: field_info(n).label.lower()):
            self.cb_add_attr.addItem(f"{field_info(name).label}  ({name})", name)
        self.cb_add_attr.setEnabled(bool(missing))

    def _build_attribute_tabs(self) -> None:
        while self.tabs.count() > 1:
            self.tabs.removeTab(1)
        self.editors.clear()
        groups: dict[str, list[str]] = {}
        for name in self.item.attributes:
            if name in MANAGED_ATTRS:
                continue
            groups.setdefault(field_info(name).group, []).append(name)
        for group in GROUP_ORDER:
            names = groups.get(group)
            if not names:
                continue
            area, grid = self._scroll_page()
            for row, name in enumerate(names):
                spec = self.schema.attrs.get(name) or AttrSpec(name)
                base_value = self.base.attrs.get(name) if self.base else None
                editor = AttrEditor(name, spec, self.item.attributes[name], base_value,
                                    self._schedule_validation)
                self.editors[name] = editor
                grid.addWidget(editor.title, row, 0)
                grid.addWidget(editor.widget, row, 1)
                grid.addWidget(editor.delta, row, 2)
                grid.addWidget(editor.hint, row, 3)
            grid.setRowStretch(len(names), 1)
            self.tabs.addTab(area, group.replace("&", "&&"))


    def _on_text_changed(self, *_):
        self.lbl_title.setText(self.txt_display.text().strip() or self.item.name)
        self._schedule_validation()

    def _schedule_validation(self, *_):
        self._validate_timer.start()

    def _add_optional_attr(self) -> None:
        name = self.cb_add_attr.currentData()
        if not name:
            return
        self._collect()
        spec = self.schema.attrs.get(name)
        default = "false" if spec and spec.is_bool else ("0" if spec and spec.numeric else "")
        self.item.attributes[name] = default
        current = self.tabs.currentIndex()
        self._build_attribute_tabs()
        self._fill_optional_attrs()
        self.tabs.setCurrentIndex(current)
        self._validate()

    def _collect(self) -> GameItemDefinition:
        item = self.item
        item.display_name = self.txt_display.text().strip()
        item.description = self.txt_description.toPlainText().strip()
        if item.mode != MODE_OVERRIDE:
            item.name = self.txt_name.text().strip()
        item.add_to_player_inventory = self.chk_inventory.isChecked()
        for name, editor in self.editors.items():
            item.attributes[name] = editor.value()
        if item.mode == MODE_OVERRIDE and self.base:
            item.write_text = (item.display_name != self.base.display or item.description != self.base.info)
        return item

    def _validate(self) -> list:
        item = self._collect()
        issues = validate_game_item(item, self.catalog, self.mod_id, self.asset_dir)
        self.list_issues.clear()
        bad_attrs = {i.attribute for i in issues if i.severity == ERROR}
        for name, editor in self.editors.items():
            editor.set_invalid(name in bad_attrs)
        errors = [i for i in issues if i.severity == ERROR]
        warnings = [i for i in issues if i.severity != ERROR]
        if errors:
            self.pill_validation.set(f"{len(errors)} error{'s' * (len(errors) != 1)}", "error")
        elif warnings:
            self.pill_validation.set(f"Ready  ·  {len(warnings)} hint{'s' * (len(warnings) != 1)}", "warn")
        else:
            self.pill_validation.set("Ready to build", "ok")
        for issue in errors + warnings:
            entry = QListWidgetItem(f"{issue.check_name}\n{issue.message}")
            entry.setData(Qt.UserRole, issue.attribute)
            color = theme.ERR if issue.severity == ERROR else theme.WARN
            entry.setIcon(get_svg_icon("x-circle" if issue.severity == ERROR else "warning", color, 16))
            self.list_issues.addItem(entry)
        if not issues:
            entry = QListWidgetItem("All checks passed.")
            entry.setFlags(Qt.NoItemFlags)
            self.list_issues.addItem(entry)
        return issues

    def _focus_issue(self, entry: QListWidgetItem) -> None:
        attr = entry.data(Qt.UserRole)
        editor = self.editors.get(attr)
        if not editor:
            return
        for i in range(self.tabs.count()):
            page = self.tabs.widget(i)
            if page.isAncestorOf(editor.widget):
                self.tabs.setCurrentIndex(i)
                editor.widget.setFocus()
                if isinstance(page, QScrollArea):
                    page.ensureWidgetVisible(editor.widget)
                return

    def _reset_to_base(self) -> None:
        if not self.base:
            return
        answer = QMessageBox.question(self, "Reset to base item",
                                      "Discard all stat changes and copy every value from "
                                      f"'{self.base.label}' again?")
        if answer != QMessageBox.Yes:
            return
        for name, editor in self.editors.items():
            if name in self.base.attrs:
                editor.set_value(self.base.attrs[name])
        self._validate()

    def _save(self) -> None:
        issues = self._validate()
        errors = [i for i in issues if i.severity == ERROR]
        if errors:
            answer = QMessageBox.question(
                self, "Save with errors?",
                f"This item has {len(errors)} error(s) and will block the build until they are fixed.\n\n"
                "Save it anyway as a draft?")
            if answer != QMessageBox.Yes:
                return
        self.saved = self._collect()
        self.accept()
