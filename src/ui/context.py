"""Shared application state passed to every UI component."""
from __future__ import annotations

import logging
from pathlib import Path

from PySide6.QtCore import QObject, Signal

from core.config import Settings
from core.tasks import TaskManager
from database.index import AssetIndex, AssetRow

log = logging.getLogger(__name__)


class AppContext(QObject):
    index_changed = Signal()
    settings_changed = Signal()
    asset_selected = Signal(object)            # AssetRow | None
    extract_requested = Signal(list, bool)     # rows, with_companions
    extract_to_requested = Signal(list, bool)
    navigate = Signal(str, dict)               # page key, options
    extracted = Signal(list)                   # list[Path]

    mods_changed = Signal()

    def __init__(self, settings: Settings):
        super().__init__()
        self.settings = settings
        self.tasks = TaskManager(self)
        self._index: AssetIndex | None = None
        self._catalog = None
        self._catalog_game: str | None = None
        self.settings_changed.connect(self._drop_catalog)

    def _drop_catalog(self) -> None:
        self._catalog = None

    def item_catalog(self):
        """Vanilla item catalog for the configured game. Raises GameDataUnavailable."""
        from items.gamedata import GameDataUnavailable, ItemCatalog
        game = self.settings.game_dir
        if not game:
            raise GameDataUnavailable("Set the Kingdom Come: Deliverance II folder in Settings.")
        if self._catalog is None or self._catalog_game != game:
            self.settings.ensure_workspace()
            self._catalog = ItemCatalog.load(Path(game), self.settings.workspace / "cache")
            self._catalog_game = game
        return self._catalog

    @property
    def index(self) -> AssetIndex:
        if self._index is None:
            self.settings.ensure_workspace()
            self._index = AssetIndex(self.settings.database_path)
        return self._index

    def reopen_index(self) -> None:
        if self._index is not None:
            self._index.close()
            self._index = None
        self.index_changed.emit()

    def protected_dirs(self) -> list[Path]:
        out = []
        for d in (self.settings.game_dir, self.settings.tools_dir):
            if d:
                out.append(Path(d))
        return out

    def extracted_path(self, row: AssetRow) -> Path:
        return self.settings.workspace / "extracted" / Path(*row.vpath.split("/"))

    def shutdown(self) -> None:
        self.tasks.cancel_all()
        self.tasks.wait(3000)
        if self._index is not None:
            self._index.close()
