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
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
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