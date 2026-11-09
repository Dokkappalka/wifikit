#!/usr/bin/env python3
"""Проверка отрендеренных шаблонов портала (stdlib only).

Для каждого шаблона: загрузка через core.portal.load_template(), рендер всех
шагов с «злыми» тестовыми значениями, проверка разметки и живой HTTP-обмен
(GET страницы, GET статики, POST /submit с JSON и urlencoded).

Проверяется:
  (а) шаблон грузится без WilfiError;
  (б) в отрендеренном HTML остаётся input type=password;
  (в) нет незаменённых {{ ... }} (допустимы только ключи, которые знает сервер);
  (г) поля из meta.json реально присутствуют в разметке;
  (д) нет внешних ресурсов (CDN) — портал работает без интернета;
  (е) сервер отдаёт страницы и JSON-вердикт на POST.
"""

from __future__ import annotations

import json
import re
import sys
import urllib.parse
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from core.base import WilfiError  # noqa: E402
from core.portal import PLACEHOLDER, Portal, load_template, serve, stop  # noqa: E402

TEMPLATES = [
    ("routers/tp-link", ["password"]),
    ("routers/keenetic", ["password"]),
    ("cafe/free-wifi", ["name", "phone", "password"]),
    ("hotel/hotel-login", ["room", "surname", "password"]),
    ("firmware/update", ["password"]),
    ("generic/two-step", ["password"]),
]
SERVER_KEYS = {"SSID", "VENDOR", "LANG", "TITLE", "ACTION", "STEP", "STATIC"}
TEST_SSID = 'Cafe "Bar" & <Wi-Fi> №7'
TEST_VALUES = {"password": "s3cret-Pass", "name": "Иван", "phone": "+79001234567",
               "room": "412", "surname": "Petrov", "ssid": TEST_SSID}

failures: list[str] = []
checked = 0


def fail(tid: str, msg: str) -> None:
    failures.append(f"{tid}: {msg}")
    print(f"  FAIL {msg}")


def get(url: str) -> tuple[int, str, str]:
    with urllib.request.urlopen(url, timeout=5) as resp:
        return resp.status, resp.headers.get("Content-Type", ""), resp.read().decode("utf-8", "replace")


def post(url: str, payload: dict, as_json: bool) -> str:
    if as_json:
        body = json.dumps(payload).encode()
        ctype = "application/json"
    else:
        body = urllib.parse.urlencode(payload).encode()
        ctype = "application/x-www-form-urlencoded"
    req = urllib.request.Request(url, data=body, headers={"Content-Type": ctype}, method="POST")
    with urllib.request.urlopen(req, timeout=5) as resp:
        return json.loads(resp.read().decode())["verdict"]


def main() -> int:
    global checked
    for tid, expected_fields in TEMPLATES:
        print(f"\n[{tid}]")
        try:
            tpl = load_template(tid)
        except WilfiError as exc:
            fail(tid, f"шаблон не загрузился: {exc} (code={exc.code})")
            continue
        print(f"  загружен: name={tpl.name!r} lang={tpl.lang} steps={tpl.steps}")

        if tpl.lang not in {"ru", "en"}:
            fail(tid, f"неожиданный lang {tpl.lang!r}")
        if tpl.fields_expected != expected_fields:
            fail(tid, f"fields {tpl.fields_expected} != ожидаемых {expected_fields}")

        portal = Portal(tid, ssid=TEST_SSID, vendor=tpl.lang)
        all_html = []
        for index, step_name in enumerate(tpl.steps):
            raw = (tpl.dir / step_name).read_text()
            bad_keys = {m.group(1) for m in PLACEHOLDER.finditer(raw)} - SERVER_KEYS
            if bad_keys:
                fail(tid, f"{step_name}: неизвестные плейсхолдеры {sorted(bad_keys)}")
            html = portal.render(index).decode()
            all_html.append((step_name, html))

            leftover = PLACEHOLDER.findall(html)
            if leftover:
                fail(tid, f"{step_name}: остались плейсхолдеры {sorted(set(leftover))}")
            if not re.search(r"type=[\"']?password", html, re.I):
                fail(tid, f"{step_name}: нет input[type=password]")
            if "<input" in html and not re.search(r"type=[\"']?password", html, re.I):
                fail(tid, f"{step_name}: password-поле потеряно при рендере")
            if 'fetch({{' in html or "fetch('{{" in html:
                fail(tid, f"{step_name}: fetch не подставил ACTION")
            if "https://" in html or "http://" in html:
                fail(tid, f"{step_name}: внешние ресурсы (CDN) запрещены")
            if re.search(r"\balert\s*\(", html):
                fail(tid, f"{step_name}: используется alert()")
            if "localStorage" in html or "sessionStorage" in html:
                fail(tid, f"{step_name}: используется storage")
            if TEST_SSID not in html.replace("&quot;", '"').replace("&lt;", "<").replace("&gt;", ">").replace("&amp;", "&") \
                    and "{{SSID}}" in raw:
                fail(tid, f"{step_name}: SSID не подставлен")

        joined = "\n".join(h for _, h in all_html)
        for field in expected_fields:
            if f'name="{field}"' not in joined:
                fail(tid, f"в разметке нет поля {field}")
        if '{{ACTION}}' in joined:
            fail(tid, "ACTION не подставлен")

        # ---- живой HTTP-обмен
        try:
            serve(portal, "127.0.0.1", 0)
            base = f"http://127.0.0.1:{portal.port}"
            code, ctype, page = get(base + "/")
            if code != 200 or "text/html" not in ctype:
                fail(tid, f"GET / → {code} {ctype}")
            if 'action="{{ACTION}}"' in page:
                fail(tid, "в отданной странице остался action-плейсхолдер")
            if not re.search(r"type=[\"']?password", page, re.I):
                fail(tid, "GET / отдал страницу без password-поля")
            if tpl.steps and tpl.steps[0] != "index.html":
                fail(tid, f"первый шаг {tpl.steps[0]!r}")

            code, ctype, _ = get(base + "/static/" + tpl.steps[-1])
            if code != 200:
                fail(tid, f"GET /static/{tpl.steps[-1]} → {code}")

            if len(tpl.steps) > 1:
                _, _, step_html = get(base + "/step")
                if not re.search(r"href=[\"']/[\"']", step_html):
                    fail(tid, "на шаге /step нет ссылки «назад» на /")

            verdict = post(base + "/submit", dict(TEST_VALUES), as_json=True)
            if verdict not in {"ok", "retry", "pending"}:
                fail(tid, f"JSON-POST вернул {verdict!r}")
            verdict = post(base + "/submit", dict(TEST_VALUES), as_json=False)
            if verdict not in {"ok", "retry", "pending"}:
                fail(tid, f"urlencoded-POST вернул {verdict!r}")
            if not portal.submissions:
                fail(tid, "сервер не сохранил отправку")
            stop(portal)
            print(f"  HTTP: страница, статика, оба POST — ok (собрано полей: {len(portal.submissions)})")
            checked += 1
        except Exception as exc:  # noqa: BLE001
            fail(tid, f"HTTP-проверка: {exc!r}")
            stop(portal)

    print("\n" + "=" * 58)
    if failures:
        print(f"ПРОВАЛЕНО: {len(failures)}")
        for item in failures:
            print(" -", item)
        return 1
    print(f"Все {checked} шаблонов прошли проверку.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
