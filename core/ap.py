"""Фейк-точка: hostapd с клоном BSSID/SSID, DHCP, перехват DNS и HTTP.

Порядок подъёма: интерфейс в managed → адрес на нём → hostapd → dnsmasq →
nftables redirect 80→портал. Всё регистрируется в ResourceSet; откат снимает
правила, гасит демоны и возвращает адаптер.
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from pathlib import Path

from . import link
from .base import ResourceSet, WilfiError, ensure_dir, require, run, wait_until
from .jobs import Job, JobRegistry
from .scan import Ap

PORTAL_PORT = 8080
SUBNET = "192.168.77"
NFT_TABLE = "wifikit"


@dataclass
class ApConfig:
    ssid: str
    bssid: str
    channel: int
    band: str = "2.4"
    hidden: bool = False
    clone_mac: bool = True
    country: str = "RU"


class FakeAp:
    def __init__(self, jobs: JobRegistry, iface: str, workdir: Path):
        self.jobs = jobs
        self.iface = iface
        self.workdir = ensure_dir(workdir)
        self.resources = ResourceSet("ap")
        self.hostapd_job: Job | None = None
        self.dnsmasq_job: Job | None = None
        self.config: ApConfig | None = None
        self.portal_running = False

    @property
    def running(self) -> bool:
        return bool(self.hostapd_job and self.hostapd_job.state == "running")

    # ------------------------------------------------------------------ start
    def start(self, ap: Ap, portal_port: int = PORTAL_PORT, clone_bssid: bool = True) -> dict:
        if self.running:
            raise WilfiError("фейк-точка уже поднята", code="busy")
        hostapd = require("hostapd")
        require("dnsmasq")
        require("nft")
        cfg = ApConfig(
            ssid=ap.ssid or "Free WiFi",
            bssid=ap.bssid,
            channel=ap.channel or 6,
            band=ap.band,
            hidden=ap.ssid == "",
        )
        self.config = cfg
        self._prepare_interface(cfg, clone_bssid)
        conf = self._write_hostapd_conf(cfg)
        self._write_dnsmasq_conf()
        self._up_nft(portal_port)

        job = Job("hostapd", [hostapd, "-dd", str(conf)], title="фейк-точка")
        job.on_exit.append(self._on_hostapd_exit)
        self.hostapd_job = job
        self.jobs.add(job)
        if not wait_until(lambda: "AP-ENABLED" in job.tail(400) or not job.state == "running", 12):
            self.stop()
            raise WilfiError("hostapd не включил точку", detail=job.tail(600))
        if job.state != "running":
            raise WilfiError("hostapd упал при старте", detail=job.tail(800))
        dns = Job("dnsmasq", [require("dnsmasq"), "-d", "-C", str(self.workdir / "dnsmasq.conf")], title="DHCP/DNS")
        self.dnsmasq_job = dns
        self.jobs.add(dns)
        self.portal_running = True
        return self.status()

    def _prepare_interface(self, cfg: ApConfig, clone_bssid: bool) -> None:
        link.to_managed(self.iface)
        link.unmanage(self.iface, self.resources)
        link.down(self.iface)
        if clone_bssid and cfg.bssid:
            self.resources.add(f"вернуть MAC {self.iface}", lambda: None)
            res = run([require("ip"), "link", "set", self.iface, "address", cfg.bssid], timeout=10)
            if not res.ok:
                raise WilfiError("не удалось подменить MAC на BSSID точки", detail=res.err.strip())
        link.up(self.iface)

        def flush_addr() -> None:
            run([require("ip"), "addr", "flush", "dev", self.iface], timeout=10)

        self.resources.add(f"снять адрес с {self.iface}", flush_addr)
        link.set_channel(self.iface, cfg.channel, cfg.band)
        res = run([require("ip"), "addr", "add", f"{SUBNET}.1/24", "dev", self.iface], timeout=10)
        if not res.ok:
            raise WilfiError("не удалось назначить адрес шлюза", detail=res.err.strip())

    def _write_hostapd_conf(self, cfg: ApConfig) -> Path:
        conf = self.workdir / "hostapd.conf"
        band_lines = ["hw_mode=g", "ieee80211n=1"] if cfg.band == "2.4" else [
            "hw_mode=a", "ieee80211n=1", "ieee80211ac=1"]
        body = "\n".join([
            "interface=" + self.iface,
            "driver=nl80211",
            "ctrl_interface=" + str(self.workdir / "hostapd-ctrl"),
            "ssid=" + cfg.ssid,
            "bssid=" + cfg.bssid,
            "utf8_ssid=1",
            *band_lines,
            f"channel={cfg.channel}",
            f"country_code={cfg.country}",
            "wmm_enabled=1",
            "auth_algs=1",
            "ignore_broadcast_ssid=" + ("1" if cfg.hidden else "0"),
            "ap_isolate=1",
            "max_num_sta=64",
            "logger_syslog=0",
            "logger_stdout=1",
        ]) + "\n"
        conf.write_text(body)
        return conf

    def _write_dnsmasq_conf(self) -> Path:
        conf = self.workdir / "dnsmasq.conf"
        conf.write_text("\n".join([
            "port=53",
            f"interface={self.iface}",
            "bind-interfaces",
            "no-resolv",
            "no-hosts",
            f"dhcp-range={SUBNET}.10,{SUBNET}.200,255.255.255.0,1h",
            f"dhcp-option=3,{SUBNET}.1",
            f"dhcp-option=6,{SUBNET}.1",
            "address=/#/" + SUBNET + ".1",
            "log-dhcp",
            "log-queries",
            "log-facility=-",
        ]) + "\n")
        return conf

    def _up_nft(self, portal_port: int) -> None:
        nft = require("nft")
        run([nft, "delete", "table", "ip", NFT_TABLE], timeout=10)

        def drop_table() -> None:
            run([nft, "delete", "table", "ip", NFT_TABLE], timeout=10)

        self.resources.add("снять nft-таблицу", drop_table)
        script = "\n".join([
            f"table ip {NFT_TABLE} {{",
            "  chain prerouting {",
            "    type nat hook prerouting priority dstnat; policy accept;",
            f"    iifname \"{self.iface}\" tcp dport 80 redirect to :{portal_port}",
            f"    iifname \"{self.iface}\" udp dport 53 redirect to :53",
            "  }",
            "  chain forward {",
            "    type filter hook forward priority filter; policy accept;",
            f"    iifname \"{self.iface}\" accept",
            "  }",
            "}",
            "",
        ])
        path = self.workdir / "portal.nft"
        path.write_text(script)
        p = run([nft, "-f", str(path)], timeout=10)
        if not p.ok:
            raise WilfiError("nft не применил правила перенаправления", detail=p.err.strip())

    # ------------------------------------------------------------------ state
    def _on_hostapd_exit(self, job: Job) -> None:
        if self.dnsmasq_job and self.dnsmasq_job.state == "running":
            self.dnsmasq_job.request_stop()

    def stop(self) -> dict:
        for job in (self.dnsmasq_job, self.hostapd_job):
            if job and job.state in ("starting", "running"):
                job.request_stop()
        time.sleep(0.4)
        problems = self.resources.rollback()
        self.portal_running = False
        return {**self.status(), "problems": problems}

    def status(self) -> dict:
        return {
            "running": self.running,
            "iface": self.iface,
            "ssid": self.config.ssid if self.config else None,
            "bssid": self.config.bssid if self.config else None,
            "channel": self.config.channel if self.config else None,
            "clients": self.clients(),
            "hostapd": self.hostapd_job.status() if self.hostapd_job else None,
        }

    def clients(self) -> list[dict]:
        res = run([require("ip"), "neigh", "show", "dev", self.iface], timeout=8)
        out = []
        for line in res.out.splitlines():
            parts = line.split()
            if len(parts) >= 5 and parts[3] == "lladdr":
                out.append({"mac": parts[0], "ip": parts[4], "state": parts[-1]})
        return out
