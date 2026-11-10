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

# shellcheck disable=SC1091
distro="$(. /etc/os-release 2>/dev/null && echo "${PRETTY_NAME:-неизвестно}")"
say "0/5 окружение: $distro ($(uname -m))"
if [ -r /var/lib/dpkg/status ]; then
  free_mb=$(df -Pm /var 2>/dev/null | awk 'NR==2 {print $4}')
  if [ -n "${free_mb:-}" ] && [ "$free_mb" -lt 200 ]; then
    warn "на разделе /var свободно ${free_mb} МБ — apt с таким запасом работать не будет"
  fi
fi

say "1/5 системные пакеты"
for mount in /usr /tmp; do
  avail_mb=$(df -Pm "$mount" 2>/dev/null | awk 'NR==2 {print $4}')
  if [ -n "${avail_mb:-}" ] && [ "$avail_mb" -lt 1200 ]; then
    die "на $mount свободно ${avail_mb} МБ — нужно минимум 1200. Освободите место:
  sudo du -xh / --exclude=/proc --exclude=/sys | sort -h | tail -20
  sudo apt-get clean; sudo journalctl --vacuum-size=100M
Переполненный диск — главная причина обрезанных Qt-библиотек и падений с Bus error."
  fi
done
APT_CORE="python3 python3-venv python3-pip iw iproute2 network-manager rfkill
 aircrack-ng hostapd dnsmasq nftables hcxtools hashcat usbutils
 gcc make libpcap-dev git pkg-config"
# только системные xcb/EGL: Qt6 внутри PySide6 свой, системный libqt6* с ним конфликтует
APT_QT="libxcb-cursor0 libxcb-icccm4 libxcb-image0 libxcb-keysyms1 libxcb-randr0
 libxcb-render-util0 libxcb-shape0 libxcb-xinerama0 libxkbcommon-x11-0
 libegl1 libgl1"

apt_healthy() {
  # «Splitting up … into data and signature failed» = сломан apt или кончилось место,
  # и это не наша ошибка: без рабочих индексов ни hcxdumptool не собрать, ни Qt не поставить.
  local out
  out=$(apt-get update 2>&1)
  if echo "$out" | grep -q "Splitting up"; then
    warn "apt не может разобрать индексы репозиториев (это состояние гостевой системы, не установщика)"
    cat >&2 <<'APT_FIX'

Почините apt и запустите установщик снова:

  df -h /var; df -i /var          # место и inode — самая частая причина
  sudo rm -rf /var/lib/apt/lists/*
  sudo apt-get clean
  sudo dpkg --configure -a
  sudo apt-get -f install
  sudo apt-get update

Если «Splitting up» остался:
  sudo apt-get install --reinstall -y apt gpgv
  date -u                          # часы не должны убегать вперёд/назад

Обойти apt совсем (файлы поставятся, зависимости — нет):
  sudo WIFIKIT_SKIP_APT=1 packaging/install.sh

APT_FIX
    return 1
  fi
  echo "$out" | grep -qi "signature verification\|GPG error" && warn "часть репозиториев не проверяется по подписи — apt работает, но с оговоркой"
  return 0
}

APT_OK=1
if command -v apt-get >/dev/null; then
  if [ "${WIFIKIT_SKIP_APT:-0}" = "1" ]; then
    warn "WIFIKIT_SKIP_APT=1 — системные пакеты не трогаю"
    APT_OK=0
  elif ! apt_healthy; then
    die "сначала почините apt (команды выше), иначе hcxdumptool 7 и Qt поставить нечем"
  fi
  if [ "$APT_OK" = "1" ]; then
    # shellcheck disable=SC2086
    apt-get install -y -qq --no-install-recommends $APT_CORE || FAILED+=("часть базовых пакетов не установилась")
    # shellcheck disable=SC2086
    apt-get install -y -qq --no-install-recommends $APT_QT 2>/dev/null || warn "Qt-библиотеки xcb не встали — GUI может не запуститься"
    for polkit_pkg in policykit-1 pkexec; do
      if ! command -v pkexec >/dev/null; then
        apt-get install -y -qq --no-install-recommends "$polkit_pkg" >/dev/null 2>&1 || true
      fi
    done
    command -v pkexec >/dev/null || FAILED+=("нет pkexec — демон не сможет запросить права")
  fi
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
qt_smoke() {
  # настоящий запуск Qt без окна: ловит и битые .so, и отсутствующие xcb-плагины
  QT_QPA_PLATFORM=offscreen "$1" - >/tmp/wifikit-qt-smoke.log 2>&1 <<'PYEOF'
from PySide6.QtWidgets import QApplication, QLabel
app = QApplication([])
label = QLabel("ok")
label.resize(40, 16)
label.show()
print("qt-ok")
PYEOF
  rc=$?
  if grep -q "qt-ok" /tmp/wifikit-qt-smoke.log; then
    return 0
  fi
  echo "   Qt не запустился (код $rc): $(tail -2 /tmp/wifikit-qt-smoke.log | tr '\n' ' ')"
  return 1
}

install_pyside_venv() {
  local pin="$1"
  install -d "$PREFIX"
  [ -x "$PREFIX/venv/bin/python" ] || "$PY" -m venv "$PREFIX/venv" || return 1
  "$PREFIX/venv/bin/pip" -q install --upgrade pip
  if [ -n "$pin" ]; then
    "$PREFIX/venv/bin/pip" -q install --force-reinstall "PySide6==$pin" pyyaml psutil
  else
    "$PREFIX/venv/bin/pip" -q install --force-reinstall PySide6 pyyaml psutil
  fi
}

if [ "$QT_OK" -eq 0 ]; then
  say "   системного PySide6 нет — делаю изолированное окружение $PREFIX/venv"
  install_pyside_venv "" || die "pip не поставил PySide6 (нет сети или нет места?)"
  PY="$PREFIX/venv/bin/python"
  say "   GUI будет запускаться этим интерпретатором: $PY"
  if ! qt_smoke "$PY"; then
    warn "   Qt падает — переустанавливаю на проверенную ветку 6.8 (частый случай на 22.04)"
    if install_pyside_venv "6.8.3" && qt_smoke "$PY"; then
      say "   на 6.8.3 Qt работает"
    else
      FAILED+=("Qt не запускается даже на 6.8.3 — запустите wifikit-doctor и пришлите отчёт")
    fi
  else
    say "   проверка Qt: ок"
  fi
else
  say "   PySide6 найден в системном Python"
  "$PY" -m pip -q install pyyaml psutil 2>/dev/null \
    || apt-get install -y -qq --no-install-recommends python3-yaml python3-psutil >/dev/null 2>&1 || true
  qt_smoke "$PY" || FAILED+=("системный Qt не проходит пробный запуск — см. wifikit-doctor")
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
# pkexec делает execve по этому пути: без shebang и бита x получим «Exec format error»
if [ "$(head -c2 "$PREFIX/daemon.py")" != "#!" ]; then
  FAILED+=("$PREFIX/daemon.py без shebang — демон не запустится")
fi
if [ ! -x "$PREFIX/daemon.py" ]; then
  chmod 0755 "$PREFIX/daemon.py"
  FAILED+=("$PREFIX/daemon.py не был исполняемым — поправил права")
fi
find "$PREFIX" -name '__pycache__' -type d -prune -exec rm -rf {} + 2>/dev/null
sed -e "s|@PY@|$PY|g" -e "s|@PREFIX@|$PREFIX|g" "$ROOT/packaging/wifikit" > /usr/bin/wifikit
chmod 0755 /usr/bin/wifikit
install -m 0644 "$ROOT/packaging/wifikit.desktop" /usr/share/applications/wifikit.desktop
install -m 0644 "$ROOT/packaging/io.github.wifikit.policy" /usr/share/polkit-1/actions/
install -m 0755 "$ROOT/packaging/wifikit-doctor" /usr/bin/wifikit-doctor

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