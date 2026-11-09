"""Общие примитивы: пути, ошибки, запуск процессов, реестр отката."""

from __future__ import annotations

import json
import os
import shlex
import signal
import subprocess
import tempfile
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Iterable, Sequence

APP_NAME = "wifikit"
STATE_DIR = Path(os.environ.get("WIFIKIT_STATE_DIR") or Path.home() / ".local" / "state" / APP_NAME)
PROJECTS_DIR = Path(os.environ.get("WIFIKIT_PROJECTS_DIR") or Path.home() / "wifikit-projects")
BIN_DIR = Path(os.environ.get("WIFIKIT_BIN_DIR") or "/usr/bin")

# Минимальные версии: старый hcxdumptool 6.x имеет другой CLI.
MIN_VERSIONS = {"hcxdumptool": (7, 0, 0), "hcxpcapngtool": (6, 3, 0), "hashcat": (6, 2, 6)}


class WilfiError(Exception):
    """Ошибка с кодом, который UI показывает как есть."""

    def __init__(self, message: str, code: str = "error", detail: str = ""):
        super().__init__(message)
        self.code = code
        self.detail = detail

    def as_dict(self) -> dict:
        return {"code": self.code, "message": str(self), "detail": self.detail}


class NotSupported(WilfiError):
    def __init__(self, message: str, detail: str = ""):
        super().__init__(message, code="not_supported", detail=detail)


class MissingDependency(WilfiError):
    def __init__(self, binary: str, detail: str = ""):
        super().__init__(f"не найден {binary}", code="missing_dep", detail=detail)


@dataclass
class CommandResult:
    argv: Sequence[str]
    code: int
    out: str = ""
    err: str = ""

    @property
    def ok(self) -> bool:
        return self.code == 0


def which(binary: str) -> str | None:
    for base in ("/usr/sbin", "/usr/bin", "/sbin", "/bin", "/usr/local/bin"):
        p = Path(base) / binary
        if p.is_file() and os.access(p, os.X_OK):
            return str(p)
    from shutil import which as _w

    return _w(binary)


def require(binary: str) -> str:
    path = which(binary)
    if not path:
        raise MissingDependency(binary, detail="установите пакет из мастера зависимостей")
    return path


def run(argv: Sequence[str], timeout: float = 30.0, check: bool = False) -> CommandResult:
    """Короткая синхронная команда. Долгие процессы — через jobs.Job."""
    argv = [str(a) for a in argv]
    try:
        p = subprocess.run(
            argv,
            capture_output=True,
            text=True,
            errors="replace",
            timeout=timeout,
            start_new_session=True,
        )
        res = CommandResult(argv, p.returncode, p.stdout, p.stderr)
    except subprocess.TimeoutExpired as exc:
        out = (exc.stdout or b"")
        err = (exc.stderr or b"")
        if isinstance(out, bytes):
            out = out.decode(errors="replace")
        if isinstance(err, bytes):
            err = err.decode(errors="replace")
        res = CommandResult(argv, 124, out, err or "timeout")
    except FileNotFoundError:
        raise MissingDependency(argv[0])
    if check and not res.ok:
        raise WilfiError(
            f"{argv[0]} завершился с кодом {res.code}",
            detail=(res.err or res.out).strip()[:2000],
        )
    return res


def ensure_dir(path: Path) -> Path:
    path.mkdir(parents=True, exist_ok=True)
    return path


def state_dir() -> Path:
    d = ensure_dir(STATE_DIR)
    os.chmod(d, 0o700)
    return d


def atomic_write_json(path: Path, data: dict) -> None:
    ensure_dir(path.parent)
    fd, tmp = tempfile.mkstemp(dir=str(path.parent), prefix=".tmp-")
    try:
        with os.fdopen(fd, "w") as fh:
            json.dump(data, fh, ensure_ascii=False, indent=2)
            fh.flush()
            os.fsync(fh.fileno())
        os.chmod(tmp, 0o600)
        os.replace(tmp, path)
    finally:
        if os.path.exists(tmp):
            os.unlink(tmp)


def read_json(path: Path, default=None):
    try:
        with open(path) as fh:
            return json.load(fh)
    except (OSError, ValueError):
        return default


# --------------------------------------------------------------------------- rollback


class ResourceSet:
    """Стек действий отката. Действия выполняются в обратном порядке, ошибки собираются."""

    def __init__(self, owner: str):
        self.owner = owner
        self._stack: list[tuple[str, Callable[[], object]]] = []
        self._done = False
        self._lock = threading.Lock()

    def add(self, label: str, action: Callable[[], object]) -> None:
        with self._lock:
            if self._done:
                raise WilfiError("ресурсы уже освобождены")
            self._stack.append((label, action))

    def add_command(self, label: str, argv: Iterable[str], ignore_errors: bool = True) -> None:
        argv = [str(a) for a in argv]

        def _run() -> None:
            res = run(argv, timeout=20)
            if not res.ok and not ignore_errors:
                raise WilfiError(f"откат «{label}» не удался", detail=res.err.strip()[:500])

        self.add(label, _run)

    def rollback(self) -> list[str]:
        with self._lock:
            if self._done:
                return []
            self._done = True
            stack = list(reversed(self._stack))
            self._stack.clear()
        problems: list[str] = []
        for label, action in stack:
            try:
                action()
            except Exception as exc:  # откат не должен прерываться
                problems.append(f"{label}: {exc}")
        return problems

    @property
    def size(self) -> int:
        return len(self._stack)


def shell_join(argv: Sequence[str]) -> str:
    return " ".join(shlex.quote(str(a)) for a in argv)


def wait_until(predicate: Callable[[], bool], timeout: float, interval: float = 0.2) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return True
        time.sleep(interval)
    return predicate()


def kill_group(pid: int, sig: int = signal.SIGTERM) -> None:
    try:
        os.killpg(os.getpgid(pid), sig)
    except ProcessLookupError:
        pass
    except PermissionError:
        try:
            os.kill(pid, sig)
        except ProcessLookupError:
            pass
