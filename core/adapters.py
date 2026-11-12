"""Обнаружение адаптеров и их возможностей.

Роли задаются явно: `probe` (monitor + инъекция) и `ap` (AP-режим). Возможности
читаются из nl80211 (`iw phy`), а не угадываются по имени драйвера; драйвер лишь
даёт предупреждения о известных проблемах.
"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass, field
from pathlib import Path

from .base import NotSupported, WilfiError, run, which

SYS_NET = Path("/sys/class/net")
KNOWN_MONITOR_DRIVERS = {"mt7921u", "mt76x0u", "mt76x2u", "mt7612u", "rt2800usb", "carl9170", "ath9k_htc", "8812au", "rtl8812au", "rtl88xxau"}
KNOWN_AP_DRIVERS = {"ath9k_htc", "rt2800usb", "mt76x0u", "mt76x2u", "mt7612u", "mt7921u", "8812au", "rtl8812au"}
MULTISTATE_DRIVERS = {"rtw_8821cu", "rtw_8822bu", "rtw_8822cu", "rtw_8852bu", "rtw89_8852bu", "rtw_8852cu"}
DFS_CHANNELS = set(range(52, 65)) | set(range(100, 145))



@dataclass
class Adapter:
    iface: str
    phy: str = ""
    mac: str = ""
    driver: str = ""
    usb_id: tuple[str, str] | None = None
    bands: set[str] = field(default_factory=set)
    monitor: bool = False
    ap: bool = False
    injection: bool | None = None
    mode: str = "managed"
    up: bool = False
    rfkill_blocked: bool = False
    warnings: list[str] = field(default_factory=list)

    @property
    def key(self) -> str:
        return self.iface

    @property
    def pretty_id(self) -> str:
        if self.usb_id:
            return f"{self.usb_id[0]}:{self.usb_id[1]}"
        return ""

    @property
    def can_probe(self) -> bool:
        return self.monitor and not self.rfkill_blocked

    @property
    def can_ap(self) -> bool:
        if not self.ap:
            return False
        if self.monitor and "mt7921u" in {self.driver}:
            return True  # VIF поддерживается
        return True

    def summary(self) -> dict:
        return {
            "iface": self.iface,
            "phy": self.phy,
            "mac": self.mac,
            "driver": self.driver,
            "usb_id": self.pretty_id,
            "bands": sorted(self.bands),
            "monitor": self.monitor,
            "ap": self.ap,
            "injection": self.injection,
            "mode": self.mode,
            "rfkill_blocked": self.rfkill_blocked,
            "warnings": self.warnings,
            "suitable_probe": self.can_probe,
            "suitable_ap": self.can_ap,
            "degraded": self.iface.startswith(("wlx",)) or bool(self.usb_id),
        }


def _read(path: Path, default: str = "") -> str:
    try:
        return path.read_text(errors="replace").strip()
    except OSError:
        return default


def _usb_ids(iface_path: Path) -> tuple[str, str] | None:
    """Поднимаемся по sysfs до USB-устройства, если интерфейс на USB-шине."""
    cur = iface_path.resolve()
    for _ in range(8):
        cur = cur.parent
        uevent = cur / "uevent"
        if uevent.is_file():
            text = _read(uevent)
            vid = re.search(r"^PRODUCT=([0-9a-f]+)/([0-9a-f]+)/", text, re.M)
            if vid:
                return vid.group(1), vid.group(2)
            if "usb" in cur.name or (cur / "idVendor").is_file():
                v, p = _read(cur / "idVendor"), _read(cur / "idProduct")
                if v and p:
                    return v, p
    return None


def _driver(iface_path: Path) -> str:
    link = iface_path / "device" / "driver"
    if link.exists():
        return link.resolve().name
    return ""


def _rfkill_blocked() -> set[str]:
    """Интерфейсы, заблокированные через rfkill (soft или hard)."""
    blocked: set[str] = set()
    idx_to_name: dict[str, str] = {}
    for entry in Path("/sys/class/rfkill").glob("rfkill*"):
        if _read(entry / "type") != "wlan":
            continue
        if _read(entry / "soft") == "1" or _read(entry / "hard") == "1":
            idx = _read(entry / "index")
            if idx:
                idx_to_name[idx] = "?"
    # точное сопоставление через `rfkill -o` недоступно без парсинга; берём через iw dev
    if idx_to_name:
        for line in _iw_dev().splitlines():
            if "Interface" in line:
                blocked.add(line.split()[-1])
    return blocked


def _iw_dev() -> str:
    iw = which("iw")
    if not iw:
        return ""
    return run([iw, "dev"], timeout=10).out


def _phy_caps(phy: str) -> tuple[set[str], set[str], set[str]]:
    """(режимы, диапазоны, каналы DFS-ограничения)."""
    iw = which("iw")
    if not iw or not phy:
        return set(), set(), set()
    res = run([iw, "phy", phy, "info"], timeout=15)
    modes: set[str] = set()
    bands: set[str] = set()
    in_modes = False
    for line in res.out.splitlines():
        s = line.strip()
        if s.startswith("Supported interface modes"):
            in_modes = True
            continue
        if in_modes:
            if s.startswith("* "):
                modes.add(s[2:].strip().lower())
                continue
            in_modes = False
        if s.startswith("Band "):
            bands.add(s.split()[1])
    return modes, bands, set()


def list_adapters(include_all: bool = False) -> list[Adapter]:
    result: list[Adapter] = []
    blocked = set()
    for entry in sorted(SYS_NET.glob("*")):
        if not (entry / "phy80211").exists() and not (entry / "wireless").exists():
            continue
        phy_link = entry / "phy80211"
        phy = phy_link.resolve().name if phy_link.exists() else ""
        adapter = Adapter(iface=entry.name, phy=phy)
        adapter.mac = _read(entry / "address")
        adapter.driver = _driver(entry)
        adapter.usb_id = _usb_ids(entry / "device") if (entry / "device").exists() else None
        adapter.mode = _read(entry / "type") if False else ("monitor" if _is_monitor(entry.name) else "managed")
        adapter.up = _read(entry / "operstate") not in ("down", "unknown")
        modes, bands, _ = _phy_caps(phy)
        adapter.monitor = "monitor" in modes
        adapter.ap = "ap" in modes or "ap/vlan" in modes
        adapter.bands = bands or {"2.4"}
        adapter.rfkill_blocked = entry.name in blocked
        if not adapter.monitor:
            adapter.warnings.append("нет monitor-режима")
        if not adapter.ap:
            adapter.warnings.append("нет AP-режима")
        if not adapter.monitor and not adapter.ap:
            adapter.warnings.append("непригоден для работы")
        if include_all or adapter.monitor or adapter.ap:
            result.append(adapter)
    return result


def _is_monitor(iface: str) -> bool:
    iw = which("iw")
    if not iw:
        return False
    out = run([iw, "dev", iface, "info"], timeout=10).out
    return "type monitor" in out


def get_adapter(iface: str) -> Adapter:
    for a in list_adapters(include_all=True):
        if a.iface == iface:
            return a
    raise WilfiError(f"интерфейс {iface} не найден или не Wi-Fi", code="no_adapter")


def ensure_capability(adapter: Adapter, role: str) -> None:
    if role == "probe":
        if not adapter.monitor:
            raise NotSupported(f"{adapter.iface}: драйвер не поддерживает monitor mode")
        if adapter.rfkill_blocked:
            raise NotSupported(f"{adapter.iface}: заблокирован rfkill", detail="sudo rfkill unblock wifi")
    elif role == "ap":
        if not adapter.ap:
            raise NotSupported(f"{adapter.iface}: драйвер не поддерживает AP-режим")
    else:
        raise WilfiError(f"неизвестная роль {role}")


def assert_distinct(probe_iface: str, ap_iface: str) -> None:
    if probe_iface == ap_iface:
        raise WilfiError(
            "один адаптер не может быть и сенсором, и фейк-точкой",
            code="same_adapter",
            detail="подключите второй адаптер",
        )
    if not probe_iface or not ap_iface:
        raise WilfiError("выберите оба адаптера", code="no_adapter")


def test_injection(iface: str) -> dict:
    """Боевой тест инъекции: aireplay-ng --test на monitor-интерфейсе."""
    aireplay = which("aireplay-ng")
    if not aireplay:
        raise WilfiError("нет aireplay-ng", code="missing_dep")
    res = run([aireplay, "--test", iface], timeout=25)
    text = (res.out + res.err).strip()
    ok = "Injection is working" in text or "Injection is working!" in text
    return {"ok": ok, "output": text[-1500:]}


def hw_fingerprint() -> str:
    return _read(Path("/sys/devices/virtual/dmi/id/product_name")) + "|" + os.uname().machine
