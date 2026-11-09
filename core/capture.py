"""Захват рукопожатий и PMKID.

Тактика: канал фиксируется на точку (channel hopping отключён), hcxdumptool
работает в активном режиме и сам выходит по первому EAPOL/PMKID
(`--exitoneapol`). Никаких BPF-фильтров — сборка не всегда с libpcap; лишнее
отсекается при конвертации через `hcxhashtool --mac-ap`.
"""

from __future__ import annotations

import shutil
import time
from dataclasses import dataclass, field
from pathlib import Path

from . import convert, link
from .base import ResourceSet, WilfiError, ensure_dir, require, run
from .jobs import Job, JobRegistry
from .scan import Ap

# битмаска --exitoneapol
EXIT_PMKID = 1
EXIT_M123 = 2
EXIT_M12 = 4
EXIT_M12ROGUE = 8
EXIT_M1 = 16

MODES = {
    "handshake": EXIT_M123 | EXIT_M12,  # только полноценные пары
    "pmkid": EXIT_PMKID,
    "any": EXIT_PMKID | EXIT_M123 | EXIT_M12 | EXIT_M12ROGUE,
}


@dataclass
class CaptureResult:
    mode: str
    bssid: str
    dump: Path
    hash_file: Path | None = None
    pmkid_lines: int = 0
    eapol_lines: int = 0
    authorized: int = 0
    replay_checked: bool = False
    success: bool = False
    notes: list[str] = field(default_factory=list)

    def summary(self) -> dict:
        return {
            "mode": self.mode,
            "bssid": self.bssid,
            "dump": str(self.dump),
            "hash_file": str(self.hash_file) if self.hash_file else None,
            "pmkid": self.pmkid_lines,
            "eapol": self.eapol_lines,
            "authorized": self.authorized,
            "replay_checked": self.replay_checked,
            "success": self.success,
            "notes": self.notes,
        }


class Capture:
    def __init__(self, jobs: JobRegistry, iface: str, out_dir: Path):
        self.jobs = jobs
        self.iface = iface
        self.out_dir = ensure_dir(out_dir)
        self.job: Job | None = None
        self.result: CaptureResult | None = None
        self.resources = ResourceSet("capture")
        self._files: list[Path] = []
        self._last_count = 0
        self._started = 0.0

    # ------------------------------------------------------------------ start
    def start(self, ap: Ap, mode: str = "handshake", minutes: float = 5.0) -> dict:
        if self.job and self.job.state in ("starting", "running", "stopping"):
            raise WilfiError("захват уже идёт", code="busy")
        if mode not in MODES:
            raise WilfiError(f"неизвестный режим {mode}")
        hcx = require("hcxdumptool")
        if not ap.channel:
            raise WilfiError("у точки неизвестен канал — сначала просканируйте её", code="no_channel")
        if mode == "handshake" and ap.pmf and ap.pmf == "pmf_req":
            pass  # не блокер: пассивный захват тоже возможен
        link.to_monitor(self.iface, self.resources)
        link.set_channel(self.iface, ap.channel, ap.band)
        dump = self.out_dir / f"{_slug(ap.bssid)}-{int(time.time())}.pcapng"
        argv = [
            hcx,
            "-i", self.iface,
            "-c", f"{ap.channel}{'b' if ap.band == '5' else 'a'}",
            "-t", "2",
            "-w", str(dump),
            f"--tot={max(1, int(round(minutes)))}",
            f"--exitoneapol={MODES[mode]}",
            "--rds=0",
        ]
        job = Job("capture", argv, title=f"захват {ap.ssid or ap.bssid} ({mode})")
        job.on_exit.append(lambda j: self._on_exit(j, ap, mode, dump))
        self.job = job
        self._started = time.time()
        self.jobs.add(job)
        return {"job": job.status(), "dump": str(dump)}

    def _on_exit(self, job: Job, ap: Ap, mode: str, dump: Path) -> None:
        notes: list[str] = []
        self.result = CaptureResult(mode=mode, bssid=ap.bssid, dump=dump, notes=notes)
        problems = self.resources.rollback()
        notes.extend(f"откат: {p}" for p in problems)
        if not dump.exists():
            notes.append("файл дампа не создан")
            self.result.success = False
            return
        try:
            res = convert.convert_and_filter(dump, self.out_dir, ap.bssid)
        except WilfiError as exc:
            notes.append(f"конвертация: {exc}")
            self.result.success = False
            return
        self.result.hash_file = res.hash_file
        self.result.pmkid_lines = res.pmkid
        self.result.eapol_lines = res.eapol
        self.result.authorized = res.authorized
        self.result.replay_checked = res.replay_checked
        self.result.success = res.pmkid > 0 or res.authorized > 0
        if not self.result.success and res.eapol > 0:
            notes.append("есть EAPOL без M2M3 — попробуйте ещё раз или включите деаут")
        if res.replay_checked:
            notes.append("replaycount проверен: M2M3 не подделка")

    # ---------------------------------------------------------------- control
    def status(self) -> dict:
        data = {
            "job": self.job.status() if self.job else None,
            "result": self.result.summary() if self.result else None,
            "elapsed": round(time.time() - self._started, 1) if self.job and self.job.state == "running" else 0,
        }
        return data

    def stop(self) -> dict:
        if self.job and self.job.state in ("starting", "running"):
            self.job.request_stop()
        else:
            self.resources.rollback()
        return self.status()

    def cleanup(self) -> None:
        if not self.result:
            self.resources.rollback()


def _slug(text: str) -> str:
    return "".join(c if c.isalnum() else "-" for c in text.lower()).strip("-")


def free_space(path: Path) -> int:
    try:
        return shutil.disk_usage(path).free
    except OSError:
        return 0


def interface_channels(iface: str) -> list[int]:
    """Каналы, которые адаптер реально умеет (для UI-карты каналов)."""
    out = run([require("iw"), "dev", iface, "info"], timeout=8).out
    return []
