# wifikit — архитектура

Linux-инструмент аудита Wi-Fi (Ubuntu/Debian first-class, любой дистрибутив — через install.sh).
Три функции: захват рукопожатия/PMKID, оффлайн-крошилка, злой двойник с порталом.

## 1. Разделение привилегий

Всё, что требует root (iw, ip, hostapd, dnsmasq, nft, hcxdumptool, aireplay-ng, hashcat),
живёт в демоне `daemon/main.py`, запускаемом через `pkexec`. GUI (`app/main.py`) — без рута.

Демон слушает `AF_UNIX` `$XDG_RUNTIME_DIR/wifikit.sock` (fallback `/run/user/$UID`), режим 0600,
JSON-RPC построчно: `{"id","method","params"}` → `{"id","ok","data"|"error"}`.
Демон — единственный, кто знает про shell; ни одна строка команд не собирается в GUI.

Демон держит **реестр ресурсов**: что поднято, чей это ресурс, как откатить. `shutdown` и
`SIGTERM`/`SIGINT` вызывают полный `rollback()`: остановка hostapd/dnsmasq, снятие nft-таблицы,
`ip link set down`, возврат интерфейсов из monitor в managed, `nmcli device set managed yes`,
рестарт NetworkManager, если его глушили. Незавершённый откат повторяется при старте демона
(журнал `~/.local/state/wifikit/pending_rollback.json`).

## 2. Роли адаптеров

Два интерфейса, роли не пересекаются: `probe` (monitor + инъекция) и `ap` (managed → AP).
Один и тот же интерфейс на обе роли — запрещено (кроме «AP-режим одним адаптером» в
одноадаптерном degraded-сценарии). Роль выбирается явно, capability проверяется:
`iw phyX info` → `* monitor`, `* AP`, `aireplay-ng --test` → инъекция.

## 3. Модули (core/)

| модуль | назначение | внешние бины |
|---|---|---|
| diagnose | версии, чипы, драйверы, конфликты, тест инъекции | iw, lsusb, aireplay-ng |
| scan | скан каналов, RSN IE → WPA/WPA3/PMF бейджи | iw / aireplay, airodump |
| capture | 4-way из эфира, авто-стоп по захвату | hcxdumptool |
| pmkid | clientless PMKID | hcxdumptool |
| convert | pcapng → .hc22000 + `hcxhashtool --info` разбор | hcxpcapngtool, hcxhashtool |
| deauth | деаут burst/выборочно | aireplay-ng |
| ap | фейк-AP с клоном BSSID/SSID, DHCP, DNS-перехват | hostapd, dnsmasq, nft |
| portal | HTTP-портал, шаблоны, сбор полей | stdlib http.server |
| verify | проверка кандидата | hcxpmktool, wpa_supplicant |
| crack | словарь/правила/маска, прогресс | hashcat |
| report | md/html отчёт | — |

Каждый модуль — класс с `start() / status() / stop()` и своим `ResourceSet` для отката.

## 4. Ограничения, зашитые в UI

- WPA3-only: захват есть, крошилки нет (в hashcat нет SAE-модуля) — бейдж «не крошится».
- PMF required: деаут не сработает — предупреждение до старта.
- Крошилка в VM — только CPU; баннер предлагает экспорт хэша на хост.
- Драйверы без monitor/AP — точка в списке адаптеров помечена «непригоден», выбрать нельзя.

## 5. Безопасность

Никаких сетевых слушателей на внешних интерфейсах без флага. Портал — только на AP-интерфейсе.
Пароли в JSON-RPC не логируются, в состоянии проекта пишутся в файл с 0600.

## 6. Тесты

`tests/unit` — парсеры вывода (airodump, iw scan, hcxhashtool --info, hashcat --status-json),
рендер шаблонов, откат ресурсов, JSON-RPC. Фикстуры в `tests/fixtures` — реальные срезы вывода.
E2E требует железа и в CI не гоняется.
