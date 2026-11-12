"""Защита слотов Qt: исключение из слота не должно убивать процесс.

В PySide6 исключение, поднявшееся в слоте, вызванном из C++, раскручивает стек
через нативную часть и валит процесс SIGSEGV/SIGBUS. Поэтому каждый обработчик
ответа демона и каждое действие пользователя обёрнуты здесь: любые данные
проверяются, любые ошибки уходят в панель и в файл лога.
"""

from __future__ import annotations

import functools
import os
import sys
import threading
import traceback
from pathlib import Path
from typing import Callable


def gui_log_path() -> Path:
    base = Path(os.environ.get("XDG_STATE_HOME") or Path.home() / ".local" / "state")
    path = base / "wifikit" / "gui.log"
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
    except OSError:
        return Path("/tmp/wifikit-gui.log")
    return path


def log_exception(text: str) -> None:
    try:
        with open(gui_log_path(), "a", encoding="utf-8") as fh:
            fh.write(text.rstrip() + "\n")
    except OSError:
        pass
    try:
        sys.__stderr__.write(text)
        sys.__stderr__.flush()
    except Exception:  # noqa: BLE001
        pass


def report(owner, message: str, detail: str = "") -> None:
    """Показать ошибку так, как умеет owner: панель или обычный диалог."""
    notify = getattr(owner, "notify_error", None)
    if callable(notify):
        notify(message, detail)
        return
    show = getattr(owner, "show_error", None)
    if callable(show):
        show(message, detail)


def safe_slot(fn: Callable) -> Callable:
    """Декоратор для методов-слотов: ловит всё, включая BaseException."""

    @functools.wraps(fn)
    def wrapper(self, *args, **kwargs):
        try:
            return fn(self, *args, **kwargs)
        except Exception as exc:  # noqa: BLE001
            text = traceback.format_exc()
            log_exception(f"[slot {fn.__qualname__}] {text}")
            report(self, f"Внутренняя ошибка в {fn.__qualname__}: {exc}",
                   f"{exc!r}\n\n{text[-2500:]}")
            return None

    return wrapper


def safe_callback(owner, label: str, callback: Callable) -> Callable:
    """Обёртка для произвольного колбэка, отдаваемого в Qt-сигнал."""

    def wrapper(*args, **kwargs):
        try:
            return callback(*args, **kwargs)
        except Exception as exc:  # noqa: BLE001
            text = traceback.format_exc()
            log_exception(f"[callback {label}] {text}")
            report(owner, f"Внутренняя ошибка в {label}: {exc}",
                   f"{exc!r}\n\n{text[-2500:]}")
            return None

    return wrapper


def expect_dict(owner, label: str, data) -> dict | None:
    """Проверка формы ответа демона: лучше ошибка, чем KeyError в слоте."""
    if isinstance(data, dict):
        return data
    report(owner, f"{label}: неожиданный ответ демона", repr(data)[:1500])
    log_exception(f"[shape {label}] ожидался dict, пришло {type(data).__name__}: {data!r}"[:2000])
    return None


def install_hooks() -> None:
    """Логировать всё, что иначе уйдёт в пустоту (GUI и фоновые потоки)."""

    def excepthook(exc_type, exc, tb):
        text = "".join(traceback.format_exception(exc_type, exc, tb))
        log_exception(f"[uncaught] {text}")

    def thread_hook(args):
        text = "".join(traceback.format_exception(args.exc_type, args.exc_value, args.exc_traceback))
        log_exception(f"[thread {args.thread.name if args.thread else '?'}] {text}")

    sys.excepthook = excepthook
    threading.excepthook = thread_hook