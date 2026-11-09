"""JSON-RPC поверх unix-сокета.

Протокол построчный: `{"id":1,"method":"scan_start","params":{...}}` →
`{"id":1,"ok":true,"data":{...}}` или `{"id":1,"ok":false,"error":{...}}`.
Сокет доступен только владельцу (0600), посторонний процесс не подсунет команды.
"""

from __future__ import annotations

import json
import os
import socket
import socketserver
import threading
import traceback
from pathlib import Path
from typing import Any, Callable

from core.base import WilfiError

MAX_LINE = 1 << 20
MUTATING = {
    "ap_start", "ap_stop", "capture_start", "capture_stop", "deauth_start", "deauth_stop",
    "portal_start", "portal_stop", "crack_start", "crack_stop", "project_new", "project_open",
    "adapters_assign", "shutdown",
}


class Router:
    def __init__(self, session):
        self.session = session
        self.methods: dict[str, Callable[..., Any]] = {}
        for name in dir(session):
            if name.startswith("_"):
                continue
            attr = getattr(session, name)
            if callable(attr):
                self.methods[name] = attr

    def dispatch(self, request: dict) -> dict:
        rid = request.get("id")
        method = request.get("method", "")
        params = request.get("params") or {}
        handler = self.methods.get(method)
        if not handler:
            return _err(rid, {"code": "no_method", "message": f"нет метода {method}"})
        try:
            if not isinstance(params, dict):
                raise WilfiError("params должны быть объектом")
            if method in MUTATING:
                with self.session.lock:
                    data = handler(**_filter(handler, params))
            else:
                data = handler(**_filter(handler, params))
            return {"id": rid, "ok": True, "data": data}
        except WilfiError as exc:
            return _err(rid, exc.as_dict())
        except TypeError as exc:
            return _err(rid, {"code": "bad_params", "message": str(exc)})
        except Exception as exc:  # noqa: BLE001
            return _err(rid, {"code": "internal", "message": str(exc), "detail": traceback.format_exc()[-2000:]})


def _filter(handler: Callable, params: dict) -> dict:
    import inspect

    sig = inspect.signature(handler)
    allowed = set(sig.parameters)
    return {k: v for k, v in params.items() if k in allowed}


def _err(rid, error: dict) -> dict:
    return {"id": rid, "ok": False, "error": error}


class _Handler(socketserver.StreamRequestHandler):
    timeout = 300

    def handle(self) -> None:
        router: Router = self.server.router  # type: ignore[attr-defined]
        while True:
            line = self.rfile.readline(MAX_LINE)
            if not line:
                return
            try:
                request = json.loads(line)
            except ValueError:
                self._write(_err(None, {"code": "bad_json", "message": "не разобрал JSON"}))
                continue
            response = router.dispatch(request)
            self._write(response)

    def _write(self, payload: dict) -> None:
        try:
            self.wfile.write((json.dumps(payload, ensure_ascii=False) + "\n").encode())
            self.wfile.flush()
        except (BrokenPipeError, ConnectionResetError):
            raise SystemExit


class Server(socketserver.ThreadingUnixStreamServer):
    daemon_threads = True
    allow_reuse_address = True

    def __init__(self, path: Path, router: Router):
        self.router = router  # type: ignore[misc]
        if path.exists():
            path.unlink()
        super().__init__(str(path), _Handler)
        os.chmod(path, 0o600)


def socket_path() -> Path:
    """Сокет в рантайм-каталоге пользователя; /run на не-Linux может быть read-only."""
    candidates = []
    env = os.environ.get("XDG_RUNTIME_DIR")
    if env:
        candidates.append(Path(env))
    candidates.append(Path(f"/run/user/{os.getuid()}"))
    import tempfile

    candidates.append(Path(tempfile.gettempdir()) / f"wifikit-{os.getuid()}")
    for base in candidates:
        try:
            base.mkdir(parents=True, exist_ok=True)
        except OSError:
            continue
        if os.access(base, os.W_OK):
            return base / "wifikit.sock"
    return Path(tempfile.gettempdir()) / "wifikit.sock"


def serve(path: Path, router: Router, stop_event: threading.Event) -> None:
    server = Server(path, router)
    thread = threading.Thread(target=server.serve_forever, kwargs={"poll_interval": 0.2}, daemon=True)
    thread.start()
    stop_event.wait()
    server.shutdown()
    server.server_close()
    try:
        path.unlink()
    except OSError:
        pass


class Client:
    """Клиент для GUI: одно соединение, блокирующий запрос-ответ."""

    def __init__(self, path: Path | None = None, timeout: float = 300):
        self.path = path or socket_path()
        self.sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        self.sock.settimeout(timeout)
        self.sock.connect(str(self.path))
        self._buf = b""
        self._id = 0

    def call(self, method: str, **params) -> Any:
        self._id += 1
        payload = json.dumps({"id": self._id, "method": method, "params": params}, ensure_ascii=False)
        self.sock.sendall(payload.encode() + b"\n")
        while b"\n" not in self._buf:
            chunk = self.sock.recv(65536)
            if not chunk:
                raise ConnectionError("демон закрыл соединение")
            self._buf += chunk
        line, self._buf = self._buf.split(b"\n", 1)
        response = json.loads(line)
        if not response.get("ok"):
            error = response.get("error") or {}
            raise WilfiError(error.get("message", "ошибка демона"), code=error.get("code", "error"),
                             detail=error.get("detail", ""))
        return response.get("data")

    def close(self) -> None:
        try:
            self.sock.close()
        except OSError:
            pass
