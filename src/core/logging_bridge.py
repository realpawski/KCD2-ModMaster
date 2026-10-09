"""Bridges Python logging into the Qt operation console + a log file."""
from __future__ import annotations

import logging
import sys
from logging.handlers import RotatingFileHandler

from PySide6.QtCore import QObject, Signal

from core.config import app_data_dir


class LogEmitter(QObject):
    record = Signal(str, str)  # level name, message


class QtLogHandler(logging.Handler):
    def __init__(self):
        super().__init__(logging.INFO)
        self.emitter = LogEmitter()

    def emit(self, record: logging.LogRecord) -> None:
        try:
            self.emitter.record.emit(record.levelname, record.getMessage())
        except RuntimeError:
            pass  # emitter destroyed during shutdown


def setup_logging() -> QtLogHandler:
    root = logging.getLogger()
    root.setLevel(logging.DEBUG)
    logdir = app_data_dir() / "logs"
    logdir.mkdir(exist_ok=True)
    fh = RotatingFileHandler(logdir / "modmaster.log", maxBytes=2_000_000, backupCount=3, encoding="utf-8")
    fh.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s"))
    fh.setLevel(logging.DEBUG)
    root.addHandler(fh)
    qh = QtLogHandler()
    root.addHandler(qh)
    # Errors raised in button handlers otherwise vanish without a trace in the frozen app.
    sys.excepthook = _log_uncaught
    return qh


def _log_uncaught(exc_type, exc, tb) -> None:
    logging.getLogger("modmaster").error("Unexpected error: %s", exc, exc_info=(exc_type, exc, tb))
