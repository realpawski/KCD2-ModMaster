"""Asset Browser page with central horizontal splitter: Asset List ↔ 3D/Content Preview."""
from __future__ import annotations

import time

from PySide6.QtCore import QItemSelectionModel, Qt, QTimer
from PySide6.QtGui import QGuiApplication, QKeySequence, QShortcut
from PySide6.QtWidgets import (
    QAbstractItemView,
    QCheckBox,
    QComboBox,
    QFrame,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QMenu,
    QPushButton,
    QSizePolicy,
    QSplitter,
    QTableView,
    QVBoxLayout,
    QWidget,
)

from kcd2.formats import ASSET_CLASSES, TYPE_GROUPS
from ui import theme
from ui.asset_model import AssetTableModel
from ui.context import AppContext
from ui.icons import get_svg_icon
from ui.inspector import InspectorWidget
from ui.preview.container import PreviewContainer

RESULT_LIMIT = 5000


class BrowserPage(QWidget):
    def __init__(self, ctx: AppContext, parent=None):
        super().__init__(parent)
        self.ctx = ctx
        self.saved_splitter_sizes = [520, 1000, 360]
        self._saved_inspector_size = 360

        lay = QVBoxLayout(self)
        lay.setContentsMargins(20, 16, 20, 12)
        lay.setSpacing(10)

        head = QHBoxLayout()
        self.h1 = QLabel("Asset Browser")
        self.h1.setObjectName("H1")
        head.addWidget(self.h1)
        head.addStretch(1)
        self.count = QLabel("")
        self.count.setObjectName("Badge")
        head.addWidget(self.count)
        head.addSpacing(6)

        self.btn_toggle_inspector = QPushButton("Inspector")
        self.btn_toggle_inspector.setIcon(get_svg_icon("information-circle", "#e9ebef", 16))
        self.btn_toggle_inspector.setCheckable(True)
        self.btn_toggle_inspector.setChecked(True)
        self.btn_toggle_inspector.setToolTip("Toggle Asset Inspector")
        self.btn_toggle_inspector.clicked.connect(self.toggle_inspector)
        head.addWidget(self.btn_toggle_inspector)

        lay.addLayout(head)

        self.search = QLineEdit()
        self.search.setObjectName("Search")
        self.search.setPlaceholderText("Search assets…   e.g.  sword   helmet   barrel   door   polearm   (space = AND)")
        self.search.setClearButtonEnabled(True)
        self.search.textChanged.connect(lambda: self.timer.start())
        lay.addWidget(self.search)

        filters = QHBoxLayout()
        filters.setSpacing(8)
        self.type_cb = QComboBox()
        self.type_cb.addItem("All types", None)
        for g in TYPE_GROUPS:
            self.type_cb.addItem(g, g)
        self.type_cb.addItem("Texture parts", "Texture parts")

        self.class_cb = QComboBox()
        self.class_cb.addItem("All classes", None)
        for c in ASSET_CLASSES:
            self.class_cb.addItem(c, c)
        self.class_cb.setToolTip("Classification is a heuristic based on the virtual folder.")

        self.archive_cb = QComboBox()
        self.archive_cb.setMinimumWidth(130)

        self.vpath_chk = QCheckBox("Show virtual path")
        self.vpath_chk.setChecked(ctx.settings.show_virtual_path)

        self.parts_chk = QCheckBox("Show texture chunks")
        self.parts_chk.setToolTip("KCD2 stores higher DDS mips as separate entries (x.dds.1, x.dds.1a …).")
        self.parts_chk.setChecked(ctx.settings.show_texture_parts)

        for w in (QLabel("Type"), self.type_cb, QLabel("Class"), self.class_cb, QLabel("Archive"), self.archive_cb):
            filters.addWidget(w)
        filters.addStretch(1)
        filters.addWidget(self.vpath_chk)
        filters.addWidget(self.parts_chk)
        lay.addLayout(filters)

        self.splitter = QSplitter(Qt.Horizontal)
        self.splitter.setChildrenCollapsible(False)

        # Left Pane: Table + Action bar
        self.left_pane = QWidget()
        self.left_pane.setMinimumWidth(300)
        left_lay = QVBoxLayout(self.left_pane)
        left_lay.setContentsMargins(0, 0, 4, 0)
        left_lay.setSpacing(6)

        self.model = AssetTableModel(self)
        self.model.set_show_vpath(self.vpath_chk.isChecked())
        self.table = QTableView()
        self.table.setModel(self.model)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.ExtendedSelection)
        self.table.setAlternatingRowColors(True)
        self.table.setShowGrid(False)
        self.table.verticalHeader().setVisible(False)
        self.table.verticalHeader().setDefaultSectionSize(30)
        self.table.setWordWrap(False)

        hh = self.table.horizontalHeader()
        hh.setSectionResizeMode(0, QHeaderView.Interactive)
        hh.setSectionResizeMode(1, QHeaderView.Interactive)
        hh.setSectionResizeMode(2, QHeaderView.Stretch)
        hh.setSectionResizeMode(3, QHeaderView.Interactive)
        hh.setSectionResizeMode(4, QHeaderView.Interactive)
        hh.resizeSection(0, 240)
        hh.resizeSection(1, 64)
        hh.resizeSection(3, 130)
        hh.resizeSection(4, 70)

        self.table.setContextMenuPolicy(Qt.CustomContextMenu)
        self.table.customContextMenuRequested.connect(self._menu)
        self.table.selectionModel().selectionChanged.connect(self._sel_changed)
        self.table.doubleClicked.connect(lambda _i: self._extract(False))
        left_lay.addWidget(self.table, 1)

        self.empty_hint = QLabel("")
        self.empty_hint.setObjectName("Muted")
        self.empty_hint.setWordWrap(True)
        self.empty_hint.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)
        left_lay.addWidget(self.empty_hint)
        actions = QHBoxLayout()
        actions.addStretch(1)

        self.btn_extract_to = QPushButton("Extract to…")
        self.btn_extract_to.setIcon(get_svg_icon("arrow-down-tray", "#e9ebef", 16))
        self.btn_extract_to.clicked.connect(lambda: self._extract(True))
        self.btn_extract = QPushButton("Extract selected")
        self.btn_extract.setObjectName("Primary")
        self.btn_extract.setIcon(get_svg_icon("arrow-down-tray", "#16110a", 16))
        self.btn_extract.clicked.connect(lambda: self._extract(False))

        actions.addWidget(self.btn_extract_to)
        actions.addWidget(self.btn_extract)
        left_lay.addLayout(actions)

        self.splitter.addWidget(self.left_pane)

        # Center Pane: 3D and Content-Aware Preview Container
        self.preview_container = PreviewContainer(self.ctx)
        self.preview_container.setMinimumWidth(360)
        self.preview_container.expand_toggled.connect(self._on_preview_expand_toggled)
        self.splitter.addWidget(self.preview_container)

        # Right Pane: Asset Inspector
        self.inspector_pane = QWidget()
        self.inspector_pane.setMinimumWidth(280)
        insp_lay = QVBoxLayout(self.inspector_pane)
        insp_lay.setContentsMargins(0, 0, 0, 0)
        insp_lay.setSpacing(0)
        self.inspector = InspectorWidget(self.ctx, self.inspector_pane)
        self.inspector.collapse_requested.connect(lambda: self.set_inspector_visible(False))
        insp_lay.addWidget(self.inspector)
        self.splitter.addWidget(self.inspector_pane)

        # Configure responsive stretch factors:
        # Left (0): resizable, doesn't greedily steal space on resize
        # Right Inspector (0): resizable, retains comfortable 320-360px width
        self.splitter.setStretchFactor(0, 0)
        self.splitter.setStretchFactor(1, 1)
        self.splitter.setStretchFactor(2, 0)

        initial_sizes = self.ctx.settings.browser_splitter_sizes or [520, 1000, 360]
        self.splitter.setSizes(initial_sizes)
        self.splitter.splitterMoved.connect(self._on_splitter_moved)

        lay.addWidget(self.splitter, 1)

        # Search debounce timer
        self.timer = QTimer(self)
        self.timer.setSingleShot(True)
        self.timer.setInterval(220)
        self.timer.timeout.connect(self.refresh)

        for cb in (self.type_cb, self.class_cb, self.archive_cb):
            cb.currentIndexChanged.connect(self.refresh)
        self.parts_chk.toggled.connect(self._parts_toggled)
        self.vpath_chk.toggled.connect(self._vpath_toggled)

        QShortcut(QKeySequence("Ctrl+F"), self, activated=lambda: (self.search.setFocus(), self.search.selectAll()))
        QShortcut(QKeySequence("Ctrl+E"), self, activated=lambda: self._extract(False))
        QShortcut(QKeySequence("F4"), self, activated=self.toggle_inspector)

        ctx.index_changed.connect(self.reload_archives)
        self.reload_archives()

    def toggle_inspector(self, checked: bool | None = None) -> None:
        target = checked if isinstance(checked, bool) else (not getattr(self, "_inspector_visible", True))
        self.set_inspector_visible(target)

    def set_inspector_visible(self, visible: bool) -> None:
        self._inspector_visible = visible
        self.btn_toggle_inspector.setChecked(visible)
        if not visible:
            sizes = self.splitter.sizes()
            if len(sizes) >= 3 and sizes[2] > 0:
                self._saved_inspector_size = sizes[2]
            self.inspector_pane.setVisible(False)
        else:
            self.inspector_pane.setVisible(True)
            sizes = self.splitter.sizes()
            target_insp = getattr(self, "_saved_inspector_size", 310) or 310
            if len(sizes) >= 3:
                total = sum(sizes)
                sizes[2] = target_insp
                sizes[1] = max(100, total - sizes[0] - target_insp)
                self.splitter.setSizes(sizes)

    def _on_preview_expand_toggled(self, expanded: bool) -> None:
        if expanded:
            self.saved_splitter_sizes = self.splitter.sizes()
            self.left_pane.setVisible(False)
            self.inspector_pane.setVisible(False)
        else:
            self.left_pane.setVisible(True)
            if self.btn_toggle_inspector.isChecked():
                self.inspector_pane.setVisible(True)
            if self.saved_splitter_sizes:
                self.splitter.setSizes(self.saved_splitter_sizes)

    def _on_splitter_moved(self, pos: int, index: int) -> None:
        sizes = self.splitter.sizes()
        if len(sizes) >= 3 and all(s > 0 for s in sizes):
            self.saved_splitter_sizes = sizes
            self.ctx.settings.browser_splitter_sizes = sizes

    def showEvent(self, event) -> None:
        super().showEvent(event)
        # Ensure optimal geometry partition on first layout event
        if not getattr(self, "_initial_layout_done", False):
            self._initial_layout_done = True
            total_w = self.splitter.width()
            if total_w > 800:
                insp_w = 340
                left_w = min(420, max(300, int(total_w * 0.25)))
                vp_w = max(400, total_w - left_w - insp_w)
                self.splitter.setSizes([left_w, vp_w, insp_w])
                self.saved_splitter_sizes = [left_w, vp_w, insp_w]
                self.ctx.settings.browser_splitter_sizes = [left_w, vp_w, insp_w]

    def apply_options(self, opts: dict) -> None:
        if "asset_class" in opts:
            i = self.class_cb.findData(opts["asset_class"])
            self.class_cb.setCurrentIndex(max(i, 0))
            self.h1.setText(opts.get("title", "Asset Browser"))
        if "type" in opts:
            i = self.type_cb.findData(opts["type"])
            self.type_cb.setCurrentIndex(max(i, 0))
        self.search.setFocus()

    def reload_archives(self) -> None:
        cur = self.archive_cb.currentData()
        self.archive_cb.blockSignals(True)
        self.archive_cb.clear()
        self.archive_cb.addItem("All archives", None)
        for aid, name, group, n in self.ctx.index.list_archives():
            label = name if group == "Data" else f"{group} / {name}"
            self.archive_cb.addItem(f"{label}  ({n:,})", aid)
        i = self.archive_cb.findData(cur)
        self.archive_cb.setCurrentIndex(max(i, 0))
        self.archive_cb.blockSignals(False)
        self.refresh()

    def refresh(self) -> None:
        self.timer.stop()
        idx = self.ctx.index
        stats = idx.stats()
        if stats["assets"] == 0:
            self.model.set_rows([])
            self.count.setText("index empty")
            self.empty_hint.setText("The asset index is empty. Go to Home and click “Scan Game Archives”.")
            self.preview_container.set_asset(None)
            return

        t0 = time.perf_counter()
        rows, more = idx.search(
            self.search.text(),
            type_group=self.type_cb.currentData(),
            asset_class=self.class_cb.currentData(),
            archive_id=self.archive_cb.currentData(),
            include_parts=self.parts_chk.isChecked(),
            limit=RESULT_LIMIT,
        )
        ms = (time.perf_counter() - t0) * 1000
        self.model.set_rows(rows)
        self.count.setText(f"{len(rows):,}{'+' if more else ''} results")
        hint = f"{ms:.0f} ms · {stats['assets']:,} indexed entries"
        if more:
            hint += f" · showing first {RESULT_LIMIT:,} – refine your search"
        self.empty_hint.setText(hint if rows else "No assets match. Try fewer words or another filter.")

        # Deselect by default when list changes
        self.table.selectionModel().clearSelection()
        self.ctx.asset_selected.emit(None)
        self.preview_container.set_asset(None)

    def selected_rows(self):
        return [self.model.rows[i.row()] for i in self.table.selectionModel().selectedRows()]

    def _sel_changed(self, *_):
        rows = self.selected_rows()
        selected = rows[0] if len(rows) >= 1 else None
        # Notify context (updates right-hand inspector)
        self.ctx.asset_selected.emit(selected)
        # Notify central preview container (loads 3D/2D content immediately)
        self.preview_container.set_asset(selected)

        n = len(rows)
        self.btn_extract.setText(f"Extract {n} Selected" if n > 1 else "Extract Selected")

    def _extract(self, choose: bool, companions: bool | None = None) -> None:
        rows = self.selected_rows()
        if not rows:
            return
        comp = self.ctx.settings.extract_companions if companions is None else companions
        (self.ctx.extract_to_requested if choose else self.ctx.extract_requested).emit(rows, comp)

    def _menu(self, pos):
        rows = self.selected_rows()
        if not rows:
            return
        m = QMenu(self)

        first = rows[0]
        if first.ext.lower() in ("cgf", "cgfm", "skin", "chr"):
            m.addAction(get_svg_icon("blender", "#e9ebef", 14), "Open in Blender", lambda: self.preview_container._on_open_in_blender())
            m.addAction(get_svg_icon("document-duplicate", "#e9ebef", 14), "Create Editable Workspace Copy", lambda: self.preview_container._on_create_copy())
            m.addSeparator()

        m.addAction(get_svg_icon("arrow-down-tray", "#e9ebef", 14), "Extract to Workspace", lambda: self._extract(False))
        m.addAction(get_svg_icon("arrow-down-tray", "#e9ebef", 14), "Extract to…", lambda: self._extract(True))
        m.addAction("Extract (primary file only)", lambda: self._extract(False, companions=False))
        m.addAction("Extract with companion files", lambda: self._extract(False, companions=True))
        m.addSeparator()
        m.addAction(get_svg_icon("duplicate", "#e9ebef", 14), "Copy virtual path", lambda: QGuiApplication.clipboard().setText(
            "\n".join(r.vpath for r in self.selected_rows())))
        m.addAction(get_svg_icon("magnifying-glass", "#e9ebef", 14), "Filter by this archive", self._filter_archive)
        m.exec(self.table.viewport().mapToGlobal(pos))

    def _filter_archive(self):
        rows = self.selected_rows()
        if rows:
            i = self.archive_cb.findData(rows[0].archive_id)
            if i >= 0:
                self.archive_cb.setCurrentIndex(i)

    def _parts_toggled(self, on: bool):
        self.ctx.settings.show_texture_parts = on
        self.ctx.settings.save()
        self.refresh()

    def _vpath_toggled(self, on: bool):
        self.ctx.settings.show_virtual_path = on
        self.ctx.settings.save()
        self.model.set_show_vpath(on)

    def select_first(self):
        if self.model.rowCount():
            self.table.selectionModel().select(self.model.index(0, 0),
                                               QItemSelectionModel.ClearAndSelect | QItemSelectionModel.Rows)
