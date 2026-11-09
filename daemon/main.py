"""Точка входа демона. Запускается через pkexec, живёт до SIGTERM."""

from __future__ import annotations

import os
import signal
import sys
import threading
from pathlib import Path

HERE = Path(__file__).resolve().parent
for candidate in (HERE, HERE.parent):
    if str(candidate) not in sys.path:
        sys.path.insert(0, str(candidate))

from core.base import atomic_write_json, read_json, state_dir  # noqa: E402
from daemon import rpc  # noqa: E402
from daemon.session import PENDING_FILE, Session  # noqa: E402

LOCK = state_dir() / "daemon.lock"


def main() -> int:
    if os.geteuid() != 0 and os.environ.get("WIFIKIT_ALLOW_NONROOT") != "1":
        print("демону нужен root: запускайте через pkexec", file=sys.stderr)
        return 1
    lock_fd = os.open(LOCK, os.O_CREAT | os.O_RDWR, 0o600)
    try:
        import fcntl

        fcntl.flock(lock_fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        print("демон уже запущен", file=sys.stderr)
        return 0

    session = Session()
    router = rpc.Router(session)
    stop_event = threading.Event()

    def _stop(signum, frame) -> None:  # noqa: ARG001
        stop_event.set()

    for sig in (signal.SIGTERM, signal.SIGINT, signal.SIGHUP):
        signal.signal(sig, _stop)

    pending = read_json(state_dir() / PENDING_FILE)
    atomic_write_json(state_dir() / PENDING_FILE, {"at": __import__("time").time(), "reason": "running"})
    if pending and pending.get("reason") in ("running", "shutdown"):
        try:
            cleaned = session.recover_stale()
            if cleaned["actions"]:
                print("уборка после прошлого запуска: " + "; ".join(cleaned["actions"]), flush=True)
        except Exception as exc:  # noqa: BLE001
            print(f"уборка не удалась: {exc}", file=sys.stderr, flush=True)
    print(f"wifikit daemon up (pid {os.getpid()}), socket {rpc.socket_path()}", flush=True)

    try:
        rpc.serve(rpc.socket_path(), router, stop_event)
    finally:
        try:
            session.shutdown()
        finally:
            atomic_write_json(state_dir() / PENDING_FILE, {"at": 0, "reason": "clean"})
            os.close(lock_fd)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
