"""Управление интерфейсами: monitor/managed, up/down, вывод из-под NetworkManager.

Все изменения регистрируются в ResourceSet, чтобы откат вернул систему в исходное
состояние без участия человека.
"""

from __future__ import annotations

from .base import ResourceSet, WilfiError, require, run, wait_until

NMCLI_TIMEOUT = 15


def _ip() -> str:
    return require("ip")


def is_up(iface: str) -> bool:
    res = run([_ip(), "-o", "link", "show", iface], timeout=10)
    if not res.ok:
        raise WilfiError(f"интерфейс {iface} не найден", detail=res.err)
    return "state UP" in res.out


def type_of(iface: str) -> str:
    out = run([require("iw"), "dev", iface, "info"], timeout=10).out
    for line in out.splitlines():
        if "type " in line:
            return line.split("type", 1)[1].strip().lower()
    return "unknown"


def unmanage(iface: str, res: ResourceSet) -> None:
    """Отвязываем интерфейс от NetworkManager, чтобы он не дёргал канал."""
    nmcli = require("nmcli")
    res.add("вернуть интерфейс под NetworkManager", lambda: run([nmcli, "device", "set", iface, "managed", "yes"], timeout=NMCLI_TIMEOUT))
    run([nmcli, "device", "set", iface, "managed", "no"], timeout=NMCLI_TIMEOUT)


def down(iface: str) -> None:
    run([_ip(), "link", "set", iface, "down"], timeout=10, check=True)


def up(iface: str) -> None:
    run([_ip(), "link", "set", iface, "up"], timeout=10, check=True)


def to_monitor(iface: str, res: ResourceSet) -> str:
    """Переводит интерфейс в monitor. Возвращает имя интерфейса для работы.

    Современные драйверы (mt76, rtw88/89, ath9k_htc) умеют in-place смену типа:
    отдельный `mon0` через airmon-ng не нужен и только путает имена.
    """
    original_type = type_of(iface)
    unmanage(iface, res)

    def restore() -> None:
        down(iface)
        run([require("iw"), "dev", iface, "set", "type", original_type if original_type != "monitor" else "managed"], timeout=10)
        up(iface)

    res.add(f"вернуть {iface} в {original_type}", restore)
    down(iface)
    set_type = run([require("iw"), "dev", iface, "set", "type", "monitor"], timeout=10)
    if not set_type.ok:
        raise WilfiError(f"не удалось включить monitor на {iface}", detail=set_type.err.strip())
    up(iface)
    if not wait_until(lambda: type_of(iface) == "monitor", 5):
        raise WilfiError(f"{iface} не перешёл в monitor", detail="проверьте драйвер и rfkill")
    return iface


def to_managed(iface: str) -> None:
    down(iface)
    run([require("iw"), "dev", iface, "set", "type", "managed"], timeout=10, check=True)
    up(iface)


def set_channel(iface: str, channel: int, band: str = "2.4") -> None:
    freq = channel_to_freq(channel, band)
    res = run([require("iw"), "dev", iface, "set", "channel", str(freq)], timeout=10)
    if not res.ok:
        raise WilfiError(f"канал {channel} не переключился", detail=res.err.strip())


def channel_to_freq(channel: int, band: str = "2.4") -> int:
    if band == "5":
        return 5000 + channel * 5
    if channel == 14:
        return 2484
    return 2407 + channel * 5


def freq_to_channel(freq: int) -> int:
    if freq == 2484:
        return 14
    if 2400 <= freq < 2500:
        return (freq - 2407) // 5
    if freq >= 5000:
        return (freq - 5000) // 5
    return 0


def restart_network_manager() -> None:
    run([require("systemctl"), "restart", "NetworkManager"], timeout=30, check=False)


def set_mac(iface: str, mac: str, res: ResourceSet) -> None:
    ip = _ip()
    old = run([ip, "link", "show", iface], timeout=10).out
    res.add(f"вернуть MAC {iface}", lambda: run([ip, "link", "set", iface, "address", _extract_mac(old)], timeout=10))
    down(iface)
    run([ip, "link", "set", iface, "address", mac], timeout=10, check=True)
    up(iface)


def _extract_mac(ip_link: str) -> str:
    for token in ip_link.replace("\n", " ").split():
        if token.count(":") == 5 and len(token) == 17:
            return token
    return "00:00:00:00:00:00"


def random_mac() -> str:
    import random

    return "02:%02x:%02x:%02x:%02x:%02x" % tuple(random.randrange(256) for _ in range(5))
