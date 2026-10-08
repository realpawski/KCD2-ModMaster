"""New Mod Asset Wizard for importing external 3D models or creating new assets."""
from __future__ import annotations

import re
import shutil
import time
from pathlib import Path
from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QButtonGroup,
    QComboBox,
    QDialog,
    QFileDialog,
    QFormLayout,
    QFrame,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QRadioButton,
    QStackedWidget,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from mods.project import ModManager, slugify_mod_id
from ui.context import AppContext
from ui.dialogs.create_mod_dialog import CreateModDialog
from ui.icons import get_svg_icon
from workspace.asset_model import AssetStatus, AssetType, WorkspaceAsset, validate_workspace_asset


class NewAssetWizard(QDialog):
    """6-Step Wizard for introducing new custom assets into ModMaster workspace."""

    def __init__(self, ctx: AppContext, parent=None):
        super().__init__(parent)
        self.ctx = ctx
        self.mod_mgr = ModManager(self.ctx.settings.workspace)
        self.created_asset: WorkspaceAsset | None = None

        self.setWindowTitle("New Mod Asset Wizard")
        self.resize(650, 520)
        self.setModal(True)

        self.step_idx = 0

        lay = QVBoxLayout(self)
        lay.setContentsMargins(24, 20, 24, 20)
        lay.setSpacing(16)

        # Header with Step Indicator
        self.header = QFrame()
        h_lay = QHBoxLayout(self.header)
        h_lay.setContentsMargins(0, 0, 0, 0)

        self.lbl_step_num = QLabel("STEP 1 OF 5")
        self.lbl_step_num.setObjectName("Badge")
        self.lbl_step_num.setStyleSheet("font-size: 8pt; font-weight: 700; padding: 2px 8px;")

        self.lbl_step_title = QLabel("Select Asset Source")
        self.lbl_step_title.setStyleSheet("font-size: 13pt; font-weight: 700; color: #e9ebef;")

        h_lay.addWidget(self.lbl_step_num)
        h_lay.addSpacing(10)
        h_lay.addWidget(self.lbl_step_title)
        h_lay.addStretch(1)
        lay.addWidget(self.header)

        # Main Stacked Pages
        self.stack = QStackedWidget()

        # Page 0: Source
        self.p_source = self._build_source_page()
        self.stack.addWidget(self.p_source)

        # Page 1: Type
        self.p_type = self._build_type_page()
        self.stack.addWidget(self.p_type)

        # Page 2: Name
        self.p_name = self._build_name_page()
        self.stack.addWidget(self.p_name)

        # Page 3: Mod
        self.p_mod = self._build_mod_page()
        self.stack.addWidget(self.p_mod)

        # Page 4: Validation & Creation
        self.p_val = self._build_validation_page()
        self.stack.addWidget(self.p_val)

        lay.addWidget(self.stack, 1)

        # Bottom Navigation Controls
        btn_box = QHBoxLayout()
        self.btn_cancel = QPushButton("Cancel")
        self.btn_cancel.clicked.connect(self.reject)

        self.btn_back = QPushButton("Back")
        self.btn_back.clicked.connect(self._prev_step)
        self.btn_back.setEnabled(False)

        self.btn_next = QPushButton("Next")
        self.btn_next.setObjectName("Primary")
        self.btn_next.clicked.connect(self._next_step)

        btn_box.addWidget(self.btn_cancel)
        btn_box.addStretch(1)
        btn_box.addWidget(self.btn_back)
        btn_box.addWidget(self.btn_next)
        lay.addLayout(btn_box)

    # Step 1: Source
    def _build_source_page(self) -> QWidget:
        w = QWidget()
        lay = QVBoxLayout(w)
        lay.setSpacing(14)

        desc = QLabel("Choose how you want to bring this asset into KCD2 ModMaster:")
        desc.setObjectName("Dim")
        lay.addWidget(desc)

        self.rb_import_file = QRadioButton("Import Existing 3D Model File (.blend, FBX, GLTF / GLB, OBJ)")
        self.rb_import_file.setChecked(True)

        self.file_picker_row = QHBoxLayout()
        self.txt_source_file = QLineEdit()
        self.txt_source_file.setPlaceholderText("Select model file from disk…")
        self.btn_browse = QPushButton("Browse…")
        self.btn_browse.setIcon(get_svg_icon("folder", "#e9ebef", 14))
        self.btn_browse.clicked.connect(self._browse_source_file)
        self.file_picker_row.addWidget(self.txt_source_file, 1)
        self.file_picker_row.addWidget(self.btn_browse)

        self.rb_vanilla = QRadioButton("Create From Vanilla KCD2 Asset (Extract working copy)")
        self.txt_vanilla_vpath = QLineEdit()
        self.txt_vanilla_vpath.setPlaceholderText("e.g. Objects/props/furniture/chairs/chair_a.cgf")
        self.txt_vanilla_vpath.setEnabled(False)

        self.rb_blender_scene = QRadioButton("Current Active Blender 5.2 Scene")

        lay.addWidget(self.rb_import_file)
        lay.addLayout(self.file_picker_row)
        lay.addSpacing(10)
        lay.addWidget(self.rb_vanilla)
        lay.addWidget(self.txt_vanilla_vpath)
        lay.addSpacing(10)
        lay.addWidget(self.rb_blender_scene)
        lay.addStretch(1)

        self.rb_import_file.toggled.connect(lambda chk: self.txt_source_file.setEnabled(chk))
        self.rb_vanilla.toggled.connect(lambda chk: self.txt_vanilla_vpath.setEnabled(chk))

        return w

    def _browse_source_file(self) -> None:
        chosen, _ = QFileDialog.getOpenFileName(
            self,
            "Select 3D Model File",
            "",
            "3D Models (*.blend *.fbx *.glb *.gltf *.obj);;Blender (*.blend);;FBX (*.fbx);;GLTF (*.glb *.gltf);;OBJ (*.obj);;All Files (*.*)",
        )
        if chosen:
            self.txt_source_file.setText(chosen)
            stem = Path(chosen).stem
            self.txt_asset_name.setText(stem.replace("_", " ").title())
            self.txt_asset_id.setText(slugify_mod_id(stem))

    # Step 2: Asset Type
    def _build_type_page(self) -> QWidget:
        w = QWidget()
        lay = QVBoxLayout(w)
        lay.setSpacing(12)

        desc = QLabel("Select the KCD2 asset category and pipeline type:")
        desc.setObjectName("Dim")
        lay.addWidget(desc)

        self.type_group = QButtonGroup(self)
        types = [
            ("Static Prop", "Decorations, furniture, architecture, containers, clutter (Fully Supported)", True),
            ("Weapon", "Swords, polearms, axes, bows (Experimental)", False),
            ("Armor", "Helmets, cuirasses, boots, gauntlets (Experimental)", False),
            ("Character", "NPCs, creatures, animals, heads (Experimental)", False),
            ("Other", "Custom CryEngine entities and interactive props (Experimental)", False),
        ]

        self.type_rbs: list[QRadioButton] = []
        for i, (name, note, recommended) in enumerate(types):
            card = QFrame()
            card.setObjectName("Card")
            c_lay = QVBoxLayout(card)
            c_lay.setContentsMargins(12, 10, 12, 10)
            c_lay.setSpacing(4)

            rb = QRadioButton(f"<b>{name}</b>" + ("  (RECOMMENDED)" if recommended else ""))
            if i == 0:
                rb.setChecked(True)
            self.type_group.addButton(rb, i)
            self.type_rbs.append(rb)

            sub = QLabel(note)
            sub.setObjectName("Dim")
            sub.setStyleSheet("font-size: 8.5pt; color: #a2a8b5; margin-left: 20px;")

            c_lay.addWidget(rb)
            c_lay.addWidget(sub)
            lay.addWidget(card)

        lay.addStretch(1)
        return w

    # Step 3: Naming
    def _build_name_page(self) -> QWidget:
        w = QWidget()
        lay = QVBoxLayout(w)
        lay.setSpacing(14)

        desc = QLabel("Assign human-readable and internal identifier names for this asset:")
        desc.setObjectName("Dim")
        lay.addWidget(desc)

        form = QFormLayout()
        form.setSpacing(12)

        self.txt_asset_name = QLineEdit()
        self.txt_asset_name.setPlaceholderText("e.g. Pawski Test Barrel")
        self.txt_asset_name.textChanged.connect(self._on_display_name_changed)

        self.txt_asset_id = QLineEdit()
        self.txt_asset_id.setPlaceholderText("e.g. pawski_test_barrel")

        form.addRow("Display Name:", self.txt_asset_name)
        form.addRow("Internal Asset ID:", self.txt_asset_id)
        lay.addLayout(form)

        hint = QLabel(
            "Note: The internal Asset ID will be used for workspace directory naming, "
            "interchange files, and in-game entity registry generation."
        )
        hint.setObjectName("Dim")
        hint.setWordWrap(True)
        lay.addWidget(hint)
        lay.addStretch(1)
        return w

    def _on_display_name_changed(self, text: str) -> None:
        if not self.txt_asset_id.isModified():
            self.txt_asset_id.setText(slugify_mod_id(text))

    # Step 4: Mod Assignment
    def _build_mod_page(self) -> QWidget:
        w = QWidget()
        lay = QVBoxLayout(w)
        lay.setSpacing(14)

        desc = QLabel("Assign this asset to a Mod Project (or keep it as an unassigned workspace asset):")
        desc.setObjectName("Dim")
        lay.addWidget(desc)

        row = QHBoxLayout()
        self.cb_mod = QComboBox()
        self.btn_new_mod = QPushButton("Create New Mod…")
        self.btn_new_mod.setIcon(get_svg_icon("plus", "#e9ebef", 14))
        self.btn_new_mod.clicked.connect(self._open_create_mod)

        row.addWidget(self.cb_mod, 1)
        row.addWidget(self.btn_new_mod)
        lay.addLayout(row)

        self.lbl_mod_desc = QLabel("No mod selected.")
        self.lbl_mod_desc.setObjectName("Dim")
        self.lbl_mod_desc.setWordWrap(True)
        lay.addWidget(self.lbl_mod_desc)

        lay.addStretch(1)
        self._refresh_mods_list()
        self.cb_mod.currentIndexChanged.connect(self._on_mod_selected)
        return w

    def _refresh_mods_list(self) -> None:
        self.cb_mod.clear()
        self.cb_mod.addItem("None (Standalone Workspace Asset)", "")
        mods = self.mod_mgr.list_mods()
        for m in mods:
            self.cb_mod.addItem(f"{m.name} ({m.id})", m.id)

    def _open_create_mod(self) -> None:
        dlg = CreateModDialog(self.ctx, self)
        if dlg.exec() == QDialog.Accepted and dlg.created_mod:
            self._refresh_mods_list()
            idx = self.cb_mod.findData(dlg.created_mod.id)
            if idx >= 0:
                self.cb_mod.setCurrentIndex(idx)

    def _on_mod_selected(self) -> None:
        mod_id = self.cb_mod.currentData()
        if not mod_id:
            self.lbl_mod_desc.setText("Asset will remain in Workspace/Assets/ without being tied to a specific mod package.")
        else:
            mod = self.mod_mgr.get_mod(mod_id)
            if mod:
                self.lbl_mod_desc.setText(f"Mod: {mod.name} (v{mod.version}) by {mod.author or 'Unknown'}\nPath: {mod.project_dir}")

    # Step 5: Validation & Create
    def _build_validation_page(self) -> QWidget:
        w = QWidget()
        lay = QVBoxLayout(w)
        lay.setSpacing(12)

        desc = QLabel("Pre-flight Validation & Summary:")
        desc.setObjectName("H2")
        lay.addWidget(desc)

        self.txt_summary = QTextEdit()
        self.txt_summary.setReadOnly(True)
        lay.addWidget(self.txt_summary, 1)
        return w

    # Navigation logic
    def _update_step_ui(self) -> None:
        titles = [
            "Select Asset Source",
            "Choose Asset Type",
            "Asset Naming",
            "Assign to Mod Project",
            "Pre-Flight Validation & Create",
        ]
        self.lbl_step_num.setText(f"STEP {self.step_idx + 1} OF {len(titles)}")
        self.lbl_step_title.setText(titles[self.step_idx])
        self.stack.setCurrentIndex(self.step_idx)

        self.btn_back.setEnabled(self.step_idx > 0)
        self.btn_next.setText("Create Asset" if self.step_idx == len(titles) - 1 else "Next")

    def _prev_step(self) -> None:
        if self.step_idx > 0:
            self.step_idx -= 1
            self._update_step_ui()

    def _next_step(self) -> None:
        if self.step_idx == 0:
            if self.rb_import_file.isChecked() and not self.txt_source_file.text().strip():
                QMessageBox.warning(self, "Source File Required", "Please choose a 3D model file to import.")
                return
        elif self.step_idx == 2:
            if not self.txt_asset_name.text().strip():
                QMessageBox.warning(self, "Name Required", "Please enter an asset name.")
                return

        if self.step_idx == 3:
            # Entering validation page
            self._update_summary()

        if self.step_idx < self.stack.count() - 1:
            self.step_idx += 1
            self._update_step_ui()
        else:
            self._create_workspace_asset()

    def _get_selected_type(self) -> str:
        idx = self.type_group.checkedId()
        types = [AssetType.STATIC_PROP.value, AssetType.WEAPON.value, AssetType.ARMOR.value, AssetType.CHARACTER.value, AssetType.OTHER.value]
        return types[idx] if 0 <= idx < len(types) else AssetType.STATIC_PROP.value

    def _update_summary(self) -> None:
        source_desc = self.txt_source_file.text() if self.rb_import_file.isChecked() else (
            self.txt_vanilla_vpath.text() if self.rb_vanilla.isChecked() else "Active Blender Scene"
        )
        mod_id = self.cb_mod.currentData() or "None"
        asset_id = slugify_mod_id(self.txt_asset_id.text() or self.txt_asset_name.text())

        summary = (
            f"=== NEW WORKSPACE ASSET SUMMARY ===\n"
            f"Asset ID:      {asset_id}\n"
            f"Display Name:  {self.txt_asset_name.text()}\n"
            f"Asset Type:    {self._get_selected_type()}\n"
            f"Source:        {source_desc}\n"
            f"Assigned Mod:  {mod_id}\n\n"
            f"=== PIPELINE TARGET ===\n"
            f"Workspace Dir: {self.ctx.settings.workspace / 'Assets' / asset_id}\n"
            f"Blend File:    {self.ctx.settings.workspace / 'Assets' / asset_id / 'blender' / f'{asset_id}.blend'}\n\n"
            f"Ready to initialize workspace structure and stage files."
        )
        self.txt_summary.setPlainText(summary)

    def _create_workspace_asset(self) -> None:
        asset_id = slugify_mod_id(self.txt_asset_id.text() or self.txt_asset_name.text())
        name = self.txt_asset_name.text().strip() or asset_id
        asset_type = self._get_selected_type()
        mod_id = self.cb_mod.currentData() or ""

        ws_root = self.ctx.settings.workspace / "Assets" / asset_id
        source_dir = ws_root / "source"
        textures_dir = ws_root / "textures"
        blender_dir = ws_root / "blender"
        export_dir = ws_root / "export"
        meta_dir = ws_root / "metadata"

        for d in (source_dir, textures_dir, blender_dir, export_dir, meta_dir):
            d.mkdir(parents=True, exist_ok=True)

        blend_file = blender_dir / f"{asset_id}.blend"
        source_file = ""

        # Copy source file if specified
        if self.rb_import_file.isChecked():
            p_src = Path(self.txt_source_file.text().strip())
            if p_src.is_file():
                source_file = str(source_dir / p_src.name)
                shutil.copy2(p_src, source_file)
                if p_src.suffix.lower() == ".blend":
                    blend_file = blender_dir / p_src.name
                    shutil.copy2(p_src, blend_file)

        asset = WorkspaceAsset(
            asset_id=asset_id,
            name=name,
            asset_type=asset_type,
            source_type="imported" if self.rb_import_file.isChecked() else ("vanilla_copy" if self.rb_vanilla.isChecked() else "blender_scene"),
            source_file=source_file,
            workspace_dir=str(ws_root),
            blend_file=str(blend_file),
            mod_id=mod_id,
            status=AssetStatus.EDITING.value,
        )

        validate_workspace_asset(asset)
        asset.save()

        # Assign to ModProject if selected
        if mod_id:
            mod = self.mod_mgr.get_mod(mod_id)
            if mod:
                mod.assign_asset(asset_id)

        self.created_asset = asset
        self.accept()
