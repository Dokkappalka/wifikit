"""Двуязычие. Ключи плоские, значения только строки; язык переключается на лету."""

from __future__ import annotations

LANG = "ru"

STRINGS: dict[str, dict[str, str]] = {
    "app.title": {"ru": "wifikit", "en": "wifikit"},
    "app.subtitle": {"ru": "аудит Wi-Fi", "en": "Wi-Fi audit"},
    "nav.scan": {"ru": "Точки", "en": "Access points"},
    "nav.capture": {"ru": "Захват", "en": "Capture"},
    "nav.crack": {"ru": "Крошилка", "en": "Cracker"},
    "nav.evil": {"ru": "Злой двойник", "en": "Evil twin"},
    "nav.log": {"ru": "Журнал", "en": "Log"},
    "nav.project": {"ru": "Проект", "en": "Project"},
    "project.none": {"ru": "проект не открыт", "en": "no project"},
    "project.new": {"ru": "Новый проект", "en": "New project"},
    "project.open": {"ru": "Открыть", "en": "Open"},
    "project.name": {"ru": "Название проекта", "en": "Project name"},
    "project.export": {"ru": "Отчёт", "en": "Report"},
    "adapters.probe": {"ru": "Сенсор", "en": "Sensor"},
    "adapters.ap": {"ru": "Фейк-точка", "en": "Fake AP"},
    "adapters.none": {"ru": "не выбран", "en": "none"},
    "adapters.recheck": {"ru": "Обновить", "en": "Refresh"},
    "adapters.test": {"ru": "Проверить инъекцию", "en": "Test injection"},
    "adapters.unsuitable": {"ru": "непригоден", "en": "unusable"},
    "scan.start": {"ru": "Сканировать", "en": "Scan"},
    "scan.stop": {"ru": "Стоп", "en": "Stop"},
    "scan.empty": {"ru": "нажмите «Сканировать»", "en": "press Scan"},
    "scan.col.ssid": {"ru": "SSID", "en": "SSID"},
    "scan.col.bssid": {"ru": "BSSID", "en": "BSSID"},
    "scan.col.ch": {"ru": "Кан", "en": "Ch"},
    "scan.col.rssi": {"ru": "Сигнал", "en": "Signal"},
    "scan.col.sec": {"ru": "Защита", "en": "Security"},
    "scan.col.hint": {"ru": "Чем брать", "en": "How"},
    "scan.hidden": {"ru": "<скрытая>", "en": "<hidden>"},
    "capture.start": {"ru": "Захватить", "en": "Capture"},
    "capture.pmkid_first": {"ru": "Сначала PMKID", "en": "PMKID first"},
    "capture.stop": {"ru": "Остановить захват", "en": "Stop capture"},
    "capture.deauth": {"ru": "Деаут при захвате", "en": "Deauth while capturing"},
    "capture.minutes": {"ru": "Лимит, мин", "en": "Timeout, min"},
    "capture.result": {"ru": "Результат", "en": "Result"},
    "capture.none": {"ru": "захват не запускался", "en": "no capture yet"},
    "capture.ok": {"ru": "хэш получен", "en": "hash captured"},
    "capture.fail": {"ru": "хэш не получен", "en": "no hash"},
    "capture.to_crack": {"ru": "В крошилку", "en": "To cracker"},
    "crack.attack": {"ru": "Атака", "en": "Attack"},
    "crack.wordlist": {"ru": "словарь", "en": "wordlist"},
    "crack.mask": {"ru": "маска", "en": "mask"},
    "crack.hybrid": {"ru": "словарь + маска", "en": "wordlist + mask"},
    "crack.rules": {"ru": "Правила", "en": "Rules"},
    "crack.mask_value": {"ru": "Маска", "en": "Mask"},
    "crack.start": {"ru": "Запустить", "en": "Start"},
    "crack.stop": {"ru": "Стоп", "en": "Stop"},
    "crack.found": {"ru": "Найдено", "en": "Found"},
    "crack.candidates": {"ru": "Вендорские кандидаты", "en": "Vendor candidates"},
    "crack.speed": {"ru": "Скорость", "en": "Speed"},
    "crack.no_hash": {"ru": "нет хэша — сначала захват", "en": "no hash — capture first"},
    "evil.need": {"ru": "нужны два разных адаптера", "en": "two distinct adapters required"},
    "evil.raise": {"ru": "Поднять точку", "en": "Raise AP"},
    "evil.drop": {"ru": "Погасить", "en": "Tear down"},
    "evil.template": {"ru": "Шаблон портала", "en": "Portal template"},
    "evil.upload": {"ru": "Загрузить свой HTML/ZIP", "en": "Upload own HTML/ZIP"},
    "evil.verify": {"ru": "Проверять пароль по хэшу", "en": "Verify password against hash"},
    "evil.clone": {"ru": "Клонировать BSSID", "en": "Clone BSSID"},
    "evil.clients": {"ru": "Клиенты", "en": "Clients"},
    "evil.submits": {"ru": "Вводы в портале", "en": "Portal submissions"},
    "evil.preview": {"ru": "Открыть портал", "en": "Open portal"},
    "log.clear": {"ru": "Очистить", "en": "Clear"},
    "btn.save": {"ru": "Сохранить", "en": "Save"},
    "btn.cancel": {"ru": "Отмена", "en": "Cancel"},
    "err.title": {"ru": "Ошибка", "en": "Error"},
    "ok.title": {"ru": "Готово", "en": "Done"},
    "warn.pmf": {"ru": "PMF обязателен — деаут не сработает", "en": "PMF required — deauth ignored"},
}


def set_lang(lang: str) -> None:
    global LANG
    LANG = lang if lang in ("ru", "en") else "ru"


def t(key: str, **fmt) -> str:
    entry = STRINGS.get(key)
    if not entry:
        return key
    text = entry.get(LANG) or entry.get("ru") or key
    return text.format(**fmt) if fmt else text
