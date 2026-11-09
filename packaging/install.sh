#!/usr/bin/env bash
# Установка на любой дистрибутив: ставит зависимости своим менеджером, копирует файлы.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
PREFIX="${PREFIX:-/usr/lib/wifikit}"
PY="$(command -v python3)"

say() { printf '\033[1m%s\033[0m\n' "$*"; }

if [ "$(id -u)" -ne 0 ]; then
  echo "нужен root: sudo $0"; exit 1
fi

say "1/5 зависимости"
if command -v apt-get >/dev/null; then
  apt-get update -qq
  apt-get install -y --no-install-recommends \
    python3 python3-pip python3-venv python3-yaml python3-psutil \
    aircrack-ng hostapd dnsmasq nftables iw iproute2 network-manager rfkill \
    policykit-1 hashcat hcxtools usbutils gcc make libpcap-dev git \
    libqt6svg6 || true
  # PySide6: пакет есть в новых релизах, иначе venv
  apt-get install -y --no-install-recommends python3-pyside6.qtwidgets || true
elif command -v pacman >/dev/null; then
  pacman -Sy --needed --noconfirm aircrack-ng hostapd dnsmasq nftables iw iproute2 \
    networkmanager rfkill polkit hashcat hcxtools usbutils gcc make libpcap git python-pyside6 python-yaml python-psutil
elif command -v dnf >/dev/null; then
  dnf install -y aircrack-ng hostapd dnsmasq nftables iw iproute NetworkManager rfkill \
    polkit hashcat hcxtools usbutils gcc make libpcap-devel git python3-pyside6 python3-pyyaml python3-psutil
else
  say "неизвестный пакетный менеджер — поставьте зависимости вручную (см. README)"
fi

say "2/5 PySide6"
if ! "$PY" -c "import PySide6" 2>/dev/null; then
  echo "PySide6 нет в системе — ставлю в изолированное окружение"
  install -d "$PREFIX"
  "$PY" -m venv "$PREFIX/venv"
  "$PREFIX/venv/bin/pip" -q install --upgrade pip
  "$PREFIX/venv/bin/pip" -q install PySide6 pyyaml psutil
  PY="$PREFIX/venv/bin/python"
fi

say "3/5 hcxdumptool >= 7"
need_build=0
if ! command -v hcxdumptool >/dev/null; then
  need_build=1
else
  major=$(hcxdumptool -v 2>/dev/null | head -1 | grep -o '[0-9]\+' | head -1)
  [ -n "${major:-}" ] && [ "$major" -lt 7 ] && need_build=1
fi
if [ "$need_build" -eq 1 ]; then
  tmp=$(mktemp -d)
  git clone --depth=1 https://github.com/ZerBea/hcxdumptool "$tmp/hcxdumptool"
  make -C "$tmp/hcxdumptool" -j"$(nproc)" install
  rm -rf "$tmp"
fi

say "4/5 файлы"
install -d "$PREFIX" /usr/share/applications /usr/share/polkit-1/actions
cp -r "$ROOT/app" "$ROOT/core" "$ROOT/daemon" "$ROOT/portals" "$PREFIX/"
install -m 0755 "$ROOT/daemon/main.py" "$PREFIX/daemon.py"
sed -e "s|@PY@|$PY|g" -e "s|@PREFIX@|$PREFIX|g" "$ROOT/packaging/wifikit" > /usr/bin/wifikit
chmod 0755 /usr/bin/wifikit
install -m 0644 "$ROOT/packaging/wifikit.desktop" /usr/share/applications/wifikit.desktop
install -m 0644 "$ROOT/packaging/io.github.wifikit.policy" /usr/share/polkit-1/actions/

say "5/5 проверка"
"$PY" -c "import PySide6, yaml, psutil; print('python-зависимости на месте')"
echo
say "готово. Запуск: wifikit"
