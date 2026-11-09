"""Проверка зависимостей и версий бинарей."""

from __future__ import annotations

import re
from dataclasses import dataclass

from .base import MIN_VERSIONS, WilfiError, run, which

REQUIRED = {
    "iw": "iw",
    "ip": "iproute2",
    "nmcli": "network-manager",
    "hcxdumptool": "hcxdumptool",
    "hcxpcapngtool": "hcxtools",
    "hcxhashtool": "hcxtools",
    "hcxpmktool": "hcxtools",
    "aireplay-ng": "aircrack-ng",
    "airodump-ng": "aircrack-ng",
    "hostapd": "hostapd",
    "dnsmasq": "dnsmasq",
    "nft": "nftables",
    "hashcat": "hashcat",
    "rfkill": "rfkill",
}

VERSION_FLAGS = ("-v", "--version", "-V", "version")


@dataclass
class Dep:
    binary: str
    path: str | None
    version: tuple[int, ...] | None
    min_version: tuple[int, ...] | None
    ok: bool
    note: str = ""


def parse_version(text: str) -> tuple[int, ...] | None:
    m = re.search(r"(\d+)\.(\d+)(?:\.(\d+))?", text)
    if not m:
        return None
    return tuple(int(g) for g in m.groups() if g is not None)


def probe(binary: str) -> Dep:
    path = which(binary)
    minimum = MIN_VERSIONS.get(binary)
    if not path:
        return Dep(binary, None, None, minimum, False, f"нет в системе — пакет {REQUIRED.get(binary, binary)}")
    version = None
    for flag in VERSION_FLAGS:
        res = run([path, flag], timeout=8)
        text = (res.out + res.err).strip()
        if text and res.code in (0, 1):
            version = parse_version(text)
            if version:
                break
    note = ""
    if minimum and version and version < minimum:
        return Dep(binary, path, version, minimum, False,
                   f"версия {'.'.join(map(str, version))} устарела, нужна >= {'.'.join(map(str, minimum))}")
    if minimum and version is None:
        note = "версию определить не удалось"
    return Dep(binary, path, version, minimum, True, note)


def check_all() -> dict:
    deps = [probe(b) for b in REQUIRED]
    missing = [d.binary for d in deps if not d.ok]
    return {
        "ok": not missing,
        "missing": missing,
        "deps": [
            {
                "binary": d.binary,
                "path": d.path,
                "version": ".".join(map(str, d.version)) if d.version else None,
                "ok": d.ok,
                "note": d.note,
            }
            for d in deps
        ],
    }


def require_all() -> None:
    report = check_all()
    if not report["ok"]:
        raise WilfiError(
            "не хватает зависимостей: " + ", ".join(report["missing"]),
            code="missing_dep",
            detail="откройте мастер зависимостей",
        )


def hashcat_modes() -> dict:
    """Какие WPA-режимы реально знает установленный hashcat (SAE-модуля в hashcat нет)."""
    hc = which("hashcat")
    if not hc:
        return {"22000": False, "22001": False, "sae": False}
    res = run([hc, "-h"], timeout=15)
    text = res.out + res.err
    return {
        "22000": "22000 | WPA-PBKDF2-PMKID+EAPOL" in text,
        "22001": "22001 | WPA-PMK-PMKID+EAPOL" in text,
        "sae": "SAE" in text,
    }
