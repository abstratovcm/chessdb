"""One daemon thread per engine process; tasks are callables with state."""

from __future__ import annotations

import queue
import threading
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

_STOP = object()


@dataclass(frozen=True)
class TaskOutcome:
    task: Any
    result: Any = None
    error: BaseException | None = None


class WorkerPool:
    def __init__(self, engine_factory: Callable[[], Any], workers: int) -> None:
        self._engine_factory = engine_factory
        self._in_q: queue.Queue = queue.Queue()
        self._out_q: queue.Queue = queue.Queue()
        self._lock = threading.Lock()
        self._live_workers = workers
        self._threads = [
            threading.Thread(target=self._worker_loop, daemon=True)
            for _ in range(workers)
        ]
        for thread in self._threads:
            thread.start()

    @property
    def live_workers(self) -> int:
        with self._lock:
            return self._live_workers

    def _mark_dead(self) -> None:
        with self._lock:
            self._live_workers -= 1

    def _worker_loop(self) -> None:
        try:
            engine = self._engine_factory()
        except Exception as exc:  # noqa: BLE001 (reported to the orchestrator)
            self._out_q.put(TaskOutcome(task=None, error=exc))
            self._mark_dead()
            return
        try:
            while True:
                task = self._in_q.get()
                if task is _STOP:
                    return
                try:
                    result = task.run(engine)
                except Exception as exc:  # noqa: BLE001 (reported to the orchestrator)
                    self._out_q.put(TaskOutcome(task, error=exc))
                else:
                    self._out_q.put(TaskOutcome(task, result=result))
        finally:
            try:
                engine.quit()
            finally:
                self._mark_dead()

    def submit(self, task: Any) -> None:
        self._in_q.put(task)

    def next_result(self, timeout: float | None = None) -> TaskOutcome | None:
        try:
            return self._out_q.get(timeout=timeout)
        except queue.Empty:
            return None

    def results(self):
        while True:
            try:
                yield self._out_q.get_nowait()
            except queue.Empty:
                return

    def close(self) -> None:
        for _ in self._threads:
            self._in_q.put(_STOP)
        for thread in self._threads:
            thread.join()
