"""Content-Aware Preview Workspace with embedded Heroicons Solid SVG icons and Blender 5.2 Bridge actions."""
from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from PySide6.QtCore import QPoint, Qt, QTimer, Signal
from PySide6.QtWidgets import (
    QButtonGroup,
    QComboBox,
    QFrame,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from archives.pak import PakArchive
from blender.bridge_manager import BlenderBridgeManager
from core.tasks import Task
from database.index import AssetRow
from preview.converter import prepare_3d_preview
from preview.lods import LodFamily, find_lod_family
from ui import theme
from ui.context import AppContext
from ui.icons import get_svg_icon
from ui.preview.material_viewer import MaterialViewer
from ui.preview.texture_viewer import TextureViewer2D
from ui.preview.text_viewer import TextViewer
from ui.preview.viewport_3d import ModelViewport3D

log = logging.getLogger(__name__)


class PreviewContainer(QWidget):
    expand_toggled = Signal(bool)

    def __init__(self, ctx: AppContext, parent=None):
        super().__init__(parent)
        self.ctx = ctx
        self.bridge_mgr = BlenderBridgeManager.get_instance(self.ctx.settings)
        self.current_row: AssetRow | None = None
        self.current_lod_family: LodFamily | None = None
        self.is_expanded = False

        # Token to discard outdated async conversions
        self._preview_token = 0
        self._active_task: Task | None = None

        root_lay = QVBoxLayout(self)
        root_lay.setContentsMargins(0, 0, 0, 0)
        root_lay.setSpacing(0)

        self.toolbar = QFrame()
        self.toolbar.setObjectName("PreviewToolbar")
        tb_lay = QHBoxLayout(self.toolbar)
        tb_lay.setContentsMargins(6, 4, 6, 4)
        tb_lay.setSpacing(4)

        # Shading mode buttons with Heroicons Solid SVG icons
        self.btn_textured = QPushButton("Textured")
        self.btn_textured.setIcon(get_svg_icon("sparkles", "#e9ebef", 14))

        self.btn_clay = QPushButton("Clay")
        self.btn_clay.setIcon(get_svg_icon("cube", "#e9ebef", 14))

        self.btn_wireframe = QPushButton("Wire")
        self.btn_wireframe.setIcon(get_svg_icon("squares-2x2", "#e9ebef", 14))

        self.btn_mat_ids = QPushButton("Mat ID")
        self.btn_mat_ids.setIcon(get_svg_icon("swatch", "#e9ebef", 14))
        self.btn_mat_ids.setToolTip("Material IDs: Developer debug colors per material slot")

        for b in (self.btn_textured, self.btn_clay, self.btn_wireframe, self.btn_mat_ids):
            b.setCheckable(True)
            tb_lay.addWidget(b)

        self.shade_group = QButtonGroup(self)
        self.shade_group.addButton(self.btn_textured, 0)
        self.shade_group.addButton(self.btn_clay, 1)
        self.shade_group.addButton(self.btn_wireframe, 2)
        self.shade_group.addButton(self.btn_mat_ids, 3)
        self.btn_textured.setChecked(True)
        self.shade_group.idClicked.connect(self._on_shade_mode_changed)

        tb_lay.addSpacing(4)

        # Overlay toggles
        self.btn_grid = QPushButton("Grid")
        self.btn_grid.setIcon(get_svg_icon("squares-plus", "#e9ebef", 14))
        self.btn_grid.setCheckable(True)
        self.btn_grid.setChecked(True)
        self.btn_grid.toggled.connect(self._on_grid_toggled)
        tb_lay.addWidget(self.btn_grid)

        self.btn_ground = QPushButton("Ground")
        self.btn_ground.setIcon(get_svg_icon("home", "#e9ebef", 14))
        self.btn_ground.setCheckable(True)
        self.btn_ground.setChecked(True)
        self.btn_ground.toggled.connect(self._on_ground_toggled)
        tb_lay.addWidget(self.btn_ground)

        tb_lay.addSpacing(4)

        # LOD Switcher
        lbl_lod = QLabel("LOD:")
        lbl_lod.setObjectName("Dim")
        tb_lay.addWidget(lbl_lod)
        self.lod_cb = QComboBox()
        self.lod_cb.setMinimumWidth(65)
        self.lod_cb.currentIndexChanged.connect(self._on_lod_changed)
        tb_lay.addWidget(self.lod_cb)

        tb_lay.addSpacing(4)

        # Camera views
        self.cam_cb = QComboBox()
        self.cam_cb.addItems([
            "Perspective",
            "Front",
            "Back",
            "Left",
            "Right",
            "Top",
            "Bottom",
        ])
        self.cam_cb.currentTextChanged.connect(
            lambda t: self.viewport_3d.set_camera_view(t.lower())
        )
        tb_lay.addWidget(self.cam_cb)

        self.btn_frame = QPushButton("Frame")
        self.btn_frame.setIcon(get_svg_icon("arrows-pointing-in", "#e9ebef", 14))
        self.btn_frame.setToolTip("Frame camera on model (Focus)")
        self.btn_frame.clicked.connect(self.viewport_3d_frame)
        tb_lay.addWidget(self.btn_frame)

        tb_lay.addStretch(1)

        # Expand / Restore Viewport button
        self.btn_expand = QPushButton("Expand")
        self.btn_expand.setIcon(get_svg_icon("expand", "#e9ebef", 14))
        self.btn_expand.setToolTip("Toggle full-width preview")
        self.btn_expand.clicked.connect(self._toggle_expand)
        tb_lay.addWidget(self.btn_expand)

        root_lay.addWidget(self.toolbar)

        self.stack = QStackedWidget()

        # View 0: Empty / Placeholder state
        self.empty_view = QFrame()
        empty_lay = QVBoxLayout(self.empty_view)
        empty_lay.setAlignment(Qt.AlignCenter)
        lbl_empty = QLabel("Select an asset to preview")
        lbl_empty.setObjectName("H2")
        lbl_empty.setWordWrap(True)
        lbl_empty_sub = QLabel(
            "CGF / SKIN meshes render in 3D · DDS textures display in 2D · MTL materials inspect shaders"
        )
        lbl_empty_sub.setObjectName("Dim")
        lbl_empty_sub.setWordWrap(True)
        lbl_empty_sub.setAlignment(Qt.AlignCenter)
        empty_lay.addWidget(lbl_empty)
        empty_lay.addWidget(lbl_empty_sub)
        self.stack.addWidget(self.empty_view)

        # View 1: 3D Viewport
        self.v3d_container = QWidget()
        v3d_lay = QVBoxLayout(self.v3d_container)
        v3d_lay.setContentsMargins(0, 0, 0, 0)
        v3d_lay.setSpacing(0)

        self.viewport_3d = ModelViewport3D()
        self.viewport_3d.dimensions_updated.connect(self._update_hud_stats)
        v3d_lay.addWidget(self.viewport_3d, 1)

        # Bottom HUD Dimensions & Statistics Bar
        self.hud_bar = QFrame()
        self.hud_bar.setObjectName("PreviewHud")
        hud_lay = QHBoxLayout(self.hud_bar)
        hud_lay.setContentsMargins(10, 4, 10, 4)

        self.lbl_hud_dims = QLabel("DIMENSIONS: —")
        self.lbl_hud_dims.setStyleSheet(f"color: {theme.ACCENT}; font-weight: 600;")
        self.lbl_hud_tris = QLabel("Tris: —")
        self.lbl_hud_verts = QLabel("Verts: —")
        self.lbl_hud_working_copy = QLabel("SOURCE: Vanilla / Read Only")
        self.lbl_hud_working_copy.setStyleSheet("font-size: 8.5pt; font-weight: 600; color: #a2a8b5;")
        self.lbl_hud_status = QLabel("")
        self.lbl_hud_status.setObjectName("Dim")

        hud_lay.addWidget(self.lbl_hud_dims)
        hud_lay.addSpacing(16)
        hud_lay.addWidget(self.lbl_hud_tris)
        hud_lay.addSpacing(12)
        hud_lay.addWidget(self.lbl_hud_verts)
        hud_lay.addSpacing(16)
        hud_lay.addWidget(self.lbl_hud_working_copy)
        hud_lay.addStretch(1)
        hud_lay.addWidget(self.lbl_hud_status)

        v3d_lay.addWidget(self.hud_bar)
        self.stack.addWidget(self.v3d_container)

        # View 2: 2D Texture Viewer
        self.texture_viewer = TextureViewer2D()
        self.stack.addWidget(self.texture_viewer)

        # View 3: Material Inspector
        self.material_viewer = MaterialViewer()
        self.material_viewer.texture_navigate_requested.connect(
            self._on_material_texture_navigate
        )
        self.stack.addWidget(self.material_viewer)

        # View 4: Text Viewer
        self.text_viewer = TextViewer()
        self.stack.addWidget(self.text_viewer)

        self.loading_banner = QFrame(self)
        self.loading_banner.setStyleSheet(
            f"background: rgba(15, 17, 21, 0.95); border-bottom: 1px solid {theme.BORDER}; padding: 6px 14px;"
        )
        lb_lay = QHBoxLayout(self.loading_banner)
        lb_lay.setContentsMargins(10, 6, 10, 6)
        lb_lay.setSpacing(10)
        self.lbl_loading_msg = QLabel("Generating 3D preview...")
        self.lbl_loading_msg.setStyleSheet(f"color: {theme.ACCENT}; font-weight: 600;")
        self.load_progress = QProgressBar()
        self.load_progress.setRange(0, 0)
        self.load_progress.setFixedWidth(120)
        lb_lay.addWidget(self.lbl_loading_msg)
        lb_lay.addWidget(self.load_progress)
        lb_lay.addStretch(1)
        self.loading_banner.setVisible(False)

        root_lay.addWidget(self.loading_banner)
        root_lay.addWidget(self.stack, 1)

        # Connect bridge export listener
        self.bridge_mgr.signals.asset_exported.connect(self._on_asset_exported)

        # Initially show empty state
        self.set_asset(None)

    def viewport_3d_frame(self) -> None:
        self.viewport_3d.frame_camera()

    def _toggle_expand(self) -> None:
        self.is_expanded = not self.is_expanded
        self.btn_expand.setText("Restore" if self.is_expanded else "Expand")
        self.expand_toggled.emit(self.is_expanded)

    def _on_shade_mode_changed(self, mode_id: int) -> None:
        self.viewport_3d.set_mode(mode_id)
        if mode_id == 3 and self.viewport_3d.geom and self.viewport_3d.geom.materials:
            mats = self.viewport_3d.geom.materials
            if len(mats) <= 5:
                mat_summary = " · ".join(f"[{i}] {m.name}" for i, m in enumerate(mats))
            else:
                mat_summary = " · ".join(f"[{i}] {m.name}" for i, m in enumerate(mats[:4])) + f" (+{len(mats)-4} more)"
            self.lbl_hud_status.setText(f"Slots: {mat_summary}")

    def _on_grid_toggled(self, checked: bool) -> None:
        self.viewport_3d.toggle_grid(checked)

    def _on_ground_toggled(self, checked: bool) -> None:
        self.viewport_3d.toggle_ground(checked)

    def _update_hud_stats(
        self, dx: float, dy: float, dz: float, tris: int, verts: int
    ) -> None:
        self.lbl_hud_dims.setText(
            f"SIZE: {dx:.2f} × {dy:.2f} × {dz:.2f} m"
        )
        self.lbl_hud_tris.setText(f"Tris: {tris:,}")
        self.lbl_hud_verts.setText(f"Verts: {verts:,}")

    def _on_open_in_blender(self) -> None:
        if not self.current_row:
            return
        self.lbl_hud_status.setText("Launching Blender Bridge…")
        try:
            self.bridge_mgr.open_in_blender(self.current_row, self.ctx.index)
            self.lbl_hud_working_copy.setText(f"WORKING COPY: Opened in Blender ({Path(self.current_row.filename).stem})")
            self.lbl_hud_working_copy.setStyleSheet("font-size: 8.5pt; font-weight: 700; color: #e9ebef;")
        except Exception as e:
            QMessageBox.critical(self, "Open in Blender Error", str(e))
            self.lbl_hud_status.setText(f"Blender launch failed: {e}")

    def _on_create_copy(self) -> None:
        if not self.current_row:
            return
        try:
            meta = self.bridge_mgr.prepare_editable_workspace(self.current_row, self.ctx.index)
            self.lbl_hud_working_copy.setText(f"WORKING COPY: Editable ({meta['asset_name']})")
            self.lbl_hud_working_copy.setStyleSheet("font-size: 8.5pt; font-weight: 700; color: #e9ebef;")
            QMessageBox.information(
                self,
                "Editable Copy Created",
                f"Created editable workspace for '{meta['asset_name']}' in:\n{meta['workspace_dir']}"
            )
        except Exception as e:
            QMessageBox.critical(self, "Error", f"Failed to create workspace copy:\n{e}")

    def _on_asset_exported(self, asset_id: str, asset_name: str, export_path: str) -> None:
        if self.current_row and (asset_name in self.current_row.filename or asset_id.startswith(Path(self.current_row.filename).stem)):
            self.lbl_hud_working_copy.setText(f"MODIFIED IN BLENDER ({Path(export_path).name})")
            self.lbl_hud_working_copy.setStyleSheet("font-size: 8.5pt; font-weight: 700; color: #e9ebef;")
            self.lbl_hud_status.setText("Export detected from Blender ✓")

    def _refresh_working_copy_hud(self) -> None:
        if not self.current_row:
            self.lbl_hud_working_copy.setText("SOURCE: Vanilla / Read Only")
            self.lbl_hud_working_copy.setStyleSheet("font-size: 8.5pt; font-weight: 600; color: #a2a8b5;")
            return

        slug = Path(self.current_row.filename).stem
        ws_root = self.ctx.settings.workspace / "Assets" / slug
        export_file = ws_root / "export" / f"{slug}_exported.glb"
        meta_file = ws_root / "metadata" / ".modmaster_asset.json"

        if export_file.is_file():
            self.lbl_hud_working_copy.setText(f"MODIFIED IN BLENDER ({export_file.name})")
            self.lbl_hud_working_copy.setStyleSheet("font-size: 8.5pt; font-weight: 700; color: #e9ebef;")
        elif meta_file.is_file():
            self.lbl_hud_working_copy.setText(f"WORKING COPY: Editable ({slug})")
            self.lbl_hud_working_copy.setStyleSheet("font-size: 8.5pt; font-weight: 600; color: #e9ebef;")
        else:
            self.lbl_hud_working_copy.setText("SOURCE: Vanilla / Read Only")
            self.lbl_hud_working_copy.setStyleSheet("font-size: 8.5pt; font-weight: 600; color: #a2a8b5;")

    def set_asset(self, row: AssetRow | None) -> None:
        self.current_row = row
        self._preview_token += 1
        current_token = self._preview_token

        # Hide loading banner
        self.loading_banner.setVisible(False)

        if row is None:
            self.toolbar.setVisible(False)
            self.viewport_3d.set_geometry(None)
            self.stack.setCurrentIndex(0)
            return

        ext = row.ext.lower()
        is_3d = ext in ("cgf", "cgfm", "skin", "chr", "cga")

        if is_3d:
            self.toolbar.setVisible(True)
            self.viewport_3d.set_geometry(None)
            self.stack.setCurrentIndex(1)
            self._refresh_working_copy_hud()
            self._load_3d_asset(row, current_token)

        elif ext in ("dds", "tif", "tiff", "png", "jpg", "jpeg"):
            self.toolbar.setVisible(False)
            self.stack.setCurrentIndex(2)
            self._load_texture_asset(row)

        elif ext == "mtl":
            self.toolbar.setVisible(False)
            self.stack.setCurrentIndex(3)
            self._load_material_asset(row)

        elif ext in ("xml", "tbl", "cfg", "lua", "txt", "json", "ent", "act"):
            self.toolbar.setVisible(False)
            self.stack.setCurrentIndex(4)
            self._load_text_asset(row)

        # Fallback: Unsupported preview format
        else:
            self.toolbar.setVisible(False)
            self.viewport_3d.set_geometry(None)
            self.stack.setCurrentIndex(0)

    def _load_3d_asset(self, row: AssetRow, token: int) -> None:
        # Populate LOD Switcher
        lod_family = find_lod_family(self.ctx.index, row)
        self.current_lod_family = lod_family
        self.lod_cb.blockSignals(True)
        self.lod_cb.clear()

        selected_idx = 0
        for i, item in enumerate(lod_family.lods):
            self.lod_cb.addItem(item.label, item.row)
            if item.row.id == row.id:
                selected_idx = i

        self.lod_cb.setCurrentIndex(selected_idx)
        self.lod_cb.blockSignals(False)

        # Show loading banner
        self.lbl_loading_msg.setText(f"Preparing 3D preview for {row.filename}...")
        self.loading_banner.setVisible(True)

        def run_task(task_ctx):
            def progress(msg: str):
                QTimer.singleShot(0, lambda: self.lbl_loading_msg.setText(msg))

            return prepare_3d_preview(
                row,
                self.ctx.index,
                self.ctx.settings,
                progress_cb=progress,
                cancel_check=lambda: task_ctx.cancelled or token != self._preview_token,
            )

        task = Task(f"Preview {row.filename}", run_task)
        self._active_task = task

        def on_success(result):
            if token != self._preview_token:
                return
            self._active_task = None
            self.loading_banner.setVisible(False)
            glb_path, geom, metadata = result
            self.viewport_3d.set_geometry(geom)

            if metadata.textures_total > 0:
                self.lbl_hud_status.setText(
                    f"Textures: {metadata.textures_resolved}/{metadata.textures_total} resolved · {row.archive_name}"
                )
            else:
                self.lbl_hud_status.setText(f"Cached · {row.archive_name}")

        def on_fail(err_msg):
            if token != self._preview_token:
                return
            self._active_task = None
            self.loading_banner.setVisible(False)
            self.viewport_3d.set_geometry(None)
            self.lbl_hud_status.setText(f"Preview failed: {err_msg}")
            log.warning("3D preview failed for %s: %s", row.filename, err_msg)

        task.signals.finished.connect(on_success)
        task.signals.failed.connect(on_fail)
        self.ctx.tasks.start(task)

    def _on_lod_changed(self, index: int) -> None:
        if index < 0 or not self.current_lod_family:
            return
        target_row = self.lod_cb.itemData(index)
        if target_row and (self.current_row is None or target_row.id != self.current_row.id):
            self.ctx.asset_selected.emit(target_row)

    def _load_texture_asset(self, row: AssetRow) -> None:
        try:
            with PakArchive(row.archive_path) as pak:
                data = pak.read(row.vpath)
            self.texture_viewer.load_texture_data(data, row.filename)
        except Exception as e:
            log.warning("Failed to read texture %s: %s", row.vpath, e)

    def _load_material_asset(self, row: AssetRow) -> None:
        try:
            with PakArchive(row.archive_path) as pak:
                data = pak.read(row.vpath)
            self.material_viewer.load_material_xml(data, row.filename)
        except Exception as e:
            log.warning("Failed to read material %s: %s", row.vpath, e)

    def _on_material_texture_navigate(self, tex_ref: str) -> None:
        hits = self.ctx.index.find_by_vpath(tex_ref)
        if hits:
            self.ctx.asset_selected.emit(hits[0])

    def _load_text_asset(self, row: AssetRow) -> None:
        try:
            with PakArchive(row.archive_path) as pak:
                data = pak.read(row.vpath, max_size=5 * 1024 * 1024)
            text = data.decode("utf-8", errors="replace")
            self.text_viewer.load_text(text, row.filename)
        except Exception as e:
            self.text_viewer.load_text(f"Error loading file: {e}", row.filename)
