#!/usr/bin/env bash
# Сборка .deb. Запуск: packaging/deb/build.sh [версия]
set -euo pipefail

VERSION="${1:-0.1.0}"
ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
STAGE="$(mktemp -d)"
trap 'rm -rf "$STAGE"' EXIT

APP="$STAGE/usr/lib/wifikit"
install -d "$APP" "$STAGE/usr/bin" "$STAGE/usr/share/applications" "$STAGE/usr/share/polkit-1/actions"
install -d "$STAGE/DEBIAN"

cp -r "$ROOT/app" "$ROOT/core" "$ROOT/daemon" "$ROOT/portals" "$APP/"
install -m 0755 "$ROOT/daemon/main.py" "$APP/daemon.py"
install -m 0755 "$ROOT/packaging/wifikit" "$STAGE/usr/bin/wifikit"
install -m 0644 "$ROOT/packaging/wifikit.desktop" "$STAGE/usr/share/applications/wifikit.desktop"
install -m 0644 "$ROOT/packaging/io.github.wifikit.policy" "$STAGE/usr/share/polkit-1/actions/"

find "$STAGE/usr" -name '__pycache__' -type d -prune -exec rm -rf {} +

cat > "$STAGE/DEBIAN/control" <<CONTROL
Package: wifikit
Version: $VERSION
Section: net
Priority: optional
Architecture: all
Maintainer: fedya <fedya@localhost>
Depends: python3 (>=3.11), python3-yaml, python3-psutil,
 aircrack-ng, hostapd, dnsmasq, nftables, iw, iproute2, network-manager, rfkill,
 policykit-1, hashcat, hcxtools, usbutils,
 libxcb-cursor0, libxcb-icccm4, libxkbcommon-x11-0, libegl1, libgl1, libqt6svg6
Recommends: hcxdumptool (>= 7.0.0)
Description: Аудит Wi-Fi: захват рукопожатий, крошилка, злой двойник
 GUI-инструмент для Linux: захват 4-way и PMKID, оффлайн-брутфорс через hashcat,
 фейк-точка с порталом-ловушкой и загрузкой своих HTML-форм.
CONTROL

cat > "$STAGE/DEBIAN/postinst" <<'POST'
#!/bin/sh
set -e
if [ "$(command -v hcxdumptool)" ]; then
  v=$(hcxdumptool -v 2>/dev/null | head -1 | grep -o '[0-9]\+\.[0-9]\+\.[0-9]\+' | head -1)
  major=${v%%.*}
  if [ -n "$major" ] && [ "$major" -lt 7 ]; then
    echo "wifikit: установлен hcxdumptool $v, нужен 7.x — сборка из исходников:"
    echo "  sudo wifikit-install-hcxdumptool   (или см. README, раздел «Зависимости»)"
  fi
fi
POST
chmod 0755 "$STAGE/DEBIAN/postinst"

dpkg-deb --root-owner-group -Zxz --build "$STAGE" "$ROOT/dist/wifikit_${VERSION}_all.deb" >/dev/null
echo "готово: $ROOT/dist/wifikit_${VERSION}_all.deb"
