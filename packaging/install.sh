#!/usr/bin/env bash
# Установка на любой дистрибутив. Запуск: sudo packaging/install.sh
#
# Порядок: обязательные системные пакеты и Qt-библиотеки (без них GUI падает с
# «could not load the Qt platform plugin xcb»), затем PySide6 (пакет дистрибутива,
# иначе venv), затем hcxdumptool >= 7 — в Ubuntu 24.04 в репозитории только 6.3.
set -uo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
PREFIX="${PREFIX:-/usr/lib/wifikit}"
PY="$(command -v python3)"
FAILED=()

say()  { printf '\033[1m%s\033[0m\n' "$*"; }
warn() { printf '\033[33m%s\033[0m\n' "$*"; }
die()  { printf '\033[31m%s\033[0m\n' "$*" >&2; exit 1; }

if [ "$(id -u)" -ne 0 ]; then
  die "нужен root: sudo $0"
fi

say "1/5 системные пакеты"
APT_CORE="python3 python3-venv python3-pip iw iproute2 network-manager rfkill
 aircrack-ng hostapd dnsmasq nftables hcxtools hashcat usbutils policykit-1
 gcc make libpcap-dev git pkg-config"
APT_QT="libxcb-cursor0 libxcb-icccm4 libxcb-image0 libxcb-keysyms1 libxcb-randr0
 libxcb-render-util0 libxcb-shape0 libxcb-xinerama0 libxkbcommon-x11-0
 libegl1 libgl1 libqt6svg6"

if command -v apt-get >/dev/null; then
  apt-get update -qq || warn "apt-get update не прошёл — ставлю из текущих индексов"
  # shellcheck disable=SC2086
  apt-get install -y -qq --no-install-recommends $APT_CORE || FAILED+=("часть базовых пакетов не установилась")
  # shellcheck disable=SC2086
  apt-get install -y -qq --no-install-recommends $APT_QT 2>/dev/null || warn "Qt-библиотеки xcb не встали — GUI может не запуститься"
elif command -v pacman >/dev/null; then
  pacman -Sy --needed --noconfirm aircrack-ng hostapd dnsmasq nftables iw iproute2 \
    networkmanager rfkill polkit hashcat hcxtools usbutils gcc make libpcap git python \
    xcb-util-cursor xcb-util-keysyms xcb-util-renderutil xcb-util-wm libxkbcommon-x11 \
    libglvnd || warn "часть пакетов не встала"
elif command -v dnf >/dev/null; then
  dnf install -y aircrack-ng hostapd dnsmasq nftables iw iproute NetworkManager rfkill \
    polkit hashcat hcxtools usbutils gcc make libpcap-devel git python3 python3-pip \
    xcb-util-cursor xcb-util-keysyms xcb-util-renderutil libxkbcommon-x11 || warn "часть пакетов не встала"
else
  warn "неизвестный пакетный менеджер — поставьте зависимости вручную (README)"
fi

say "2/5 PySide6 и питоновские зависимости"
QT_OK=0
"$PY" -c "import PySide6" >/dev/null 2>&1 && QT_OK=1
if [ "$QT_OK" -eq 0 ] && command -v apt-get >/dev/null; then
  # в 24.04 такого пакета нет вовсе — пробуем варианты имён молча
  for pkg in python3-pyside6.qtwidgets python3-pyside6 python3-qt6-qtwidgets; do
    apt-get install -y -qq --no-install-recommends "$pkg" >/dev/null 2>&1 || continue
    "$PY" -c "import PySide6" >/dev/null 2>&1 && { QT_OK=1; break; }
  done
fi
if [ "$QT_OK" -eq 0 ]; then
  say "   системного PySide6 нет — делаю изолированное окружение $PREFIX/venv"
  install -d "$PREFIX"
  "$PY" -m venv "$PREFIX/venv" || die "нет python3-venv: sudo apt install python3-venv"
  "$PREFIX/venv/bin/pip" -q install --upgrade pip
  "$PREFIX/venv/bin/pip" -q install PySide6 pyyaml psutil || die "pip не поставил PySide6 (нет сети?)"
  PY="$PREFIX/venv/bin/python"
  say "   GUI будет запускаться этим интерпретатором: $PY"
else
  say "   PySide6 найден в системном Python"
  "$PY" -m pip -q install pyyaml psutil 2>/dev/null \
    || apt-get install -y -qq --no-install-recommends python3-yaml python3-psutil >/dev/null 2>&1 || true
fi

say "3/5 hcxdumptool >= 7"
need_build=0
if ! command -v hcxdumptool >/dev/null; then
  need_build=1
else
  major=$(hcxdumptool -v 2>/dev/null | head -1 | grep -o '[0-9]\+' | head -1)
  if [ -n "${major:-}" ] && [ "$major" -lt 7 ]; then
    warn "   установлен hcxdumptool $major.x, а нужен 7.x (другой CLI) — собираю из исходников"
    need_build=1
  fi
fi
if [ "$need_build" -eq 1 ]; then
  tmp=$(mktemp -d)
  if git clone --depth=1 https://github.com/ZerBea/hcxdumptool "$tmp/hcxdumptool" 2>/dev/null; then
    if make -C "$tmp/hcxdumptool" -j"$(nproc)" install >/dev/null 2>&1; then
      say "   собрано: $(hcxdumptool -v 2>/dev/null | head -1)"
    else
      FAILED+=("hcxdumptool не собрался (нужны gcc и libpcap-dev)")
    fi
  else
    FAILED+=("hcxdumptool не скачался — нет сети?")
  fi
  rm -rf "$tmp"
fi

say "4/5 файлы"
install -d "$PREFIX" /usr/share/applications /usr/share/polkit-1/actions
rm -rf "$PREFIX/app" "$PREFIX/core" "$PREFIX/daemon" "$PREFIX/portals"
cp -r "$ROOT/app" "$ROOT/core" "$ROOT/daemon" "$ROOT/portals" "$PREFIX/"
install -m 0755 "$ROOT/daemon/main.py" "$PREFIX/daemon.py"
find "$PREFIX" -name '__pycache__' -type d -prune -exec rm -rf {} + 2>/dev/null
sed -e "s|@PY@|$PY|g" -e "s|@PREFIX@|$PREFIX|g" "$ROOT/packaging/wifikit" > /usr/bin/wifikit
chmod 0755 /usr/bin/wifikit
install -m 0644 "$ROOT/packaging/wifikit.desktop" /usr/share/applications/wifikit.desktop
install -m 0644 "$ROOT/packaging/io.github.wifikit.policy" /usr/share/polkit-1/actions/

say "5/5 проверка"
"$PY" -c "import PySide6.QtWidgets, yaml, psutil; print('   python:', '$PY')" || FAILED+=("python-зависимости")
"$PY" -c "import sys; sys.path.insert(0, '$PREFIX'); import core.scan, core.mask, daemon.session; print('   модули wifikit на месте')" \
  || FAILED+=("модули wifikit не импортируются")
for bin in iw ip nmcli hcxdumptool hcxpcapngtool aireplay-ng hostapd dnsmasq nft hashcat; do
  command -v "$bin" >/dev/null || FAILED+=("нет $bin")
done

echo
if [ ${#FAILED[@]} -gt 0 ]; then
  warn "установка завершена с замечаниями:"
  printf '  - %s\n' "${FAILED[@]}"
  warn "запускайте wifikit — мастер диагностики покажет, чего не хватает"
  exit 0
fi
say "готово. Запуск: wifikit"