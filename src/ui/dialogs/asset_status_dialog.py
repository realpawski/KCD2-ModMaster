"""What an asset still needs before it works in the game, with a button for each fix."""
from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import QDialog, QFrame, QHBoxLayout, QScrollArea, QVBoxLayout, QWidget

from ui import theme
from ui.icons import get_svg_icon
from ui.widgets import StatusPill, button, label
from workspace.asset_model import AssetStatus, ValidationReport, WorkspaceAsset

SEVERITY = {"error": ("x-circle", theme.ERR), "warning": ("warning", theme.WARN), "info": ("check-circle", theme.OK)}
ACTION_LABELS = {"open_blender": ("Open in Blender", "blender"), "add_to_mod": ("Add to mod", "puzzle")}
STATUS_TEXT = {AssetStatus.READY.value: ("Ready for the game", "ok"),
               AssetStatus.WARNING.value: ("Needs attention", "warn"),
               AssetStatus.INVALID.value: ("Has a problem", "error")}


class AssetStatusDialog(QDialog):
    action_requested = Signal(str)
    recheck_requested = Signal()

    def __init__(self, asset: WorkspaceAsset, report: ValidationReport, parent=None):
        super().__init__(parent)
        self.setWindowTitle(f"Status — {asset.name}")
        self.resize(620, 460)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(24, 22, 24, 20)
        lay.setSpacing(12)
        head = QHBoxLayout()
        head.addWidget(label(asset.name, "H1"))
        text, state = STATUS_TEXT.get(asset.status, (asset.status.title(), "muted"))
        head.addWidget(StatusPill(text, state))
        head.addStretch(1)
        lay.addLayout(head)
        todo = [i for i in report.issues if i.severity != "info"]
        lay.addWidget(label(f"{len(todo)} thing{'s' * (len(todo) != 1)} to do before it works in the game."
                            if todo else "Everything the game needs is in place.", "Muted"))

        body = QWidget()
        rows = QVBoxLayout(body)
        rows.setContentsMargins(0, 0, 0, 0)
        rows.setSpacing(8)
        order = {"error": 0, "warning": 1, "info": 2}
        for issue in sorted(report.issues, key=lambda i: order.get(i.severity, 3)):
            rows.addWidget(self._row(issue))
        rows.addStretch(1)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        scroll.setWidget(body)
        lay.addWidget(scroll, 1)

        foot = QHBoxLayout()
        recheck = button("Check again", "arrow-path")
        recheck.clicked.connect(self.recheck_requested.emit)
        foot.addWidget(recheck)
        foot.addStretch(1)
        close = button("Close", "", "Primary")
        close.clicked.connect(self.accept)
        foot.addWidget(close)
        lay.addLayout(foot)

    def _row(self, issue) -> QWidget:
        card = QFrame()
        card.setObjectName("Card")
        row = QHBoxLayout(card)
        row.setContentsMargins(12, 10, 12, 10)
        row.setSpacing(10)
        icon_name, color = SEVERITY.get(issue.severity, ("info", theme.TEXT_MUTED))
        icon = label("")
        icon.setPixmap(get_svg_icon(icon_name, color, 18).pixmap(18, 18))
        icon.setAlignment(Qt.AlignTop)
        row.addWidget(icon)
        text = QVBoxLayout()
        text.setSpacing(2)
        text.addWidget(label(issue.message, wrap=True))
        if issue.fix:
            text.addWidget(label(issue.fix, "Muted", wrap=True))
        row.addLayout(text, 1)
        if issue.action in ACTION_LABELS:
            title, icon_key = ACTION_LABELS[issue.action]
            act = button(title, icon_key)
            act.clicked.connect(lambda _=False, a=issue.action: self.action_requested.emit(a))
            row.addWidget(act, 0, Qt.AlignVCenter)
        return card
