"""Run printer operations off the UI thread, one at a time."""
from __future__ import annotations

import traceback
from typing import Callable, Optional

from PySide6.QtCore import QObject, QThread, Signal, Slot


class Job(QObject):
    finished = Signal(object)      # result
    failed = Signal(str, str)      # message, traceback
    progress = Signal(int, int)

    def __init__(self, fn: Callable, *args, **kwargs):
        super().__init__()
        self._fn, self._args, self._kwargs = fn, args, kwargs

    @Slot()
    def run(self) -> None:
        try:
            code = getattr(self._fn, "__code__", None)
            if code is not None and "progress" in code.co_varnames[: code.co_argcount + code.co_kwonlyargcount]:
                self._kwargs.setdefault("progress", lambda i, n: self.progress.emit(i, n))
            result = self._fn(*self._args, **self._kwargs)
        except Exception as exc:  # noqa: BLE001
            self.failed.emit(f"{type(exc).__name__}: {exc}", traceback.format_exc())
            return
        self.finished.emit(result)


class Runner(QObject):
    """Serialises jobs on a single worker thread (the printer link is not
    thread-safe: the D4 channel must see one request at a time).

    Callbacks always run on the GUI thread: the job's signals are connected to
    slots of this object, which lives on the GUI thread, so Qt queues them."""

    busy_changed = Signal(bool)

    def __init__(self, parent: Optional[QObject] = None):
        super().__init__(parent)
        self._thread: Optional[QThread] = None
        self._job: Optional[Job] = None
        self._cbs: tuple = ()
        self._queue: list[tuple] = []

    @property
    def busy(self) -> bool:
        return self._thread is not None

    def submit(self, fn: Callable, *args, on_done: Callable = None, on_error: Callable = None,
               on_progress: Callable = None, **kwargs) -> None:
        self._queue.append((Job(fn, *args, **kwargs), on_done or (lambda r: None),
                            on_error or (lambda m, t: None), on_progress or (lambda i, n: None)))
        self._pump()

    def _pump(self) -> None:
        if self._thread is not None or not self._queue:
            return
        job, on_done, on_error, on_progress = self._queue.pop(0)
        thread = QThread()
        job.moveToThread(thread)
        thread.started.connect(job.run)
        job.progress.connect(self._on_progress)
        job.finished.connect(self._on_done)
        job.failed.connect(self._on_failed)
        self._thread, self._job, self._cbs = thread, job, (on_done, on_error, on_progress)
        self.busy_changed.emit(True)
        thread.start()

    def _finish(self) -> None:
        if self._thread is not None:
            self._thread.quit()
            self._thread.wait()
        self._thread, self._job, self._cbs = None, None, ()
        self.busy_changed.emit(False)
        self._pump()

    @Slot(int, int)
    def _on_progress(self, i: int, n: int) -> None:
        if self._cbs:
            self._cbs[2](i, n)

    @Slot(object)
    def _on_done(self, result) -> None:
        cb = self._cbs[0] if self._cbs else None
        self._finish()
        if cb:
            cb(result)

    @Slot(str, str)
    def _on_failed(self, msg: str, tb: str) -> None:
        cb = self._cbs[1] if self._cbs else None
        self._finish()
        if cb:
            cb(msg, tb)
