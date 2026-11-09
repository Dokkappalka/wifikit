"""Конвертация pcapng в .hc22000, отсев по точке и оценка качества пар."""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

from .base import WilfiError, require, run

PMKID_PREFIX = "WPA*01*"
EAPOL_PREFIX = "WPA*02*"


@dataclass
class ConvertResult:
    hash_file: Path
    pmkid: int
    eapol: int
    authorized: int
    challenge: int
    replay_checked: bool
    info: str

    def summary(self) -> dict:
        return {
            "hash_file": str(self.hash_file),
            "pmkid": self.pmkid,
            "eapol": self.eapol,
            "authorized": self.authorized,
            "challenge": self.challenge,
            "replay_checked": self.replay_checked,
        }


def filter_lines(lines: list[str], bssid: str) -> list[str]:
    """Оставляем только пары, где AP совпадает с целью (MAC в хэше без двоеточий)."""
    needle = f"*{bssid.replace(':', '').lower()}*"
    return [ln for ln in lines if needle in ln.lower()]


def convert_and_filter(dump: Path, out_dir: Path, bssid: str) -> ConvertResult:
    """Конвертируем дамп и оставляем только пары по нужной точке.

    `--all` не используем: он раздувает список негодными парами. Берём лучшее,
    затем фильтруем по MAC AP — иначе в хэше окажутся соседние сети.
    """
    if not dump.is_file() or dump.stat().st_size == 0:
        raise WilfiError("пустой дамп", code="empty_dump")
    conv = require("hcxpcapngtool")
    hash_file = out_dir / (dump.stem + ".hc22000")
    res = run([conv, "-o", str(hash_file), str(dump)], timeout=180)
    if not hash_file.is_file():
        raise WilfiError("hcxpcapngtool не создал хэш", detail=(res.err or res.out)[-1200:])
    raw_lines = [ln for ln in hash_file.read_text(errors="replace").splitlines() if ln.strip()]
    only_mac = filter_lines(raw_lines, bssid)
    hash_file.write_text("\n".join(only_mac) + ("\n" if only_mac else ""))
    pmkid = sum(1 for ln in only_mac if ln.startswith(PMKID_PREFIX))
    eapol = sum(1 for ln in only_mac if ln.startswith(EAPOL_PREFIX))
    info_text = ""
    authorized = challenge = 0
    replay_checked = False
    if only_mac:
        info_text, authorized, challenge, replay_checked = _quality(hash_file)
    return ConvertResult(
        hash_file=hash_file,
        pmkid=pmkid,
        eapol=eapol,
        authorized=authorized,
        challenge=challenge,
        replay_checked=replay_checked,
        info=info_text,
    )


def _quality(hash_file: Path) -> tuple[str, int, int, bool]:
    hh = require("hcxhashtool")
    res = run([hh, "-i", str(hash_file), "--info=stdout"], timeout=30)
    text = res.out + res.err
    authorized = _count_after(text, r"M2M3|M3M4")
    challenge = _count_after(text, r"M1M2")
    return text[-2000:], authorized, challenge, replay_checked(text)


def replay_checked(text: str) -> bool:
    """replaycount считается проверенным только если непроверенных ровно ноль."""
    unchecked = _count_after(text, r"replaycount not checked:")
    checked = _count_after(text, r"replaycount checked:")
    return checked > 0 and unchecked == 0


def _count_after(text: str, pattern: str) -> int:
    total = 0
    for m in re.finditer(pattern, text):
        tail = text[m.end(): m.end() + 40]
        num = re.search(r"(\d+)", tail)
        if num:
            total += int(num.group(1))
    return total


def best_pair(hash_file: Path) -> str | None:
    """Первый пригодный хэш: PMKID приоритетнее, authorized EAPOL — нет."""
    lines = [ln for ln in hash_file.read_text(errors="replace").splitlines() if ln.strip()]
    for prefix in (PMKID_PREFIX, EAPOL_PREFIX):
        for ln in lines:
            if ln.startswith(prefix):
                return ln
    return None
