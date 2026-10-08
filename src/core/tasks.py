"""Background task infrastructure so long operations never block the UI."""
from __future__ import annotations

import logging
import threading
import traceback
from typing import Any, Callable

from PySide6.QtCore import QObject, QRunnable, QThreadPool, Signal

log = logging.getLogger(__name__)


class TaskCancelled(Exception):
    pass


class UserFacingError(Exception):
    """Error whose message is already readable for an artist."""


class TaskSignals(QObject):
    progress = Signal(int, int, str)   # current, total, message
    finished = Signal(object)          # result
    failed = Signal(str)               # readable message
    done = Signal()


class TaskContext:
    def __init__(self, signals: TaskSignals):
        self._signals = signals
        self._cancel = threading.Event()

    def progress(self, current: int, total: int, message: str = "") -> None:
        if self._cancel.is_set():
            raise TaskCancelled()
        self._signals.progress.emit(current, total, message)

    def cancel(self) -> None:
        self._cancel.set()

    @property
    def cancelled(self) -> bool:
        return self._cancel.is_set()


class Task(QRunnable):
    def __init__(self, name: str, fn: Callable[..., Any], *args, **kwargs):
        super().__init__()
        self.name = name
        self.fn = fn
        self.args = args
        self.kwargs = kwargs
        self.signals = TaskSignals()
        self.ctx = TaskContext(self.signals)
        self.setAutoDelete(False)

    def run(self) -> None:  # executed in worker thread
        try:
            result = self.fn(self.ctx, *self.args, **self.kwargs)
            self.signals.finished.emit(result)
        except TaskCancelled:
            self.signals.failed.emit(f"{self.name} was cancelled.")
        except UserFacingError as e:
            self.signals.failed.emit(str(e))
        except Exception as e:  # noqa: BLE001
            log.debug(traceback.format_exc())
            self.signals.failed.emit(f"{self.name} failed unexpectedly: {e}")
        finally:
            self.signals.done.emit()


class TaskManager(QObject):
    """Owns the thread pool and keeps running tasks alive."""

    busy_changed = Signal(bool)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.pool = QThreadPool.globalInstance()
        self._running: list[Task] = []

    def start(self, task: Task) -> Task:
        self._running.append(task)
        task.signals.done.connect(lambda t=task: self._on_done(t))
        self.busy_changed.emit(True)
        self.pool.start(task)
        return task

    def _on_done(self, task: Task) -> None:
        if task in self._running:
            self._running.remove(task)
        self.busy_changed.emit(bool(self._running))

    def is_running(self, name: str) -> bool:
        return any(t.name == name for t in self._running)

    def cancel_all(self) -> None:
        for t in self._running:
            t.ctx.cancel()

    def wait(self, ms: int = 3000) -> None:
        self.pool.waitForDone(ms)
