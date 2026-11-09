"""Долгоживущие дочерние процессы и реестр заданий."""

from __future__ import annotations

import collections
import itertools
import os
import subprocess
import threading
import time
from typing import Callable, Sequence

from .base import WilfiError, kill_group

MAX_LINES = 4000


class Job:
    """Процесс с кольцевым буфером вывода, состоянием и колбэками.

    Он же — единица наблюдения для UI: клиент подписывается на job_id и тянет
    новые строки по курсору. Никакого shell: argv собирается списком.
    """

    _ids = itertools.count(1)

    def __init__(self, kind: str, argv: Sequence[str], title: str = ""):
        self.id = f"{kind}-{next(self._ids)}"
        self.kind = kind
        self.argv = [str(a) for a in argv]
        self.title = title or kind
        self.state = "starting"  # starting|running|stopping|done|failed|cancelled
        self.exit_code: int | None = None
        self.error: str | None = None
        self.started_at = time.time()
        self.ended_at: float | None = None
        self.on_exit: list[Callable[["Job"], None]] = []
        self._lines: collections.deque[tuple[int, str]] = collections.deque(maxlen=MAX_LINES)
        self._seq = 0
        self._lock = threading.Lock()
        self._proc: subprocess.Popen | None = None
        self._cancel_requested = False

    # -- чтение для UI -----------------------------------------------------
    def drain(self, cursor: int = 0) -> list[tuple[int, str]]:
        with self._lock:
            return [(n, s) for n, s in self._lines if n > cursor]

    @property
    def cursor(self) -> int:
        with self._lock:
            return self._seq

    def tail(self, n: int = 200) -> str:
        with self._lock:
            return "\n".join(s for _, s in list(self._lines)[-n:])

    def status(self) -> dict:
        return {
            "id": self.id,
            "kind": self.kind,
            "title": self.title,
            "state": self.state,
            "argv": self.argv,
            "exit_code": self.exit_code,
            "error": self.error,
            "started_at": self.started_at,
            "ended_at": self.ended_at,
            "cursor": self.cursor,
        }

    # -- запись ------------------------------------------------------------
    def _emit(self, line: str) -> None:
        with self._lock:
            self._seq += 1
            self._lines.append((self._seq, line.rstrip("\n")))

    def request_stop(self, sig: int = 15) -> None:
        self._cancel_requested = True
        if self.state in ("starting", "running"):
            self.state = "stopping"
        proc = self._proc
        if proc and proc.poll() is None:
            kill_group(proc.pid, sig)

    # -- запуск ------------------------------------------------------------
    def start(self) -> "Job":
        try:
            self._proc = subprocess.Popen(
                self.argv,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                errors="replace",
                bufsize=1,
                start_new_session=True,
                env={**os.environ, "LC_ALL": "C.UTF-8", "TERM": "dumb"},
            )
        except FileNotFoundError:
            self.state = "failed"
            self.error = f"нет исполняемого файла: {self.argv[0]}"
            self.ended_at = time.time()
            self._finish()
            return self
        self.state = "running"
        self._emit(f"$ {' '.join(self.argv)}")
        threading.Thread(target=self._pump, daemon=True).start()
        return self

    def _pump(self) -> None:
        proc = self._proc
        assert proc and proc.stdout
        for line in proc.stdout:
            self._emit(line)
        code = proc.wait()
        self.exit_code = code
        self.ended_at = time.time()
        if self._cancel_requested:
            self.state = "cancelled"
        elif code == 0:
            self.state = "done"
        else:
            self.state = "failed"
            self.error = f"код выхода {code}"
        self._finish()

    def _finish(self) -> None:
        for cb in list(self.on_exit):
            try:
                cb(self)
            except Exception as exc:  # колбэк не должен ронять пампер
                self._emit(f"[callback error] {exc}")


class JobRegistry:
    def __init__(self) -> None:
        self._jobs: dict[str, Job] = {}
        self._lock = threading.Lock()

    def add(self, job: Job) -> Job:
        with self._lock:
            self._jobs[job.id] = job
        job.start()
        return job

    def get(self, job_id: str) -> Job:
        with self._lock:
            job = self._jobs.get(job_id)
        if not job:
            raise WilfiError(f"нет задания {job_id}", code="no_job")
        return job

    def of_kind(self, kind: str) -> list[Job]:
        with self._lock:
            return [j for j in self._jobs.values() if j.kind == kind]

    def running(self, kind: str | None = None) -> list[Job]:
        return [j for j in self.of_kind(kind) if j.state in ("starting", "running", "stopping")] if kind else [
            j for j in self._jobs.values() if j.state in ("starting", "running", "stopping")
        ]

    def stop_all(self) -> None:
        for job in list(self._jobs.values()):
            if job.state in ("starting", "running", "stopping"):
                job.request_stop()
        deadline = time.monotonic() + 8
        while time.monotonic() < deadline and any(
            j.state in ("starting", "running", "stopping") and j._proc and j._proc.poll() is None
            for j in self._jobs.values()
        ):
            time.sleep(0.1)
        for job in list(self._jobs.values()):
            if job._proc and job._proc.poll() is None:
                job.request_stop(9)

    def prune(self, keep_done_seconds: float = 900) -> None:
        now = time.time()
        with self._lock:
            for jid, job in list(self._jobs.items()):
                if job.ended_at and now - job.ended_at > keep_done_seconds:
                    self._jobs.pop(jid, None)
