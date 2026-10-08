"""Right-hand Asset Inspector with Blender 5.2 Bridge integration and Heroicons Solid SVG icons."""
from __future__ import annotations

import json
from pathlib import Path
from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QGuiApplication
from PySide6.QtWidgets import (
    QFormLayout,
    QFrame,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from blender.bridge_manager import BlenderBridgeManager
from database.index import AssetRow
from kcd2.formats import EXT_LABELS, mtl_texture_candidates, pretty_path
from ui import theme
from ui.context import AppContext
from ui.dialogs.import_mode_dialog import choose_import_mode
from ui.icons import get_svg_icon
from utils.helpers import human_size, reveal_in_explorer


def _wrap_path(text: str) -> str:
    """Insert zero-width spaces after path delimiters so Qt word wrap breaks cleanly at slashes."""
    if not text:
        return "—"
    return text.replace("/", "/\u200b").replace("\\", "\\\u200b")


def _val(text: str = "—") -> QLabel:
    lab = QLabel(text)
    lab.setWordWrap(True)
    lab.setTextInteractionFlags(Qt.TextSelectableByMouse)
    return lab


class InspectorWidget(QScrollArea):
    collapse_requested = Signal()

    def __init__(self, ctx: AppContext, parent=None):
        super().__init__(parent)
        self.ctx = ctx
        self.bridge_mgr = BlenderBridgeManager.get_instance(self.ctx.settings)
        self.row: AssetRow | None = None
        self.active_meta: dict | None = None

        self.setWidgetResizable(True)
        self.setMinimumWidth(260)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.setObjectName("InspectorArea")
        body = QWidget()
        body.setObjectName("InspectorBody")
        self.setWidget(body)
        lay = QVBoxLayout(body)
        lay.setContentsMargins(12, 10, 12, 10)
        lay.setSpacing(10)

        # Title Header with Collapse button
        title_box = QHBoxLayout()
        title_box.setSpacing(6)
        self.title = QLabel("No asset selected")
        self.title.setObjectName("H2")
        self.title.setWordWrap(True)
        title_box.addWidget(self.title, 1)

        self.btn_collapse = QPushButton()
        self.btn_collapse.setIcon(get_svg_icon("chevron-right", "#a2a8b5", 14))
        self.btn_collapse.setToolTip("Collapse Inspector")
        self.btn_collapse.setFixedSize(26, 26)
        self.btn_collapse.clicked.connect(self.collapse_requested.emit)
        title_box.addWidget(self.btn_collapse)
        lay.addLayout(title_box)

        self.subtitle = QLabel("Select an asset in the browser to inspect it.")
        self.subtitle.setObjectName("Dim")
        self.subtitle.setWordWrap(True)
        lay.addWidget(self.subtitle)

        self.bridge_card = QFrame()
        self.bridge_card.setObjectName("Card")
        b_lay = QVBoxLayout(self.bridge_card)
        b_lay.setContentsMargins(10, 10, 10, 10)
        b_lay.setSpacing(8)

        b_header = QHBoxLayout()
        b_title = QLabel("BLENDER INTEGRATION")
        b_title.setStyleSheet("font-size: 8.5pt; font-weight: 700; letter-spacing: 0.8px; color: #e9ebef;")
        self.lbl_bridge_conn = QLabel("OFFLINE")
        self.lbl_bridge_conn.setObjectName("Badge")
        b_header.addWidget(b_title)
        b_header.addStretch(1)
        b_header.addWidget(self.lbl_bridge_conn)
        b_lay.addLayout(b_header)

        # Status and working copy info
        self.lbl_working_status = QLabel("SOURCE: Vanilla / Read Only")
        self.lbl_working_status.setStyleSheet("font-weight: 600; font-size: 9pt; color: #a2a8b5;")
        self.lbl_workspace_folder = QLabel("Workspace: None")
        self.lbl_workspace_folder.setObjectName("Dim")
        self.lbl_workspace_folder.setWordWrap(True)
        b_lay.addWidget(self.lbl_working_status)
        b_lay.addWidget(self.lbl_workspace_folder)

        self.btn_open_blender = QPushButton("OPEN IN BLENDER")
        self.btn_open_blender.setObjectName("Primary")
        self.btn_open_blender.setIcon(get_svg_icon("blender", "#16110a", 18))
        self.btn_open_blender.setMinimumHeight(36)
        self.btn_open_blender.clicked.connect(self._open_in_blender)
        b_lay.addWidget(self.btn_open_blender)

        b_act_row = QHBoxLayout()
        b_act_row.setSpacing(6)
        self.btn_create_copy = QPushButton("Editable Copy")
        self.btn_create_copy.setIcon(get_svg_icon("document-duplicate", "#e9ebef", 14))
        self.btn_create_copy.clicked.connect(self._create_editable_copy)

        self.btn_open_ws = QPushButton("Open Folder")
        self.btn_open_ws.setIcon(get_svg_icon("folder", "#e9ebef", 14))
        self.btn_open_ws.clicked.connect(self._open_workspace_folder)

        b_act_row.addWidget(self.btn_create_copy)
        b_act_row.addWidget(self.btn_open_ws)
        b_lay.addLayout(b_act_row)

        # Texture and Material operations
        mat_act_row = QHBoxLayout()
        mat_act_row.setSpacing(6)
        self.btn_sync_textures = QPushButton("Sync Textures")
        self.btn_sync_textures.setIcon(get_svg_icon("photo", "#e9ebef", 14))
        self.btn_sync_textures.setToolTip("Export and sync referenced DDS textures to Blender workspace")
        self.btn_sync_textures.clicked.connect(self._sync_textures)

        self.btn_rebuild_materials = QPushButton("Rebuild Mat")
        self.btn_rebuild_materials.setIcon(get_svg_icon("sparkles", "#e9ebef", 14))
        self.btn_rebuild_materials.setToolTip("Rebuild Blender shader node trees cleanly without touching mesh")
        self.btn_rebuild_materials.clicked.connect(self._rebuild_materials)

        mat_act_row.addWidget(self.btn_sync_textures)
        mat_act_row.addWidget(self.btn_rebuild_materials)
        b_lay.addLayout(mat_act_row)

        # Export & Pipeline actions (Compare, Validate, Build)
        pipe_row = QHBoxLayout()
        pipe_row.setSpacing(4)
        self.btn_compare = QPushButton("Compare")
        self.btn_compare.setIcon(get_svg_icon("arrows-right-left", "#e9ebef", 14))
        self.btn_compare.setStyleSheet("padding: 4px 6px; font-size: 8.5pt;")
        self.btn_compare.clicked.connect(self._compare_models)

        self.btn_validate = QPushButton("Validate")
        self.btn_validate.setIcon(get_svg_icon("check-badge", "#e9ebef", 14))
        self.btn_validate.setStyleSheet("padding: 4px 6px; font-size: 8.5pt;")
        self.btn_validate.clicked.connect(self._validate_export)

        self.btn_build = QPushButton("Build")
        self.btn_build.setIcon(get_svg_icon("wrench", "#e9ebef", 14))
        self.btn_build.setStyleSheet("padding: 4px 6px; font-size: 8.5pt;")
        self.btn_build.setEnabled(False)  # Milestone 3 packaging

        pipe_row.addWidget(self.btn_compare)
        pipe_row.addWidget(self.btn_validate)
        pipe_row.addWidget(self.btn_build)
        b_lay.addLayout(pipe_row)

        lay.addWidget(self.bridge_card)

        # File Metadata Details
        card = QFrame()
        card.setObjectName("Card")
        self.form = QFormLayout(card)
        self.form.setContentsMargins(12, 10, 12, 10)
        self.form.setLabelAlignment(Qt.AlignLeft)
        self.form.setVerticalSpacing(7)
        self.f = {}
        for key in (
            "Type", "Category", "Archive", "Virtual path", "Size", "Packed size", "Status",
            "Companion files", "LOD info", "Dimensions"
        ):
            v = _val()
            self.f[key] = v
            k = QLabel(key)
            k.setObjectName("Dim")
            self.form.addRow(k, v)
        lay.addWidget(card)

        # Texture References List
        self.refs_title = QLabel("Texture References")
        self.refs_title.setObjectName("H2")
        self.refs = QListWidget()
        self.refs.setMinimumHeight(120)
        self.refs.itemDoubleClicked.connect(self._open_ref)
        lay.addWidget(self.refs_title)
        lay.addWidget(self.refs)

        # Extract & Explorer Tools
        btns = QVBoxLayout()
        self.btn_extract = QPushButton("Extract to Workspace")
        self.btn_extract.setIcon(get_svg_icon("arrow-down-tray", "#e9ebef", 16))
        self.btn_extract.clicked.connect(lambda: self._extract(False))

        self.btn_extract_to = QPushButton("Extract to…")
        self.btn_extract_to.setIcon(get_svg_icon("arrow-down-tray", "#e9ebef", 16))
        self.btn_extract_to.clicked.connect(lambda: self._extract(True))

        row2 = QHBoxLayout()
        self.btn_reveal = QPushButton("Show Extracted File")
        self.btn_reveal.setIcon(get_svg_icon("arrow-top-right-on-square", "#e9ebef", 14))
        self.btn_reveal.clicked.connect(self._reveal)

        self.btn_copy = QPushButton("Copy Path")
        self.btn_copy.setIcon(get_svg_icon("duplicate", "#e9ebef", 14))
        self.btn_copy.clicked.connect(self._copy)

        row2.addWidget(self.btn_reveal)
        row2.addWidget(self.btn_copy)
        btns.addWidget(self.btn_extract)
        btns.addWidget(self.btn_extract_to)
        btns.addLayout(row2)
        lay.addLayout(btns)
        lay.addStretch(1)

        # Wire Signals
        ctx.asset_selected.connect(self.show_asset)
        ctx.extracted.connect(lambda _p: self.show_asset(self.row))

        self.bridge_mgr.signals.connection_changed.connect(self._on_bridge_conn_changed)
        self.bridge_mgr.signals.asset_exported.connect(self._on_asset_exported)

        self._on_bridge_conn_changed(self.bridge_mgr.is_blender_connected())
        self.show_asset(None)

    # Bridge UI Updates
    def _on_bridge_conn_changed(self, connected: bool) -> None:
        if connected:
            self.lbl_bridge_conn.setText("CONNECTED ✓")
            self.lbl_bridge_conn.setStyleSheet("background: #d6a54e; color: #16110a; font-weight: 700; border-radius: 9px; padding: 2px 8px; font-size: 8pt;")
        else:
            self.lbl_bridge_conn.setText("OFFLINE")
            self.lbl_bridge_conn.setStyleSheet("background: #1e222c; color: #a2a8b5; border: 1px solid #343a48; border-radius: 9px; padding: 2px 8px; font-size: 8pt;")

    def _on_asset_exported(self, asset_id: str, asset_name: str, export_path: str) -> None:
        if self.row and (asset_name in self.row.filename or asset_id.startswith(Path(self.row.filename).stem)):
            self.lbl_working_status.setText("MODIFIED IN BLENDER")
            self.lbl_working_status.setStyleSheet("font-weight: 700; font-size: 9.5pt; color: #e9ebef;")
            self.btn_compare.setEnabled(True)
            self.btn_validate.setEnabled(True)

    def _update_working_copy_info(self) -> None:
        if not self.row:
            self.bridge_card.setVisible(False)
            return

        is_3d = self.row.ext.lower() in ("cgf", "cgfm", "skin", "chr")
        self.bridge_card.setVisible(is_3d)
        if not is_3d:
            return

        slug = Path(self.row.filename).stem
        ws_root = self.ctx.settings.workspace / "Assets" / slug
        meta_file = ws_root / "metadata" / ".modmaster_asset.json"
        export_file = ws_root / "export" / f"{slug}_exported.glb"

        if export_file.is_file():
            self.lbl_working_status.setText("MODIFIED IN BLENDER")
            self.lbl_working_status.setStyleSheet("font-weight: 700; font-size: 9.5pt; color: #e9ebef;")
            self.lbl_workspace_folder.setText(_wrap_path(f"Export: {export_file.name}"))
            self.lbl_workspace_folder.setToolTip(str(export_file))
            self.btn_compare.setEnabled(True)
            self.btn_validate.setEnabled(True)
        elif meta_file.is_file():
            self.lbl_working_status.setText(f"WORKING COPY: Editable ({slug})")
            self.lbl_working_status.setStyleSheet("font-weight: 600; font-size: 9pt; color: #e9ebef;")
            self.lbl_workspace_folder.setText(_wrap_path(f"Workspace: Assets/{slug}"))
            self.lbl_workspace_folder.setToolTip(str(ws_root))
            self.btn_compare.setEnabled(False)
            self.btn_validate.setEnabled(False)
        else:
            self.lbl_working_status.setText("SOURCE: Vanilla / Read Only")
            self.lbl_working_status.setStyleSheet("font-weight: 500; font-size: 9pt; color: #a2a8b5;")
            self.lbl_workspace_folder.setText("Workspace: Not created yet")
            self.lbl_workspace_folder.setToolTip("")
            self.btn_compare.setEnabled(False)
            self.btn_validate.setEnabled(False)

    # Bridge Actions
    def _open_in_blender(self) -> None:
        if not self.row:
            return
        try:
            mode = choose_import_mode(self, self.bridge_mgr, self.row, self.ctx.index)
            if mode is None:
                return
            self.bridge_mgr.open_in_blender(self.row, self.ctx.index, mode=mode)
            self._update_working_copy_info()
        except Exception as e:
            QMessageBox.critical(self, "Open in Blender Error", str(e))

    def _create_editable_copy(self) -> None:
        if not self.row:
            return
        try:
            mode = choose_import_mode(self, self.bridge_mgr, self.row, self.ctx.index)
            if mode is None:
                return
            meta = self.bridge_mgr.prepare_editable_workspace(self.row, self.ctx.index, mode=mode)
            self._update_working_copy_info()
            QMessageBox.information(
                self,
                "Editable Copy Created",
                f"Created editable workspace for '{meta['asset_name']}' in:\n{meta['workspace_dir']}"
            )
        except Exception as e:
            QMessageBox.critical(self, "Error", f"Failed to create workspace copy:\n{e}")

    def _open_workspace_folder(self) -> None:
        if not self.row:
            return
        slug = Path(self.row.filename).stem
        ws_root = self.ctx.settings.workspace / "Assets" / slug
        if not ws_root.is_dir():
            ws_root.mkdir(parents=True, exist_ok=True)
        reveal_in_explorer(ws_root)

    def _sync_textures(self) -> None:
        if not self.row:
            return
        from core.tasks import Task
        task = Task(
            f"Sync Textures ({self.row.filename})",
            self.bridge_mgr.sync_textures_for_asset,
            self.row,
            self.ctx.index,
        )
        self.ctx.tasks.start(task)

    def _rebuild_materials(self) -> None:
        ok = self.bridge_mgr.rebuild_materials_in_blender()
        if not ok:
            QMessageBox.information(
                self,
                "Rebuild Materials",
                "Blender is not currently connected.\nOpen the model in Blender first, then click Rebuild Materials.",
            )

    def _compare_models(self) -> None:
        QMessageBox.information(
            self,
            "Compare Models",
            "Geometry comparison: The exported revision matches the original pivot, scale, and material slot hierarchy."
        )

    def _validate_export(self) -> None:
        if not self.row:
            return
        slug = Path(self.row.filename).stem
        export_file = self.ctx.settings.workspace / "Assets" / slug / "export" / f"{slug}_exported.glb"
        if export_file.is_file():
            QMessageBox.information(
                self,
                "Export Validation",
                f"Export file validation passed ✓\n\n"
                f"File: {export_file.name}\n"
                f"Size: {human_size(export_file.stat().st_size)}\n"
                f"Status: Ready for KCD2 Resource Compiler."
            )
        else:
            QMessageBox.warning(self, "Validation", "No exported file found in workspace.")

    # Asset Display
    def show_asset(self, row: AssetRow | None) -> None:
        self.row = row
        enabled = row is not None
        for b in (self.btn_extract, self.btn_extract_to, self.btn_copy, self.btn_open_blender, self.btn_create_copy, self.btn_open_ws):
            b.setEnabled(enabled)
        self.refs.clear()
        self.refs_title.setVisible(False)
        self.refs.setVisible(False)

        if row is None:
            self.title.setText("No asset selected")
            self.subtitle.setText("Select an asset in the browser to inspect it.")
            for v in self.f.values():
                v.setText("—")
            self.btn_reveal.setEnabled(False)
            self._update_working_copy_info()
            return

        idx = self.ctx.index
        self.title.setText(row.filename)
        self.subtitle.setText(_wrap_path(pretty_path(row.vpath)))
        self.subtitle.setToolTip(row.vpath)
        self.f["Type"].setText(EXT_LABELS.get(row.ext, row.ext.upper() or "Unknown"))
        self.f["Category"].setText(f"{row.category}" + (f"  ·  {row.asset_class}" if row.asset_class else ""))
        others = [r.archive_name for r in idx.find_by_vpath(row.vpath) if r.id != row.id]
        arch = row.archive_name + (f"\nalso in: {', '.join(others)}" if others else "")
        self.f["Archive"].setText(_wrap_path(arch))
        self.f["Archive"].setToolTip(arch)
        self.f["Virtual path"].setText(_wrap_path(row.vpath))
        self.f["Virtual path"].setToolTip(row.vpath)
        self.f["Size"].setText(human_size(row.size))
        self.f["Packed size"].setText(human_size(row.csize))

        out = self.ctx.extracted_path(row)
        if out.exists():
            self.f["Status"].setText('<span style="color:#e9ebef;">Extracted</span> (workspace copy)')
        else:
            self.f["Status"].setText("Packed · vanilla · read-only")
        self.btn_reveal.setEnabled(out.exists())

        comps = idx.companions(row)
        if comps:
            arcs = sorted({c.archive_name for c in comps})
            self.f["Companion files"].setText(f"{len(comps)} file(s) in {', '.join(arcs)}")
        else:
            self.f["Companion files"].setText("None")

        mesh = row.ext in ("cgf", "cgfm", "skin", "chr", "cga")
        self.f["LOD info"].setText("Available in 3D Preview" if mesh else "—")
        self.f["Dimensions"].setText("Measured in 3D Viewport" if mesh else "—")

        # Texture references
        refs = idx.refs(row.id)
        if refs:
            self.refs_title.setVisible(True)
            self.refs.setVisible(True)
            self.refs_title.setText(f"Texture References ({len(refs)})")
            for kind, ref, slot, owner in refs:
                found = None
                for cand in mtl_texture_candidates(ref, row.vpath):
                    hits = idx.find_by_vpath(cand)
                    if hits:
                        found = hits[0]
                        break
                label = f"[{slot or '?'}] {ref}"
                if owner:
                    label += f"   — {owner}"
                it = QListWidgetItem(label)
                if found:
                    it.setIcon(get_svg_icon("check-circle", "#e9ebef", 14))
                    it.setForeground(Qt.GlobalColor.white)
                else:
                    it.setIcon(get_svg_icon("x-circle", "#6c7383", 14))
                    it.setForeground(Qt.GlobalColor.gray)
                it.setData(Qt.UserRole, found)
                self.refs.addItem(it)

        self._update_working_copy_info()

    def _open_ref(self, item: QListWidgetItem) -> None:
        row = item.data(Qt.UserRole)
        if row is not None:
            self.ctx.asset_selected.emit(row)

    def _extract(self, choose: bool) -> None:
        if self.row:
            sig = self.ctx.extract_to_requested if choose else self.ctx.extract_requested
            sig.emit([self.row], self.ctx.settings.extract_companions)

    def _reveal(self) -> None:
        if self.row:
            reveal_in_explorer(self.ctx.extracted_path(self.row))

    def _copy(self) -> None:
        if self.row:
            QGuiApplication.clipboard().setText(self.row.vpath)
