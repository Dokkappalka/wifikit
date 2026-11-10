"""Связь с демоном: запуск через pkexec, запросы в фоновых потоках.

Демон поднимается с явными `--socket` и `--owner`: pkexec вычищает окружение,
и вычислять путь сокета независимо с двух сторон нельзя — раньше GUI ждал сокет
в /run/user/1000, а демон создавал его в /tmp и от root, поэтому «нет связи».
"""

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
INSTALLED_DAEMON = Path("/usr/lib/wifikit/daemon.py")


def log_path() -> Path:
    base = Path(os.environ.get("XDG_STATE_HOME") or Path.home() / ".local" / "state")
    path = base / "wifikit" / "daemon.log"
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
    except OSError:
        return Path("/tmp/wifikit-daemon.log")
    return path


class Remote(QObject):
    log = Signal(str)
    failed = Signal(str, str)

    def __init__(self) -> None:
        super().__init__()
        self._client: Client | None = None
        self._lock = threading.Lock()
        self.socket_file = socket_path()

    # ------------------------------------------------------------ connection
    def is_connected(self) -> bool:
        return self._client is not None

    def daemon_log_tail(self, lines: int = 12) -> str:
        path = log_path()
        try:
            text = path.read_text(errors="replace").splitlines()
        except OSError:
            return ""
        return "\n".join(text[-lines:])

    def open_link(self, timeout: float = 90.0) -> None:
        """Запустить демон (если нужно) и дождаться сокета.

        Имя намеренно не `connect`: метод с таким именем на QObject перекрывает
        старый Qt-стиль `QObject.connect(sender, signal, receiver, slot)` и ломает
        подключение сигналов на части сборок PySide6.
        """
        if self._client:
            return
        if os.environ.get("WIFIKIT_NO_DAEMON") == "1":
            self.log.emit("режим без демона (WIFIKIT_NO_DAEMON=1) — запросы будут падать")
            return
        try:
            self.socket_file.parent.mkdir(parents=True, exist_ok=True)
        except OSError:
            pass
        self._spawn_daemon()
        deadline = time.monotonic() + timeout
        last = ""
        while time.monotonic() < deadline:
            try:
                client = Client(path=self.socket_file, timeout=300)
                client.call("ping")
                with self._lock:
                    self._client = client
                self._try_recover()
                self.log.emit(f"демон подключён ({self.socket_file})")
                return
            except PermissionError as exc:
                last = f"нет прав на сокет {self.socket_file}: {exc}"
                time.sleep(0.7)
            except ConnectionRefusedError:
                # сокет есть, но слушателя нет: остаток от прошлого запуска
                last = "сокет есть, но демон не слушает"
                try:
                    if self.socket_file.stat().st_uid == os.getuid():
                        self.socket_file.unlink()
                except OSError:
                    pass
                time.sleep(0.5)
                self._spawn_daemon()
            except (OSError, ConnectionError, WilfiError) as exc:
                last = str(exc)
                time.sleep(0.7)
        tail = self.daemon_log_tail()
        manual = " ".join(self._daemon_argv())
        self.failed.emit(
            "демон не поднялся",
            (last or "нет ответа")
            + (f"\n\nлог демона ({log_path()}):\n{tail}" if tail
               else "\n\nлог пуст: pkexec, вероятно, не спросил пароль")
            + "\n\nЗапустить демон вручную в отдельном терминале:\n  sudo " + manual,
        )

    def _daemon_argv(self) -> list[str]:
        script = INSTALLED_DAEMON if INSTALLED_DAEMON.is_file() else ROOT / "daemon" / "main.py"
        return [self._interpreter(), "-X", "utf8", str(script)] + self._daemon_args()

    def _daemon_args(self) -> list[str]:
        return ["--socket", str(self.socket_file),
                "--owner", str(os.getuid()), "--group", str(os.getgid())]

    @staticmethod
    def _interpreter() -> str:
        """Системный python3: демону PySide6 не нужен, хватает штатного 3.10+."""
        for candidate in ("/usr/bin/python3", "/usr/local/bin/python3"):
            if Path(candidate).is_file():
                return candidate
        return sys.executable

    def _spawn_daemon(self) -> None:
        # Всегда запускаем интерпретатором, а не файлом: pkexec делает execve по пути,
        # и любая мелочь в первой строке (нет shebang, BOM, CRLF) даёт «Exec format error».
        script = INSTALLED_DAEMON if INSTALLED_DAEMON.is_file() else ROOT / "daemon" / "main.py"
        argv = ["pkexec", self._interpreter(), "-X", "utf8", str(script), *self._daemon_args()]
        self.log.emit("$ " + " ".join(argv))
        try:
            out = open(log_path(), "ab", buffering=0)
        except OSError:
            out = subprocess.DEVNULL  # type: ignore[assignment]
        try:
            subprocess.Popen(argv, start_new_session=True, stdout=out, stderr=subprocess.STDOUT,
                             stdin=subprocess.DEVNULL)
        except FileNotFoundError:
            self.failed.emit("нет pkexec", "установите polkit: sudo apt install policykit-1 (или pkexec)")
        finally:
            if hasattr(out, "close") and out is not subprocess.DEVNULL:
                out.close()  # type: ignore[union-attr]

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
            raise WilfiError(
                "нет связи с демоном",
                code="offline",
                detail="демон не запущен или не пустил к сокету. Закройте и откройте приложение; "
                       "если не помогло — пришлите файл " + str(log_path()),
            )
        try:
            return client.call(method, **params)
        except (ConnectionError, OSError) as exc:
            with self._lock:
                self._client = None
            raise WilfiError("связь с демоном потеряна", code="offline",
                             detail=f"{exc}\nлог: {log_path()}") from exc

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