"""Связь с демоном: запуск через pkexec, запросы в фоновых потоках."""

from __future__ import annotations

import os
import subprocess
import sys
import threading
import time
from pathlib import Path

from PySide6.QtCore import QObject, Signal

from core.base import WilfiError
from daemon.rpc import Client, socket_path

ROOT = Path(__file__).resolve().parent.parent


class Remote(QObject):
    log = Signal(str)
    failed = Signal(str, str)

    def __init__(self) -> None:
        super().__init__()
        self._client: Client | None = None
        self._lock = threading.Lock()

    # ------------------------------------------------------------ connection
    def connected(self) -> bool:
        return self._client is not None

    def connect(self, timeout: float = 90.0) -> None:
        if self._client:
            return
        deadline = time.monotonic() + timeout
        if not socket_path().exists():
            self._spawn_daemon()
        last = ""
        while time.monotonic() < deadline:
            try:
                client = Client(timeout=300)
                with self._lock:
                    self._client = client
                client.call("ping")
                self._try_recover()
                self.log.emit("демон подключён")
                return
            except (OSError, ConnectionError, WilfiError) as exc:
                last = str(exc)
                time.sleep(0.7)
        self.failed.emit("демон не отвечает", last or "проверьте pkexec и polkit-агент")

    def _spawn_daemon(self) -> None:
        sock = socket_path()
        try:
            Path(sock).parent.mkdir(parents=True, exist_ok=True)
        except OSError:
            pass
        installed = Path("/usr/lib/wifikit/daemon.py")
        if installed.is_file():
            argv = ["pkexec", str(installed)]
        else:
            argv = ["pkexec", sys.executable, str(ROOT / "daemon" / "main.py")]
        self.log.emit("$ " + " ".join(argv))
        try:
            subprocess.Popen(argv, start_new_session=True,
                             stdout=subprocess.DEVNULL, stderr=subprocess.STDOUT)
        except FileNotFoundError:
            self.failed.emit("нет pkexec", "установите пакет polkit (Ubuntu: policykit-1)")

    def _try_recover(self) -> None:
        try:
            res = self.call("recover_stale")
            if res.get("actions"):
                self.log.emit("уборка: " + "; ".join(res["actions"]))
        except (WilfiError, ConnectionError, OSError):
            pass

    # ---------------------------------------------------------------- calls
    def call(self, method: str, **params):
        with self._lock:
            client = self._client
        if not client:
            raise WilfiError("нет связи с демоном", code="offline")
        return client.call(method, **params)

    def shutdown(self) -> None:
        try:
            self.call("shutdown")
        except Exception:  # noqa: BLE001
            pass
        with self._lock:
            if self._client:
                self._client.close()
                self._client = None


class Task(QObject):
    """Один вызов демона в отдельном потоке. UI не блокируется.

    Пока задача жива, модуль держит на неё ссылку: QObject без родителя иначе
    удаляется сборщиком раньше, чем поток успевает отдать сигнал (падение).
    """

    done = Signal(object)
    failed = Signal(str, str)
    _running: set["Task"] = set()

    def __init__(self, remote: Remote, method: str, **params):
        super().__init__()
        self.remote = remote
        self.method = method
        self.params = params

    def start(self) -> "Task":
        Task._running.add(self)
        threading.Thread(target=self._run, daemon=True).start()
        return self

    def _run(self) -> None:
        try:
            self.done.emit(self.remote.call(self.method, **self.params))
        except WilfiError as exc:
            self.failed.emit(str(exc), exc.detail or exc.code)
        except Exception as exc:  # noqa: BLE001
            self.failed.emit("вызов не прошёл", str(exc))
        finally:
            Task._running.discard(self)
