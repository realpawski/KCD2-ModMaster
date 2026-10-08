"""Structured text / script / xml viewer for KCD2 data files."""
from __future__ import annotations

from PySide6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QPlainTextEdit,
    QVBoxLayout,
    QWidget,
)


class TextViewer(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)

        lay = QVBoxLayout(self)
        lay.setContentsMargins(16, 12, 16, 12)
        lay.setSpacing(8)

        header = QHBoxLayout()
        self.lbl_title = QLabel("Text Viewer")
        self.lbl_title.setObjectName("H2")
        self.lbl_size = QLabel("")
        self.lbl_size.setObjectName("Dim")

        header.addWidget(self.lbl_title)
        header.addStretch(1)
        header.addWidget(self.lbl_size)
        lay.addLayout(header)

        self.editor = QPlainTextEdit()
        self.editor.setObjectName("Console")
        self.editor.setReadOnly(True)
        lay.addWidget(self.editor, 1)

    def load_text(self, text: str, filename: str) -> None:
        self.lbl_title.setText(filename)
        self.lbl_size.setText(f"{len(text):,} characters")
        self.editor.setPlainText(text)
