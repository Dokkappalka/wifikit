"""Проверка кандидата: оффлайн по хэшу и онлайн ассоциацией."""

from __future__ import annotations

import re
import tempfile
import time
from pathlib import Path

from . import link
from .base import ResourceSet, WilfiError, require, run, wait_until
from .convert import best_pair


def check_offline(hash_file: Path, psk: str) -> dict:
    """hcxpmktool: 0 — пароль подтверждён, 2 — не подтверждён, 1 — ошибка."""
    pmk = require("hcxpmktool")
    line = best_pair(hash_file)
    if not line:
        raise WilfiError("в хэше нет пригодной пары", code="no_pair")
    res = run([pmk, "-l", line, "-p", psk], timeout=30)
    if res.code == 0:
        return {"ok": True, "reason": "подтверждён по захваченному рукопожатию"}
    if res.code == 2:
        return {"ok": False, "reason": "не подходит к захваченному рукопожатию"}
    raise WilfiError("hcxpmktool не смог проверить", detail=(res.out + res.err)[-800:])


def check_online(iface: str, ssid: str, psk: str, timeout: float = 25.0) -> dict:
    """Пробуем реальную ассоциацию через wpa_supplicant (нужен свободный адаптер)."""
    wpa = require("wpa_supplicant")
    require("wpa_cli")
    conf = Path(tempfile.mkdtemp(prefix="wifikit-verify-")) / "wpa.conf"
    conf.write_text(
        "ctrl_interface=/run/wifikit-verify\n"
        "network={\n"
        f'\tssid="{ssid}"\n'
        f'\tpsk="{psk}"\n'
        "\tkey_mgmt=WPA-PSK\n"
        "}\n"
    )
    resources = ResourceSet("verify")
    try:
        link.to_managed(iface)
        job = require("wpa_supplicant")
        proc = run([job, "-B", "-i", iface, "-c", str(conf)], timeout=20)
        resources.add("остановить wpa_supplicant", lambda: run([require("wpa_cli"), "-i", iface, "terminate"], timeout=15))
        if not proc.ok and "already running" not in (proc.out + proc.err):
            return {"ok": False, "reason": "wpa_supplicant не запустился", "detail": (proc.err or proc.out)[-600:]}
        state = {"value": ""}

        def poll() -> bool:
            res = run([require("wpa_cli"), "-i", iface, "status"], timeout=10)
            m = re.search(r"wpa_state=(\w+)", res.out)
            if m:
                state["value"] = m.group(1)
            return state["value"] in ("COMPLETED", "4WAY_HANDSHAKE", "DISCONNECTED")

        wait_until(lambda: state["value"] == "COMPLETED", timeout)
        ok = state["value"] == "COMPLETED"
        return {"ok": ok, "reason": "ассоциация установлена" if ok else f"состояние {state['value'] or 'нет ответа'}"}
    finally:
        resources.rollback()
        link.to_managed(iface)


def guess_candidates(essid: str, bssid: str, extra_args: list[str] | None = None) -> list[str]:
    """Кандидаты по вендорским шаблонам через hcxpsktool."""
    tool = require("hcxpsktool")
    args = [tool, "-e", essid, "-b", bssid.replace(":", "").lower()]
    if extra_args:
        args += extra_args
    res = run(args, timeout=120)
    return [ln for ln in res.out.splitlines() if ln.strip()]
