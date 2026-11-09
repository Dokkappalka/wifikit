"""Отчёт по проекту в Markdown и HTML."""

from __future__ import annotations

import html
import time
from pathlib import Path

from .project import Project


def _fmt(ts: float) -> str:
    return time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(ts))


def build_markdown(project: Project, extra: dict | None = None) -> str:
    t = project.target
    lines = [
        f"# Отчёт: {project.name}",
        "",
        f"- создан: {_fmt(project.created_at)}",
        f"- обновлён: {_fmt(project.updated_at)}",
        "",
        "## Цель",
        "",
    ]
    if t:
        lines += [
            f"- SSID: `{t.ssid}`",
            f"- BSSID: `{t.bssid}`",
            f"- канал: {t.channel} ({t.band} ГГц)",
            f"- шифрование: {'WPA3' if t.wpa3 else ''}{'WPA2' if t.wpa2 else ''}".strip(),
            f"- PMF: {t.pmf or 'нет'}",
            f"- вендор: {t.vendor or '—'}",
        ]
    else:
        lines.append("- цель не задана")
    lines += ["", "## Адаптеры", "", f"- сенсор: `{project.probe_iface or '—'}`", f"- фейк-точка: `{project.ap_iface or '—'}`", ""]
    lines += ["## Результат", ""]
    if project.password:
        lines.append(f"**Пароль найден: `{project.password}`**")
    else:
        lines.append("пароль не найден")
    if extra:
        lines += ["", "## Детали", ""]
        for key, value in extra.items():
            lines.append(f"- {key}: {value}")
    if project.notes:
        lines += ["", "## Заметки", ""] + [f"- {n}" for n in project.notes]
    files = sorted(p.relative_to(project.path) for p in project.path.rglob("*") if p.is_file())
    if files:
        lines += ["", "## Файлы", ""] + [f"- `{f}`" for f in files]
    lines += ["", "---", "", "Отчёт собран wifikit."]
    return "\n".join(lines) + "\n"


def build_html(project: Project, extra: dict | None = None) -> str:
    md = build_markdown(project, extra)
    body = []
    for line in md.splitlines():
        esc = html.escape(line)
        if line.startswith("# "):
            body.append(f"<h1>{esc[2:]}</h1>")
        elif line.startswith("## "):
            body.append(f"<h2>{esc[3:]}</h2>")
        elif line.startswith("- "):
            body.append(f"<li>{esc[2:]}</li>")
        elif line.strip() == "":
            body.append("")
        else:
            body.append(f"<p>{esc}</p>")
    css = """
    body{background:#12141a;color:#dfe3ea;font:15px/1.6 ui-monospace,Menlo,monospace;max-width:820px;margin:40px auto;padding:0 20px}
    h1{font-size:22px;font-weight:600;border-bottom:1px solid #262b36;padding-bottom:12px}
    h2{font-size:15px;text-transform:uppercase;letter-spacing:.08em;color:#8b93a3;margin-top:28px}
    li{margin-left:-16px} code{color:#7fd1a4}
    """
    # li подряд склеиваем в ul
    joined: list[str] = []
    in_list = False
    for chunk in body:
        if chunk.startswith("<li>"):
            if not in_list:
                joined.append("<ul>")
                in_list = True
            joined.append(chunk)
        else:
            if in_list:
                joined.append("</ul>")
                in_list = False
            joined.append(chunk)
    if in_list:
        joined.append("</ul>")
    return (
        "<!doctype html><html lang=\"ru\"><meta charset=\"utf-8\">"
        f"<title>Отчёт {html.escape(project.name)}</title><style>{css}</style><body>"
        + "\n".join(joined)
        + "</body></html>"
    )


def export(project: Project, fmt: str = "md", extra: dict | None = None) -> Path:
    stamp = time.strftime("%Y%m%d-%H%M%S")
    if fmt == "html":
        path = project.report_dir / f"report-{stamp}.html"
        path.write_text(build_html(project, extra))
    else:
        path = project.report_dir / f"report-{stamp}.md"
        path.write_text(build_markdown(project, extra))
    return path
