"""Сканирование эфира и разбор возможностей точки.

Источник данных — `iw dev <if> scan` в managed-режиме (не требует инъекции) и
пассивный airodump-ng, когда интерфейс уже в monitor. Разбор RSN IE даёт бейджи
WPA2/WPA3/PMF, по которым UI решает, чем точку брать.
"""

from __future__ import annotations

import re
import time
from dataclasses import dataclass, field

from . import link
from .base import WilfiError, require, run

# RSN IE: OUI 00:0f:ac, тип 4 (AKM). SAE = 8, PSK = 2, 802.1X = 1.
AKM_NAMES = {"1": "802.1X", "2": "PSK", "3": "FT-PSK", "4": "FT-802.1X", "6": "PSK-SHA256",
             "8": "SAE", "9": "FT-SAE", "18": "OWE"}

PMF_REQUIRED = "pmf_req"
PMF_CAPABLE = "pmf_opt"

_WEAK_AKM_NOTE = "только WPA2 — крошится штатно"


@dataclass
class Ap:
    bssid: str
    ssid: str = ""
    channel: int = 0
    band: str = "2.4"
    freq: int = 0
    rssi: int = 0
    privacy: bool = False
    wpa: bool = False
    wpa2: bool = False
    wpa3: bool = False
    wps: bool = False
    akm: list[str] = field(default_factory=list)
    pmf: str | None = None
    vendor: str = ""
    beacon_interval: int = 0
    clients: int = 0

    @property
    def open(self) -> bool:
        return not self.privacy

    @property
    def crackable(self) -> bool:
        """WPA3-only без WPA2-совместимости оффлайн не крошится."""
        return self.wpa2 or self.wpa or self.open

    @property
    def deauth_ok(self) -> bool:
        return self.pmf != PMF_REQUIRED

    def technique_hint(self) -> str:
        if self.open:
            return "открытая сеть — портал сразу"
        if self.pmf == PMF_REQUIRED:
            return "PMF обязателен: деаут игнорируется, остаётся PMKID и пассивный захват"
        if self.wpa3 and not self.wpa2:
            return "WPA3-only: захват есть, оффлайн-крошилки в hashcat нет"
        if self.pmf == PMF_CAPABLE:
            return "PMF разрешён: деаут проходит не всегда, начинайте с PMKID"
        return "WPA2: PMKID → деаут + захват"

    def summary(self) -> dict:
        return {
            "bssid": self.bssid,
            "ssid": self.ssid,
            "channel": self.channel,
            "band": self.band,
            "freq": self.freq,
            "rssi": self.rssi,
            "privacy": self.privacy,
            "wpa": self.wpa,
            "wpa2": self.wpa2,
            "wpa3": self.wpa3,
            "pmf": self.pmf,
            "akm": self.akm,
            "wps": self.wps,
            "vendor": self.vendor,
            "clients": self.clients,
            "open": self.open,
            "crackable": self.crackable,
            "deauth_ok": self.deauth_ok,
            "hint": self.technique_hint(),
        }


def parse_iw_scan(text: str) -> list[Ap]:
    """Разбор вывода `iw dev X scan` (включая `-u` для RSN IE там, где он есть)."""
    aps: list[Ap] = []
    cur: Ap | None = None
    for raw in text.splitlines():
        line = raw.rstrip()
        stripped = line.strip()
        if stripped.startswith("BSS "):
            m = re.search(r"([0-9a-fA-F:]{17})", stripped)
            if not m:
                continue
            cur = Ap(bssid=m.group(1).lower())
            aps.append(cur)
            continue
        if cur is None:
            continue
        if stripped.startswith("freq:"):
            freq = int(stripped.split(":", 1)[1].strip().split()[0])
            cur.freq = freq
            cur.channel = link.freq_to_channel(freq)
            cur.band = "5" if freq >= 5000 else "2.4"
        elif stripped.startswith("signal:"):
            cur.rssi = int(float(stripped.split(":", 1)[1].split()[0]))
        elif stripped.startswith("beacon interval:"):
            try:
                cur.beacon_interval = int(stripped.split(":", 1)[1].strip())
            except ValueError:
                pass
        elif stripped.startswith("SSID:"):
            cur.ssid = stripped.split(":", 1)[1].strip()
        elif stripped.startswith("RSN:"):
            _parse_rsn_block(stripped, cur)
        elif stripped.startswith("WPA:"):
            cur.wpa = True
        elif "WPS:" in stripped:
            cur.wps = True
        elif stripped.startswith("* Authentication suites:"):
            for chunk in stripped.split(":", 1)[1].split():
                name = _akm_name(chunk)
                if name and name not in cur.akm:
                    cur.akm.append(name)
                    if name == "SAE":
                        cur.wpa3 = True
                    if name in ("PSK", "FT-PSK", "PSK-SHA256"):
                        cur.wpa2 = True
        elif stripped.startswith("* Capabilities:"):
            if "MFP-capable" in stripped:
                cur.pmf = PMF_CAPABLE
            if "MFP-required" in stripped:
                cur.pmf = PMF_REQUIRED
    return aps


def _akm_name(token: str) -> str | None:
    """iw печатает известные suite'ы именами, неизвестные — номерами. Понимаем оба."""
    token = token.strip(",").split("/")[-1].strip()
    if token.isdigit():
        return AKM_NAMES.get(token)
    return token or None


def _parse_rsn_block(stripped: str, ap: Ap) -> None:
    ap.privacy = True
    if "MFP-required" in stripped:
        ap.pmf = PMF_REQUIRED


def parse_airodump_csv(text: str) -> list[Ap]:
    """Разбор CSV-экспорта airodump-ng (только секция AP, до первой пустой строки)."""
    aps: list[Ap] = []
    in_ap = False
    for line in text.splitlines():
        if line.startswith("BSSID,"):
            in_ap = True
            continue
        if in_ap and (not line.strip() or line.startswith("Station MAC")):
            break
        if not in_ap:
            continue
        parts = [p.strip() for p in line.split(",")]
        if len(parts) < 14 or not re.match(r"([0-9A-Fa-f:]{17})", parts[0]):
            continue
        ap = Ap(bssid=parts[0].lower(), channel=int(parts[3]) if parts[3].isdigit() else 0,
                rssi=_to_int(parts[8]), ssid=parts[13])
        enc = parts[5].upper()
        if enc and enc != "OPN":
            ap.privacy = True
        if "WPA3" in enc or "SAE" in parts[7].upper():
            ap.wpa3 = True
        if "WPA2" in enc or "PSK" in parts[7].upper():
            ap.wpa2 = True
        if "WPA" in enc and "WPA2" not in enc:
            ap.wpa = True
        if "MGT" in parts[7].upper():
            ap.akm.append("802.1X")
        aps.append(ap)
    return aps


def _to_int(value: str) -> int:
    try:
        return int(value)
    except ValueError:
        return 0


def scan(iface: str, seconds: float = 12.0, channels: list[int] | None = None) -> list[Ap]:
    """Активный скан. Требует managed-режим и поднятый интерфейс."""
    iw = require("iw")
    if channels:
        found: dict[str, Ap] = {}
        for ch in channels:
            link.set_channel(iface, ch)
            for ap in _scan_once(iw, iface):
                found[ap.bssid] = ap
            time.sleep(0.4)
        return list(found.values())
    deadline = time.monotonic() + max(5.0, seconds)
    found = {}
    while time.monotonic() < deadline:
        for ap in _scan_once(iw, iface):
            found[ap.bssid] = ap
        time.sleep(1.0)
    return list(found.values())


def _scan_once(iw: str, iface: str) -> list[Ap]:
    res = run([iw, "dev", iface, "scan", "-u"], timeout=20)
    if not res.ok and "busy" in res.err.lower():
        run([iw, "dev", iface, "scan", "abort"], timeout=10)
        res = run([iw, "dev", iface, "scan", "-u"], timeout=20)
    if not res.ok:
        raise WilfiError("скан не удался", detail=res.err.strip()[:800])
    return parse_iw_scan(res.out)


def find_ap(aps: list[Ap], bssid: str) -> Ap | None:
    for ap in aps:
        if ap.bssid.lower() == bssid.lower():
            return ap
    return None
