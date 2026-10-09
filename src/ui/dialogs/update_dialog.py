"""Offers a newer release, downloads its installer and hands over to it."""
from __future__ import annotations

from PySide6.QtWidgets import (
    QApplication,
    QDialog,
    QHBoxLayout,
    QMessageBox,
    QProgressBar,
    QTextBrowser,
    QVBoxLayout,
)

from app import updater
from app.version import display_version
from core.tasks import Task
from ui.widgets import StatusPill, button, label


class UpdateDialog(QDialog):
    def __init__(self, ctx, release: updater.Release, parent=None):
        super().__init__(parent)
        self.ctx = ctx
        self.release = release
        self.task = None
        self.setWindowTitle("Update available")
        self.setModal(True)
        self.resize(640, 520)

        lay = QVBoxLayout(self)
        lay.setContentsMargins(24, 22, 24, 20)
        lay.setSpacing(12)
        lay.addWidget(label(f"ModMaster {release.version} is available", "H1"))
        meta = QHBoxLayout()
        meta.addWidget(StatusPill(f"You have {display_version()}", "muted"))
        if release.prerelease:
            meta.addWidget(StatusPill("Beta", "accent"))
        meta.addStretch(1)
        lay.addLayout(meta)

        notes = QTextBrowser()
        notes.setOpenExternalLinks(True)
        notes.setMarkdown(release.notes or "No release notes.")
        lay.addWidget(notes, 1)

        self.progress = QProgressBar()
        self.progress.setVisible(False)
        lay.addWidget(self.progress)
        self.lbl_status = label("Your workspace and mods are not affected by updating.", "Muted", wrap=True)
        lay.addWidget(self.lbl_status)

        row = QHBoxLayout()
        self.btn_skip = button("Skip this version", "", "Ghost")
        self.btn_skip.clicked.connect(self._skip)
        row.addWidget(self.btn_skip)
        row.addStretch(1)
        self.btn_later = button("Later")
        self.btn_later.clicked.connect(self.reject)
        row.addWidget(self.btn_later)
        self.btn_install = button("Download and install", "arrow-down-tray", "Primary")
        self.btn_install.clicked.connect(self._install)
        row.addWidget(self.btn_install)
        lay.addLayout(row)

    def _skip(self) -> None:
        self.ctx.settings.skipped_update = self.release.version
        self.ctx.settings.save()
        self.reject()

    def _install(self) -> None:
        self.btn_install.setEnabled(False)
        self.btn_skip.setEnabled(False)
        self.progress.setVisible(True)
        self.progress.setRange(0, 0)
        self.lbl_status.setText("Downloading…")

        def work(task_ctx):
            def progress(done, total):
                task_ctx.progress(done, max(total, 1), f"Downloading update… {done // 1048576} MB")
            return updater.download_installer(self.release, progress, lambda: task_ctx.cancelled)

        self.task = Task("Download update", work)
        self.task.signals.progress.connect(self._on_progress)
        self.task.signals.finished.connect(self._on_downloaded)
        self.task.signals.failed.connect(self._on_failed)
        self.btn_later.setText("Cancel")
        self.btn_later.clicked.disconnect()
        self.btn_later.clicked.connect(self._cancel)
        self.ctx.tasks.start(self.task)

    def _on_progress(self, done: int, total: int, message: str) -> None:
        self.progress.setRange(0, total)
        self.progress.setValue(done)
        self.lbl_status.setText(message)

    def _on_downloaded(self, path) -> None:
        self.lbl_status.setText("Starting the installer. ModMaster will close and reopen when it is done.")
        try:
            updater.launch_installer(path)
        except OSError as exc:
            self._on_failed(f"Could not start the installer: {exc}")
            return
        # Closing the windows runs their save handlers before the installer replaces the program files.
        app = QApplication.instance()
        app.closeAllWindows()
        app.quit()

    def _on_failed(self, message: str) -> None:
        self.progress.setVisible(False)
        self.lbl_status.setText(message)
        self.btn_install.setEnabled(True)
        self.btn_skip.setEnabled(True)
        QMessageBox.warning(self, "Update failed", message)

    def _cancel(self) -> None:
        if self.task:
            self.task.ctx.cancel()
        self.reject()
