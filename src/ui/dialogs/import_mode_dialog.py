"""Asks whether a character or animal goes to Blender as a static mesh or with its skeleton."""
from __future__ import annotations

from pathlib import Path

from PySide6.QtWidgets import QButtonGroup, QDialog, QFrame, QHBoxLayout, QRadioButton, QVBoxLayout

from ui.widgets import button, label


class ImportModeDialog(QDialog):
    def __init__(self, filename: str, rig_file: str, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Import into Blender")
        self.setModal(True)
        self.setMinimumWidth(520)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(24, 22, 24, 20)
        lay.setSpacing(14)
        lay.addWidget(label("Import into Blender", "H2"))
        lay.addWidget(label(f"{filename} has a skeleton. How do you want to work on it?", "Dim", wrap=True))

        self.group = QButtonGroup(self)
        self.rb_static = self._option(lay, "Static model",
                                      "Mesh only, in its rest pose. Export it back as a prop or as the "
                                      "model of an item (.cgf).")
        self.rb_rigged = self._option(lay, "Rigged model",
                                      f"Mesh with skin weights and the game skeleton from {rig_file}. "
                                      "For characters and animals that should keep moving.")
        self.rb_rigged.setChecked(True)

        row = QHBoxLayout()
        row.addStretch(1)
        cancel = button("Cancel")
        cancel.clicked.connect(self.reject)
        ok = button("Import", "arrow-down-tray", "Primary")
        ok.clicked.connect(self.accept)
        row.addWidget(cancel)
        row.addWidget(ok)
        lay.addSpacing(6)
        lay.addLayout(row)

    def _option(self, lay: QVBoxLayout, title: str, text: str) -> QRadioButton:
        box = QFrame()
        box.setObjectName("CardInset")
        inner = QVBoxLayout(box)
        inner.setContentsMargins(14, 12, 14, 12)
        inner.setSpacing(4)
        radio = QRadioButton(title)
        self.group.addButton(radio)
        inner.addWidget(radio)
        hint = label(text, "Muted", wrap=True)
        hint.setContentsMargins(26, 0, 0, 0)
        inner.addWidget(hint)
        lay.addWidget(box)
        return radio

    @property
    def mode(self) -> str:
        return "rigged" if self.rb_rigged.isChecked() else "static"


def choose_import_mode(parent, bridge_mgr, row, index) -> str | None:
    """'static' or 'rigged'; None when cancelled. Models without a skeleton skip the question."""
    source = bridge_mgr.rig_source(row, index)
    if source is None:
        return "static"
    dialog = ImportModeDialog(row.filename, Path(source.vpath).name, parent)
    return dialog.mode if dialog.exec() == QDialog.Accepted else None
