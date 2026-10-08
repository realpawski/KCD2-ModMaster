"""Settings section for the in-game companion mod."""
from __future__ import annotations

import csv
import io
import os
import subprocess
from pathlib import Path

from PySide6.QtWidgets import QGridLayout, QHBoxLayout, QMenu, QMessageBox, QVBoxLayout, QWidget

from core.tasks import Task, UserFacingError
from kcd2.detect import GAME_EXE_REL
from runtime_tools import RUNTIME_VERSION
from runtime_tools.manager import RuntimeManager
from ui.widgets import Card, StatusPill, button, label
from utils.helpers import reveal_in_explorer

STEAM_RUN = "steam://rungameid/1771300"
STATES = {
    "Installed": ("Installed", "ok", "Reinstall"),
    "Update available": ("Update available", "warn", "Update"),
    "Not installed": ("Not installed", "muted", "Install"),
}


def game_running() -> str:
    if os.name != "nt":
        return "Unknown"
    try:
        result = subprocess.run(["tasklist", "/FI", "IMAGENAME eq KingdomCome.exe", "/FO", "CSV", "/NH"],
                                capture_output=True, text=True, encoding="oem", errors="replace",
                                timeout=5, creationflags=0x08000000)
        if result.returncode:
            return "Unknown"
        rows = csv.reader(io.StringIO(result.stdout))
        return "Running" if any(row and row[0].lower() == "kingdomcome.exe" for row in rows) else "Not running"
    except (OSError, subprocess.TimeoutExpired):
        return "Unknown"


class RuntimeToolsPanel(QWidget):
    def __init__(self, ctx, parent=None):
        super().__init__(parent)
        self.ctx = ctx
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(16)

        card = Card("In-game menu")
        card.add(label(
            "ModMaster installs a small companion mod into Kingdom Come: Deliverance II. It adds an in-game "
            "menu (F5) to spawn props, give items to Henry, and switch on freecam, noclip (F4) and god mode. "
            "It only adds its own files to the Mods folder and never changes the game's files.", "Dim", wrap=True))

        grid = QGridLayout()
        grid.setHorizontalSpacing(18)
        grid.setVerticalSpacing(8)
        grid.addWidget(label("Companion mod", "Muted"), 0, 0)
        self.pill_state = StatusPill()
        grid.addWidget(self.pill_state, 0, 1)
        self.lbl_version = label("", "Dim")
        grid.addWidget(self.lbl_version, 0, 2)
        grid.addWidget(label("Game", "Muted"), 1, 0)
        self.pill_game = StatusPill()
        grid.addWidget(self.pill_game, 1, 1)
        grid.addWidget(label("Registry", "Muted"), 2, 0)
        self.lbl_registry = label("", "Dim")
        grid.addWidget(self.lbl_registry, 2, 1, 1, 2)
        grid.setColumnStretch(2, 1)
        card.body.addLayout(grid)

        row = QHBoxLayout()
        row.setSpacing(8)
        self.btn_install = button("Install", "arrow-down-tray", "Primary")
        self.btn_install.clicked.connect(self._install)
        self.btn_more = button("More", "chevron-down")
        menu = QMenu(self)
        menu.addAction("Repair installation", lambda: self._run("Repair", lambda m: m.sync(repair=True)))
        menu.addAction("Restore previous version", lambda: self._run("Restore", lambda m: m.rollback()))
        menu.addSeparator()
        menu.addAction("Open Mods folder", self._open)
        self.btn_more.setMenu(menu)
        self.btn_uninstall = button("Uninstall", "trash", "Danger")
        self.btn_uninstall.clicked.connect(self._uninstall)
        self.btn_launch = button("Launch KCD2", "play")
        self.btn_launch.clicked.connect(self._launch)
        for b in (self.btn_install, self.btn_more, self.btn_uninstall):
            row.addWidget(b)
        row.addStretch(1)
        row.addWidget(self.btn_launch)
        card.body.addLayout(row)
        card.add(label("Restart the game after installing or updating so it loads the new files.", "Muted"))
        lay.addWidget(card)
        lay.addStretch(1)
        ctx.settings_changed.connect(self.refresh)

    def manager(self) -> RuntimeManager:
        settings = self.ctx.settings
        if not settings.game_dir:
            raise ValueError("Set the Kingdom Come: Deliverance II folder first.")
        return RuntimeManager(Path(settings.game_dir), settings.workspace)

    def refresh(self) -> None:
        try:
            status = self.manager().status()
        except (ValueError, OSError) as exc:
            self.pill_state.set("Unavailable", "muted")
            self.lbl_version.setText(str(exc))
            self.lbl_registry.setText("—")
            self._enable(False)
            return
        text, tone, action = STATES.get(status.state, (status.state, "error", "Repair"))
        self.pill_state.set(text, tone)
        self.pill_state.setToolTip(status.details)
        self.btn_install.setText(action)
        installed = status.state != "Not installed"
        self.lbl_version.setText(f"Installed {status.version or '—'}  ·  bundled with this app {RUNTIME_VERSION}")
        self.lbl_registry.setText(status.registry if installed else "—")
        running = game_running()
        self.pill_game.set(running, "warn" if running == "Running" else "muted")
        self._enable(True)
        self.btn_uninstall.setEnabled(installed)

    def _enable(self, on: bool) -> None:
        for b in (self.btn_install, self.btn_more, self.btn_uninstall, self.btn_launch):
            b.setEnabled(on)

    def _install(self) -> None:
        repair = self.btn_install.text() == "Repair"
        self._run(self.btn_install.text(), lambda m: m.sync(repair=repair))

    def _run(self, title: str, action) -> None:
        if game_running() == "Running":
            QMessageBox.warning(self, title, "Close Kingdom Come: Deliverance II first.")
            return
        try:
            manager = self.manager()
        except ValueError as exc:
            QMessageBox.warning(self, title, str(exc))
            return
        self._enable(False)
        self.pill_state.set("Working…", "accent")
        def work(_ctx):
            try:
                return action(manager)
            except (OSError, ValueError) as exc:
                raise UserFacingError(str(exc)) from exc

        task = Task(title, work)

        def done(_result):
            self.refresh()
            QMessageBox.information(self, title, f"{title} finished. Restart the game to load the changes.")

        def failed(message):
            self.refresh()
            QMessageBox.warning(self, title, message)

        task.signals.finished.connect(done)
        task.signals.failed.connect(failed)
        self.ctx.tasks.start(task)

    def _uninstall(self) -> None:
        answer = QMessageBox.question(self, "Uninstall in-game menu",
                                      "Remove the ModMaster companion mod from the game's Mods folder?")
        if answer == QMessageBox.Yes:
            self._run("Uninstall", lambda m: m.uninstall())

    def _open(self) -> None:
        try:
            path = self.manager().mods
        except ValueError as exc:
            QMessageBox.warning(self, "Mods folder", str(exc))
            return
        path.mkdir(parents=True, exist_ok=True)
        reveal_in_explorer(path)

    def _launch(self) -> None:
        try:
            exe = self.manager().game / GAME_EXE_REL
            if not exe.is_file():
                raise ValueError(f"Game executable not found: {exe}")
            os.startfile(STEAM_RUN)
        except (OSError, ValueError) as exc:
            QMessageBox.warning(self, "Launch KCD2", str(exc))
