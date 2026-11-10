#!/usr/bin/env python3
"""Точка входа демона. Запускается через pkexec, живёт до SIGTERM.

Сокет и владельца GUI передаёт аргументами: pkexec вычищает окружение
(XDG_RUNTIME_DIR теряется), поэтому путь нельзя вычислять независимо с двух
сторон — иначе GUI ищет сокет в одном месте, а демон создаёт в другом.
Владелец нужен, чтобы сокет 0600 принадлежал пользователю, а не root.
"""

from __future__ import annotations

import argparse
import os
import signal
import sys
import threading
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
for candidate in (HERE, HERE.parent):
    if str(candidate) not in sys.path:
        sys.path.insert(0, str(candidate))

from core.base import atomic_write_json, read_json, state_dir  # noqa: E402
from daemon import rpc  # noqa: E402
from daemon.session import PENDING_FILE, Session  # noqa: E402


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(prog="wifikit-daemon", description="привилегированное ядро wifikit")
    parser.add_argument("--socket", help="путь к unix-сокету (по умолчанию вычисляется)")
    parser.add_argument("--owner", type=int, help="uid пользователя GUI: станет владельцем сокета")
    parser.add_argument("--group", type=int, help="gid пользователя GUI")
    parser.add_argument("--check", action="store_true",
                        help="только проверить окружение демона и выйти (для диагностики)")
    return parser.parse_args(argv)


def self_check() -> int:
    """Быстрая проверка: импорты, права, каталог сокета. Вызывается как `--check`."""
    problems = []
    print(f"python: {sys.version.split()[0]} ({sys.executable})")
    print(f"uid: {os.geteuid()}, cwd: {os.getcwd()}")
    try:
        import core.base, core.scan, core.mask, core.crack, core.ap, core.portal  # noqa: F401
        import daemon.rpc, daemon.session  # noqa: F401
        print("модули: ok")
    except Exception as exc:  # noqa: BLE001
        problems.append(f"импорт: {exc}")
    try:
        d = state_dir()
        print(f"state dir: {d} (запись: {'да' if os.access(d, os.W_OK) else 'нет'})")
    except Exception as exc:  # noqa: BLE001
        problems.append(f"state dir: {exc}")
    for binary in ("iw", "ip", "nmcli", "hcxdumptool", "hcxpcapngtool", "hostapd", "dnsmasq", "nft", "hashcat"):
        from core.base import which

        path = which(binary)
        if not path:
            problems.append(f"нет {binary}")
    print(f"инструменты: {'ok' if not problems else 'проблемы'}")
    for p in problems:
        print(f"  !! {p}")
    return 0 if not problems else 2


def main(argv: list[str] | None = None) -> int:
    # pkexec запускает без локали: без UTF-8 русский вывод падал бы на ASCII-терминале
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[union-attr]
        except AttributeError:
            pass
    args = parse_args(argv)
    if args.check:
        return self_check()
    if os.geteuid() != 0 and os.environ.get("WIFIKIT_ALLOW_NONROOT") != "1":
        print("демону нужен root: запускайте через pkexec", file=sys.stderr)
        return 1

    state = state_dir()
    lock_fd = os.open(state / "daemon.lock", os.O_CREAT | os.O_RDWR, 0o600)
    try:
        import fcntl

        fcntl.flock(lock_fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        print("демон уже запущен", file=sys.stderr)
        return 0

    socket_file = Path(args.socket) if args.socket else rpc.socket_path()
    owner = args.owner if args.owner is not None else os.geteuid()
    group = args.group if args.group is not None else (args.owner if args.owner is not None else os.getegid())

    session = Session()
    router = rpc.Router(session)
    stop_event = threading.Event()

    def _stop(signum, frame) -> None:  # noqa: ARG001
        stop_event.set()

    for sig in (signal.SIGTERM, signal.SIGINT, signal.SIGHUP):
        signal.signal(sig, _stop)

    pending = read_json(state / PENDING_FILE)
    atomic_write_json(state / PENDING_FILE, {"at": time.time(), "reason": "running"})
    if pending and pending.get("reason") in ("running", "shutdown"):
        try:
            cleaned = session.recover_stale()
            if cleaned["actions"]:
                print("уборка после прошлого запуска: " + "; ".join(cleaned["actions"]), flush=True)
        except Exception as exc:  # noqa: BLE001
            print(f"уборка не удалась: {exc}", file=sys.stderr, flush=True)

    try:
        socket_file.parent.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        print(f"нет доступа к каталогу сокета {socket_file.parent}: {exc}", file=sys.stderr)
        return 1

    print(f"wifikit daemon up (pid {os.getpid()}), socket {socket_file}, owner {owner}", flush=True)

    try:
        rpc.serve(socket_file, router, stop_event, owner=owner, group=group)
    finally:
        try:
            session.shutdown()
        finally:
            atomic_write_json(state / PENDING_FILE, {"at": 0, "reason": "clean"})
            os.close(lock_fd)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
