"""Shared building blocks so every page follows the same layout grid."""
from __future__ import annotations

from PySide6.QtCore import QRectF, QSize, Qt, Signal
from PySide6.QtGui import QColor, QFont, QFontMetrics, QPainter, QPen
from PySide6.QtWidgets import (
    QApplication,
    QStyle,
    QStyledItemDelegate,
    QStyleOptionViewItem,
    QTableWidgetItem,
    QFrame,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QPushButton,
    QSizePolicy,
    QTableView,
    QVBoxLayout,
    QWidget,
)

from ui import theme
from ui.icons import get_svg_icon

PAGE_MARGINS = (28, 22, 28, 20)
PAGE_SPACING = 16


def page_layout(page: QWidget) -> QVBoxLayout:
    page.setObjectName("Page")
    lay = QVBoxLayout(page)
    lay.setContentsMargins(*PAGE_MARGINS)
    lay.setSpacing(PAGE_SPACING)
    return lay


def label(text: str = "", role: str = "", wrap: bool = False) -> QLabel:
    lbl = QLabel(text)
    if role:
        lbl.setObjectName(role)
    lbl.setWordWrap(wrap)
    return lbl


def button(text: str, icon: str = "", kind: str = "", tooltip: str = "") -> QPushButton:
    btn = QPushButton(text.replace("&", "&&"))
    if kind:
        btn.setObjectName(kind)
    if icon:
        color = theme.ACCENT_TEXT if kind == "Primary" else (theme.ERR if kind == "Danger" else theme.TEXT)
        btn.setIcon(get_svg_icon(icon, color, 16))
    if tooltip:
        btn.setToolTip(tooltip)
    btn.setCursor(Qt.PointingHandCursor)
    return btn


def divider() -> QFrame:
    line = QFrame()
    line.setObjectName("Divider")
    return line


class PageHeader(QWidget):
    def __init__(self, title: str, subtitle: str = "", parent=None):
        super().__init__(parent)
        lay = QHBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 4)
        lay.setSpacing(12)
        text = QVBoxLayout()
        text.setSpacing(3)
        self.title = label(title, "H1")
        text.addWidget(self.title)
        self.subtitle = label(subtitle, "Dim", wrap=True)
        self.subtitle.setVisible(bool(subtitle))
        text.addWidget(self.subtitle)
        lay.addLayout(text, 1)
        self.actions = QHBoxLayout()
        self.actions.setSpacing(8)
        lay.addLayout(self.actions)

    def add_action(self, widget: QWidget) -> QWidget:
        self.actions.addWidget(widget, 0, Qt.AlignBottom)
        return widget


class Card(QFrame):
    def __init__(self, title: str = "", parent=None, inset: bool = False):
        super().__init__(parent)
        self.setObjectName("CardInset" if inset else "Card")
        self.body = QVBoxLayout(self)
        self.body.setContentsMargins(18, 16, 18, 16)
        self.body.setSpacing(10)
        self.header = QHBoxLayout()
        self.header.setSpacing(8)
        if title:
            self.title = label(title.upper(), "Section")
            self.header.addWidget(self.title)
            self.header.addStretch(1)
            self.body.addLayout(self.header)

    def add(self, widget: QWidget, stretch: int = 0) -> QWidget:
        self.body.addWidget(widget, stretch)
        return widget


class ClickableCard(QFrame):
    clicked = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("Tile")
        self.setCursor(Qt.PointingHandCursor)

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.LeftButton and self.rect().contains(event.position().toPoint()):
            self.clicked.emit()
        super().mouseReleaseEvent(event)


class StatusPill(QLabel):
    COLORS = {
        "ok": theme.OK,
        "warn": theme.WARN,
        "error": theme.ERR,
        "info": theme.INFO,
        "accent": theme.ACCENT,
        "muted": theme.TEXT_MUTED,
    }

    def __init__(self, text: str = "", state: str = "muted", parent=None):
        super().__init__(parent)
        self.set(text, state)
        self.setSizePolicy(QSizePolicy.Maximum, QSizePolicy.Fixed)

    def set(self, text: str, state: str = "muted", filled: bool = False) -> None:
        self.setText(text)
        self.setStyleSheet(theme.pill(self.COLORS.get(state, theme.TEXT_MUTED), filled))


class EmptyState(QWidget):
    def __init__(self, icon: str, title: str, text: str = "", parent=None):
        super().__init__(parent)
        lay = QVBoxLayout(self)
        lay.setAlignment(Qt.AlignCenter)
        lay.setSpacing(8)
        art = QLabel()
        art.setPixmap(get_svg_icon(icon, theme.TEXT_MUTED, 40).pixmap(40, 40))
        art.setAlignment(Qt.AlignCenter)
        lay.addWidget(art)
        heading = label(title, "H2")
        heading.setAlignment(Qt.AlignCenter)
        lay.addWidget(heading)
        self.text = label(text, "Dim", wrap=True)
        self.text.setAlignment(Qt.AlignCenter)
        self.text.setMaximumWidth(420)
        lay.addWidget(self.text, 0, Qt.AlignHCenter)
        self.actions = QHBoxLayout()
        self.actions.setAlignment(Qt.AlignCenter)
        lay.addSpacing(6)
        lay.addLayout(self.actions)


PILL_ROLE = Qt.UserRole + 20  # (text, state) of a status pill drawn by PillDelegate


class PillDelegate(QStyledItemDelegate):
    """Paints a status pill in a table cell. Painted pills move with their row; cell widgets lagged behind a
    refill and stacked on top of the first row."""

    PAD_X, MARGIN = 9, 8

    @staticmethod
    def _font(base: QFont) -> QFont:
        font = QFont(base)
        font.setPointSizeF(8.25)
        font.setWeight(QFont.DemiBold)
        return font

    def paint(self, painter: QPainter, option, index) -> None:
        data = index.data(PILL_ROLE)
        if not data:
            return super().paint(painter, option, index)
        opt = QStyleOptionViewItem(option)
        self.initStyleOption(opt, index)
        opt.text = ""
        style = opt.widget.style() if opt.widget else QApplication.style()
        style.drawControl(QStyle.CE_ItemViewItem, opt, painter, opt.widget)
        text, state = data
        color = QColor(StatusPill.COLORS.get(state, theme.TEXT_MUTED))
        font = self._font(opt.font)
        metrics = QFontMetrics(font)
        height = metrics.height() + 6
        width = metrics.horizontalAdvance(text) + 2 * self.PAD_X
        rect = QRectF(opt.rect.x() + self.MARGIN, opt.rect.center().y() - height / 2 + 0.5, width, height)
        painter.save()
        painter.setRenderHint(QPainter.Antialiasing)
        painter.setPen(QPen(color, 1))
        painter.setBrush(Qt.NoBrush)
        painter.drawRoundedRect(rect, height / 2, height / 2)
        painter.setFont(font)
        painter.drawText(rect, Qt.AlignCenter, text)
        painter.restore()

    def sizeHint(self, option, index) -> QSize:
        data = index.data(PILL_ROLE)
        if not data:
            return super().sizeHint(option, index)
        metrics = QFontMetrics(self._font(option.font))
        return QSize(metrics.horizontalAdvance(data[0]) + 2 * (self.PAD_X + self.MARGIN) + 4, metrics.height() + 10)


def set_cell_pill(table, row: int, column: int, text: str, state: str = "muted") -> None:
    # Reusing the holder avoids replaced cell widgets lingering until their deferred delete runs.
    holder = table.cellWidget(row, column)
    if holder is not None and isinstance(getattr(holder, "pill", None), StatusPill):
        holder.pill.set(text, state)
    else:
        holder = QWidget()
        lay = QHBoxLayout(holder)
        lay.setContentsMargins(8, 0, 8, 0)
        holder.pill = StatusPill(text, state)
        lay.addWidget(holder.pill)
        lay.addStretch(1)
        table.setCellWidget(row, column, holder)
    # ResizeToContents ignores cell widgets, and the pill is measured before the app font reaches it.
    item = table.item(row, column) or QTableWidgetItem()
    item.setData(Qt.SizeHintRole, QSize(holder.sizeHint().width() + 28, 0))
    item.setData(Qt.UserRole, text)
    if table.item(row, column) is None:
        table.setItem(row, column, item)


def configure_table(table: QTableView, stretch_column: int = 0, row_height: int = 34) -> None:
    table.setAlternatingRowColors(True)
    table.setShowGrid(False)
    table.setSelectionBehavior(QTableView.SelectRows)
    table.setEditTriggers(QTableView.NoEditTriggers)
    table.verticalHeader().setVisible(False)
    table.verticalHeader().setDefaultSectionSize(row_height)
    header = table.horizontalHeader()
    header.setHighlightSections(False)
    header.setDefaultAlignment(Qt.AlignLeft | Qt.AlignVCenter)
    header.setMinimumSectionSize(60)
    header.setStretchLastSection(False)
    model = table.model()
    columns = model.columnCount() if model is not None else 0
    for col in range(columns):
        mode = QHeaderView.Stretch if col == stretch_column else QHeaderView.ResizeToContents
        header.setSectionResizeMode(col, mode)
