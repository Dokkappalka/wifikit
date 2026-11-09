"""Проект: папка на диске со всем состоянием по одной цели.

Проект — единственный источник истины. GUI никогда не держит состояние у себя
дольше одного экрана: что не записано в проект, того не существует.
"""

from __future__ import annotations

import time
from dataclasses import asdict, dataclass, field
from pathlib import Path

from .base import PROJECTS_DIR, WilfiError, atomic_write_json, ensure_dir, read_json

STATE = "project.json"


@dataclass
class Target:
    bssid: str
    ssid: str = ""
    channel: int = 0
    band: str = "2.4"
    wpa2: bool = False
    wpa3: bool = False
    pmf: str | None = None
    vendor: str = ""


@dataclass
class Project:
    name: str
    path: Path
    target: Target | None = None
    probe_iface: str = ""
    ap_iface: str = ""
    portal_template: str = ""
    password: str = ""
    notes: list[str] = field(default_factory=list)
    created_at: float = field(default_factory=time.time)
    updated_at: float = field(default_factory=time.time)

    # ------------------------------------------------------------------ paths
    @property
    def dump_dir(self) -> Path:
        return ensure_dir(self.path / "dump")

    @property
    def hash_dir(self) -> Path:
        return ensure_dir(self.path / "hash")

    @property
    def ap_dir(self) -> Path:
        return ensure_dir(self.path / "ap")

    @property
    def report_dir(self) -> Path:
        return ensure_dir(self.path / "report")

    # ------------------------------------------------------------------- i/o
    def save(self) -> dict:
        self.updated_at = time.time()
        atomic_write_json(self.path / STATE, self.as_dict())
        return self.as_dict()

    def as_dict(self) -> dict:
        return {
            "name": self.name,
            "path": str(self.path),
            "target": asdict(self.target) if self.target else None,
            "probe_iface": self.probe_iface,
            "ap_iface": self.ap_iface,
            "portal_template": self.portal_template,
            "password": self.password,
            "notes": self.notes,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
        }

    def summary(self) -> dict:
        data = self.as_dict()
        data.pop("password", None)
        data["has_password"] = bool(self.password)
        data["files"] = len(list(self.path.rglob("*"))) if self.path.is_dir() else 0
        return data


def new(name: str, base: Path | None = None) -> Project:
    safe = _slug(name)
    root = ensure_dir(base or PROJECTS_DIR)
    path = root / f"{safe}-{time.strftime('%Y%m%d-%H%M%S')}"
    ensure_dir(path)
    project = Project(name=name, path=path)
    project.dump_dir, project.hash_dir, project.ap_dir, project.report_dir
    project.save()
    return project


def open_project(path: Path | str) -> Project:
    path = Path(path)
    data = read_json(path / STATE)
    if not data:
        raise WilfiError(f"в {path} нет проекта", code="no_project")
    project = Project(name=data.get("name") or path.name, path=path)
    target = data.get("target")
    if target:
        project.target = Target(**{k: v for k, v in target.items() if k in Target.__annotations__})
    project.probe_iface = data.get("probe_iface", "")
    project.ap_iface = data.get("ap_iface", "")
    project.portal_template = data.get("portal_template", "")
    project.password = data.get("password", "")
    project.notes = data.get("notes", [])
    project.created_at = data.get("created_at", project.created_at)
    project.updated_at = data.get("updated_at", project.updated_at)
    return project


def list_projects(base: Path | None = None) -> list[dict]:
    root = base or PROJECTS_DIR
    if not root.is_dir():
        return []
    out = []
    for entry in sorted(root.iterdir(), reverse=True):
        data = read_json(entry / STATE)
        if not data:
            continue
        target = data.get("target") or {}
        out.append({
            "path": str(entry),
            "name": data.get("name") or entry.name,
            "ssid": target.get("ssid", ""),
            "bssid": target.get("bssid", ""),
            "created_at": data.get("created_at", 0),
            "has_password": bool(data.get("password")),
        })
    return out


def _slug(text: str) -> str:
    keep = [c if (c.isalnum() or c in "-_") else "-" for c in text.lower()]
    return "".join(keep).strip("-")[:60] or "project"
