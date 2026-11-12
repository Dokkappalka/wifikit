"""Оффскрин-прогон GUI: строит окно, проходит по страницам, снимает PNG.

Нужен для проверки вёрстки без дисплея (CI и macOS-разработка).
"""

import os
import subprocess
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication  # noqa: E402

from app.main import MainWindow  # noqa: E402

OUT = ROOT / "docs" / "screens"


def main() -> int:
    tmp = tempfile.mkdtemp(prefix="wifikit-ui-")
    os.environ["XDG_RUNTIME_DIR"] = tmp
    daemon = subprocess.Popen(
        [sys.executable, str(ROOT / "daemon" / "main.py")],
        env={**os.environ, "WIFIKIT_ALLOW_NONROOT": "1", "WIFIKIT_STATE_DIR": tmp,
             "WIFIKIT_PROJECTS_DIR": f"{tmp}/projects"},
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
    )
    time.sleep(2.0)
    # демон уже поднят этим скриптом: не просим GUI спавнить его через pkexec
    os.environ["WIFIKIT_SKIP_SPAWN"] = "1"
    app = QApplication(sys.argv)
    from app.theme import QSS

    app.setStyleSheet(QSS)
    window = MainWindow()
    window.resize(1180, 760)
    window.show()
    OUT.mkdir(parents=True, exist_ok=True)
    problems = []
    try:
        for _ in range(30):
            app.processEvents()
            time.sleep(0.05)
        # демон поднят этим же скриптом: интерфейс обязан быть в «связь есть»,
        # без красной панели и с активным сканом
        window._tick()
        for _ in range(20):
            app.processEvents()
            time.sleep(0.05)
        if not window._initialized:
            problems.append("GUI не выполнил инициализацию после подключения")
        if not window.pages["scan"].btn.isEnabled():
            problems.append("«Сканировать» выключена при живом демоне")
        print(f"связь: initialized={window._initialized}, "
              f"scan_enabled={window.pages['scan'].btn.isEnabled()}")

        for name in ("scan", "capture", "crack", "evil", "log"):
            window._show(name)
            if name == "crack":
                page = window.pages["crack"]
                page.attack.setCurrentIndex(page.attack.findData("positions"))
                page.positions.positions()
            for _ in range(16):
                app.processEvents()
                time.sleep(0.05)
            pix = window.grab()
            path = OUT / f"{name}.png"
            if not pix.save(str(path)):
                problems.append(f"не сохранился {path}")
            print(f"{name}: {pix.width()}x{pix.height()} -> {path}")
        print(f"страниц обойдено: {len(window.pages)}")
    finally:
        window.close()
        daemon.terminate()
    if problems:
        print("ПРОБЛЕМЫ:", problems)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
