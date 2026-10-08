"""KCD2 Material (.mtl) Inspector widget."""
from __future__ import annotations

import xml.etree.ElementTree as ET
from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QPlainTextEdit,
    QPushButton,
    QScrollArea,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

from ui import theme


class MaterialViewer(QWidget):
    texture_navigate_requested = Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent)

        lay = QVBoxLayout(self)
        lay.setContentsMargins(16, 12, 16, 12)
        lay.setSpacing(10)

        # Header bar
        header = QHBoxLayout()
        self.title = QLabel("Material Inspector (.mtl)")
        self.title.setObjectName("H2")
        header.addWidget(self.title)
        header.addStretch(1)

        self.btn_view_xml = QPushButton("Raw XML")
        self.btn_view_xml.setCheckable(True)
        self.btn_view_xml.clicked.connect(self._toggle_raw_view)
        header.addWidget(self.btn_view_xml)
        lay.addLayout(header)

        # Tree view of sub-materials and texture slots
        self.tree = QTreeWidget()
        self.tree.setHeaderLabels(["Material / Slot", "Value / Target File"])
        self.tree.setColumnWidth(0, 220)
        self.tree.itemDoubleClicked.connect(self._on_item_double_clicked)
        lay.addWidget(self.tree, 1)

        # Raw XML text editor (toggleable)
        self.raw_text = QPlainTextEdit()
        self.raw_text.setReadOnly(True)
        self.raw_text.setObjectName("Console")
        self.raw_text.setVisible(False)
        lay.addWidget(self.raw_text, 1)

    def _toggle_raw_view(self, checked: bool) -> None:
        self.tree.setVisible(not checked)
        self.raw_text.setVisible(checked)
        self.btn_view_xml.setText("Tree View" if checked else "Raw XML")

    def load_material_xml(self, raw_bytes: bytes, filename: str) -> None:
        self.title.setText(f"Material: {filename}")
        text = raw_bytes.decode("utf-8", errors="replace")
        self.raw_text.setPlainText(text)

        self.tree.clear()
        try:
            root = ET.fromstring(raw_bytes)
        except Exception as e:
            item = QTreeWidgetItem(["Error parsing MTL", str(e)])
            self.tree.addTopLevelItem(item)
            return

        # Build tree
        def populate_mat_node(mat_elem, parent_item):
            name = mat_elem.get("Name", "SubMaterial")
            shader = mat_elem.get("Shader", "")
            diffuse = mat_elem.get("Diffuse", "")
            specular = mat_elem.get("Specular", "")

            mat_node = QTreeWidgetItem(parent_item, [f"Material: {name}", f"Shader: {shader}"])
            if diffuse:
                QTreeWidgetItem(mat_node, ["Diffuse Color", diffuse])
            if specular:
                QTreeWidgetItem(mat_node, ["Specular Color", specular])

            # Textures
            for tex_parent in mat_elem.findall("Textures"):
                for tex in tex_parent.findall("Texture"):
                    map_slot = tex.get("Map", "Texture")
                    file_ref = tex.get("File", "")
                    tex_item = QTreeWidgetItem(mat_node, [f"Map: {map_slot}", file_ref])
                    tex_item.setData(0, Qt.UserRole, file_ref)

            # SubMaterials
            for sub_parent in mat_elem.findall("SubMaterials"):
                for sub in sub_parent.findall("Material"):
                    populate_mat_node(sub, mat_node)

        if root.tag == "Material":
            subs = root.findall(".//SubMaterials/Material")
            if subs:
                for s in subs:
                    populate_mat_node(s, self.tree)
            else:
                populate_mat_node(root, self.tree)

        self.tree.expandAll()

    def _on_item_double_clicked(self, item: QTreeWidgetItem, column: int) -> None:
        ref = item.data(0, Qt.UserRole)
        if ref:
            self.texture_navigate_requested.emit(ref)
