"""Bottom activity bar: task progress and a collapsible log."""
from __future__ import annotations

import html
import time

from PySide6.QtCore import Signal
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QPlainTextEdit,
    QProgressBar,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from ui import theme
from ui.icons import get_svg_icon

LEVEL_COLORS = {"DEBUG": theme.TEXT_DIM, "INFO": theme.TEXT, "WARNING": theme.WARN, "ERROR": theme.ERR,
                "CRITICAL": theme.ERR, "OK": theme.OK, "TASK": theme.ACCENT}


class ConsoleWidget(QWidget):
    collapse_toggled = Signal(bool)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.is_collapsed = False
        self.setStyleSheet(f"background: {theme.BG0};")
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(0)

        bar_frame = QFrame()
        bar_frame.setStyleSheet(f"QFrame {{ background: {theme.BG1}; border-top: 1px solid {theme.BORDER}; }}")
        bar_frame.setFixedHeight(36)
        bar = QHBoxLayout(bar_frame)
        bar.setContentsMargins(14, 2, 10, 2)
        bar.setSpacing(6)
        self.status = QLabel("Ready")
        self.status.setObjectName("Muted")
        self.progress = QProgressBar()
        self.progress.setFixedWidth(200)
        self.progress.setFixedHeight(8)
        self.progress.setVisible(False)
        self.cancel_btn = QPushButton("Cancel")
        self.cancel_btn.setObjectName("Ghost")
        self.cancel_btn.setIcon(get_svg_icon("x-mark", theme.TEXT_DIM, 14))
        self.cancel_btn.setVisible(False)
        clear = QPushButton("Clear")
        clear.setObjectName("Ghost")
        clear.setIcon(get_svg_icon("arrow-path", theme.TEXT_DIM, 14))
        clear.clicked.connect(lambda: self.text.clear())

        self.btn_collapse = QPushButton("Log")
        self.btn_collapse.setObjectName("Ghost")
        self.btn_collapse.setIcon(get_svg_icon("chevron-down", theme.TEXT_DIM, 14))
        self.btn_collapse.setToolTip("Show or hide the activity log")
        self.btn_collapse.clicked.connect(self.toggle_collapsed)

        bar.addWidget(self.status, 1)
        bar.addWidget(self.progress)
        bar.addWidget(self.cancel_btn)
        bar.addWidget(clear)
        bar.addWidget(self.btn_collapse)
        lay.addWidget(bar_frame)
        self.text = QPlainTextEdit()
        self.text.setObjectName("Console")
        self.text.setReadOnly(True)
        self.text.setMaximumBlockCount(5000)
        lay.addWidget(self.text)

    def toggle_collapsed(self) -> None:
        self.set_collapsed(not self.is_collapsed)

    def set_collapsed(self, collapsed: bool) -> None:
        self.is_collapsed = collapsed
        self.text.setVisible(not collapsed)
        self.btn_collapse.setText("Show log" if collapsed else "Hide log")
        self.btn_collapse.setIcon(get_svg_icon("chevron-up" if collapsed else "chevron-down", theme.TEXT_DIM, 14))
        self.collapse_toggled.emit(collapsed)

    def append(self, level: str, message: str) -> None:
        color = LEVEL_COLORS.get(level, theme.TEXT)
        ts = time.strftime("%H:%M:%S")
        lines = html.escape(message).replace("\n", "<br>&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;")
        tag = "" if level in ("INFO",) else f"<b>{level}</b> "
        self.text.appendHtml(f'<span style="color:{theme.TEXT_DIM}">{ts}</span>&nbsp; '
                             f'<span style="color:{color}">{tag}{lines}</span>')

    def set_progress(self, current: int, total: int, message: str) -> None:
        self.progress.setVisible(True)
        self.cancel_btn.setVisible(True)
        self.progress.setMaximum(max(total, 1))
        self.progress.setValue(current)
        self.status.setText(message)

    def idle(self, message: str = "Ready") -> None:
        self.progress.setVisible(False)
        self.cancel_btn.setVisible(False)
        self.status.setText(message)
