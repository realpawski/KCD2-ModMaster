"""Table model for asset search results."""
from __future__ import annotations

from PySide6.QtCore import QAbstractTableModel, QModelIndex, Qt
from PySide6.QtGui import QColor

from database.index import AssetRow
from kcd2.formats import pretty_folder
from utils.helpers import human_size

COLUMNS = ("Name", "Type", "Location", "Archive", "Size")

TYPE_COLORS = {
    "cgf": "#7fb7e0", "cgfm": "#6a95b8", "skin": "#c59be0", "chr": "#c59be0", "cga": "#7fb7e0",
    "mtl": "#e0b36a", "dds": "#82c99a", "dds-part": "#5f8a6d", "xml": "#a8a49b",
}


class AssetTableModel(QAbstractTableModel):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.rows: list[AssetRow] = []
        self.show_vpath = False

    def set_rows(self, rows: list[AssetRow]) -> None:
        self.beginResetModel()
        self.rows = rows
        self.endResetModel()

    def set_show_vpath(self, on: bool) -> None:
        self.show_vpath = on
        if self.rows:
            self.dataChanged.emit(self.index(0, 2), self.index(len(self.rows) - 1, 2))

    def rowCount(self, parent=QModelIndex()):
        return 0 if parent.isValid() else len(self.rows)

    def columnCount(self, parent=QModelIndex()):
        return len(COLUMNS)

    def headerData(self, section, orientation, role=Qt.DisplayRole):
        if role == Qt.DisplayRole and orientation == Qt.Horizontal:
            return COLUMNS[section]
        return None

    def data(self, index, role=Qt.DisplayRole):
        if not index.isValid():
            return None
        r = self.rows[index.row()]
        c = index.column()
        if role == Qt.DisplayRole:
            if c == 0:
                return r.filename
            if c == 1:
                return r.ext.upper()
            if c == 2:
                if self.show_vpath:
                    return r.vpath.rsplit("/", 1)[0] if "/" in r.vpath else ""
                return pretty_folder(r.vpath)
            if c == 3:
                return r.archive_name
            if c == 4:
                return human_size(r.size)
        elif role == Qt.ForegroundRole:
            if c == 1:
                return QColor(TYPE_COLORS.get(r.ext, "#9a978f"))
            if c in (2, 3, 4):
                return QColor("#9a978f")
        elif role == Qt.ToolTipRole:
            return f"{r.vpath}\n{r.archive_name}"
        elif role == Qt.TextAlignmentRole and c == 4:
            return int(Qt.AlignRight | Qt.AlignVCenter)
        elif role == Qt.UserRole:
            return r
        return None
