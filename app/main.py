"""Главное окно wifikit."""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import (QApplication, QComboBox, QFileDialog, QFrame, QHBoxLayout,
                               QInputDialog, QLabel, QMainWindow, QMessageBox, QPushButton,
                               QScrollArea, QSplitter, QStackedWidget, QVBoxLayout, QWidget)

from app import i18n
from app.pages import PAGES, CapturePage, EvilPage, LogPage, ScanPage, State
from app.remote import Remote, Task
from app.theme import QSS

VERSION = "0.1.0"


class MainWindow(QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self.remote = Remote()
        self._safe_connect(self.remote.log, self._log)
        self._safe_connect(self.remote.failed, self._conn_failed)
        self.state = State()
        self.pages: dict[str, QWidget] = {}
        self.lang = "ru"
        self.setWindowTitle("wifikit")
        self.resize(1180, 760)
        self._build()
        self._connect()
        self.timer = QTimer(self)
        self.timer.timeout.connect(self._tick)
        self.timer.start(1800)

    # ------------------------------------------------------------------ layout
    def _build(self) -> None:
        root = QWidget()
        outer = QVBoxLayout(root)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        top = QFrame()
        top.setFixedHeight(52)
        top.setStyleSheet("background:#151821;border-bottom:1px solid #242a36")
        bar = QHBoxLayout(top)
        bar.setContentsMargins(16, 8, 16, 8)
        project_box = QVBoxLayout()
        project_box.setSpacing(0)
        self.lbl_project = QLabel(i18n.t("project.none"))
        self.lbl_project.setStyleSheet("font-weight:600")
        project_box.addWidget(self.lbl_project)
        self.lbl_target = QLabel("")
        self.lbl_target.setObjectName("muted")
        project_box.addWidget(self.lbl_target)
        bar.addLayout(project_box)
        bar.addStretch(1)

        bar.addWidget(QLabel(i18n.t("adapters.probe")))
        self.combo_probe = QComboBox()
        self.combo_probe.setMinimumWidth(180)
        self.combo_probe.currentIndexChanged.connect(lambda: self._assign("probe"))
        bar.addWidget(self.combo_probe)
        bar.addWidget(QLabel(i18n.t("adapters.ap")))
        self.combo_ap = QComboBox()
        self.combo_ap.setMinimumWidth(180)
        self.combo_ap.currentIndexChanged.connect(lambda: self._assign("ap"))
        bar.addWidget(self.combo_ap)
        self.btn_refresh = QPushButton(i18n.t("adapters.recheck"))
        self.btn_refresh.clicked.connect(self._load_adapters)
        bar.addWidget(self.btn_refresh)
        self.btn_lang = QPushButton("en")
        self.btn_lang.setFixedWidth(42)
        self.btn_lang.clicked.connect(self._toggle_lang)
        bar.addWidget(self.btn_lang)
        outer.addWidget(top)

        body = QHBoxLayout()
        body.setContentsMargins(0, 0, 0, 0)
        body.setSpacing(0)

        side = QFrame()
        side.setObjectName("sidebar")
        side.setFixedWidth(196)
        side_lay = QVBoxLayout(side)
        side_lay.setContentsMargins(0, 12, 0, 12)
        side_lay.setSpacing(2)
        brand = QLabel("wifikit")
        brand.setObjectName("brand")
        brand.setContentsMargins(14, 0, 0, 0)
        side_lay.addWidget(brand)
        sub = QLabel(i18n.t("app.subtitle") + f" · {VERSION}")
        sub.setObjectName("muted")
        sub.setContentsMargins(14, 0, 0, 10)
        side_lay.addWidget(sub)

        self.nav_buttons: dict[str, QPushButton] = {}
        for key, (_, title) in PAGES.items():
            btn = QPushButton(title)
            btn.setObjectName("nav")
            btn.setCheckable(True)
            btn.clicked.connect(lambda _=False, k=key: self._show(k))
            side_lay.addWidget(btn)
            self.nav_buttons[key] = btn
        side_lay.addStretch(1)
        bottom = QVBoxLayout()
        bottom.setContentsMargins(10, 0, 10, 0)
        bottom.setSpacing(6)
        self.btn_new = QPushButton(i18n.t("project.new"))
        self.btn_new.clicked.connect(self._new_project)
        self.btn_open = QPushButton(i18n.t("project.open"))
        self.btn_open.clicked.connect(self._open_project)
        self.btn_report = QPushButton(i18n.t("project.export"))
        self.btn_report.clicked.connect(self._report)
        for b in (self.btn_new, self.btn_open, self.btn_report):
            bottom.addWidget(b)
        side_lay.addLayout(bottom)
        body.addWidget(side)

        split = QSplitter(Qt.Vertical)
        self.stack = QStackedWidget()
        for key, (cls, _) in PAGES.items():
            page = cls(self.remote, self.state)
            self.pages[key] = page
            self.stack.addWidget(page)
        split.addWidget(self.stack)
        self.logbox = LogPage(self.remote, self.state)
        split.addWidget(self.logbox)
        split.setSizes([620, 120])
        body.addWidget(split, 1)
        outer.addLayout(body, 1)

        self.setCentralWidget(root)
        self.pages["scan"].target_changed.connect(self._on_target)  # type: ignore[attr-defined]
        self._show("diag")

    # ------------------------------------------------------------------- conn
    @staticmethod
    def _safe_connect(signal, slot) -> None:
        """Подключение сигнала, которое не валит приложение на экзотических сборках Qt."""
        try:
            signal.connect(slot)
        except TypeError:
            # запасной путь: Qt-стиль, если PySide6 не принял короткую форму
            signal.connect(slot, Qt.AutoConnection)

    def _connect(self) -> None:
        self._log(f"wifikit {VERSION} · подключаюсь к демону (pkexec спросит пароль)…")
        import threading

        threading.Thread(target=self.remote.open_link, daemon=True).start()

    def _conn_failed(self, message: str, detail: str) -> None:
        self._log(f"{message}: {detail}")
        self.lbl_project.setText(message)

    def _after_connect(self) -> None:
        self._log("связь есть")
        self._load_adapters()
        self.pages["diag"].refresh()  # type: ignore[attr-defined]

    # ------------------------------------------------------------------ pages
    def _show(self, key: str) -> None:
        for name, btn in self.nav_buttons.items():
            btn.setChecked(name == key)
        self.stack.setCurrentWidget(self.pages[key])
        page = self.pages[key]
        if isinstance(page, (CapturePage, EvilPage)):
            page.refresh()
        elif hasattr(page, "refresh"):
            page.refresh()

    def _tick(self) -> None:
        if not self.remote.is_connected():
            return
        evil: EvilPage = self.pages["evil"]  # type: ignore[assignment]
        tasks = [Task(self.remote, "ap_status"), Task(self.remote, "portal_status")]
        holder: dict[str, dict] = {}

        def collect(name: str):
            def _apply(data: dict) -> None:
                holder[name] = data
                if len(holder) == 2:
                    evil.update_status(holder.get("ap", {}), holder.get("portal", {}))
            return _apply

        tasks[0].done.connect(collect("ap"))
        tasks[1].done.connect(collect("portal"))
        for task in tasks:
            task.start()
        for key in ("capture", "crack"):
            page = self.pages.get(key)
            if page and self.stack.currentWidget() is page:
                page.refresh()  # type: ignore[attr-defined]

    def _on_target(self, ap: dict) -> None:
        self.state.target = ap
        self.lbl_target.setText(f"{ap['ssid'] or ap['bssid']} · {ap['bssid']}")
        capture: CapturePage = self.pages["capture"]  # type: ignore[assignment]
        capture.on_target(ap)
        evil: EvilPage = self.pages["evil"]  # type: ignore[assignment]
        evil.on_target(ap)

    # --------------------------------------------------------------- adapters
    def _load_adapters(self) -> None:
        task = Task(self.remote, "adapters_list")
        task.done.connect(self._fill_adapters)
        task.failed.connect(lambda m, d: self._log(f"{m}: {d}"))
        task.start()

    def _fill_adapters(self, data: dict) -> None:
        for combo, role in ((self.combo_probe, "probe"), (self.combo_ap, "ap")):
            combo.blockSignals(True)
            combo.clear()
            combo.addItem(i18n.t("adapters.none"), "")
            for adapter in data["adapters"]:
                usable = adapter["suitable_probe"] if role == "probe" else adapter["suitable_ap"]
                label = f"{adapter['iface']} · {adapter['driver'] or '?'}"
                if not usable:
                    label += f" ({i18n.t('adapters.unsuitable')})"
                combo.addItem(label, adapter["iface"])
                if not usable:
                    index = combo.count() - 1
                    combo.model().item(index).setEnabled(False)
            current = data.get(f"{role}_iface")
            if current:
                idx = combo.findData(current)
                if idx >= 0:
                    combo.setCurrentIndex(idx)
            combo.blockSignals(False)
        if not data["adapters"]:
            self._log("Wi-Fi адаптеров не найдено — подключите USB-адаптер и нажмите «Обновить»")

    def _assign(self, role: str) -> None:
        combo = self.combo_probe if role == "probe" else self.combo_ap
        iface = combo.currentData()
        task = Task(self.remote, "adapters_assign", role=role, iface=iface or "")
        task.failed.connect(lambda m, d: self.show_error(m, d))
        task.start()

    # --------------------------------------------------------------- project
    def _new_project(self) -> None:
        name, ok = QInputDialog.getText(self, i18n.t("project.new"), i18n.t("project.name"))
        if not ok or not name.strip():
            return
        task = Task(self.remote, "project_new", name=name.strip())
        task.done.connect(self._project_ready)
        task.failed.connect(lambda m, d: self.show_error(m, d))
        task.start()

    def _open_project(self) -> None:
        base = Path.home() / "wifikit-projects"
        path = QFileDialog.getExistingDirectory(self, i18n.t("project.open"), str(base))
        if not path:
            return
        task = Task(self.remote, "project_open", path=path)
        task.done.connect(self._project_ready)
        task.failed.connect(lambda m, d: self.show_error(m, d))
        task.start()

    def _project_ready(self, data: dict) -> None:
        self.lbl_project.setText(data.get("name") or "")
        target = data.get("target") or {}
        self.lbl_target.setText(target.get("ssid") or "")
        self._load_adapters()
        self._log(f"проект: {data.get('path')}")

    def _report(self) -> None:
        task = Task(self.remote, "report_export", fmt="md")
        task.done.connect(lambda d: self._log(f"отчёт: {d['path']}"))
        task.failed.connect(lambda m, d: self.show_error(m, d))
        task.start()

    # ------------------------------------------------------------------- misc
    def _toggle_lang(self) -> None:
        self.lang = "en" if self.lang == "ru" else "ru"
        i18n.set_lang(self.lang)
        self.btn_lang.setText("ru" if self.lang == "en" else "en")
        self._log("язык переключён — перезапустите, чтобы применить ко всем надписям")

    def show_error(self, message: str, detail: str = "") -> None:
        box = QMessageBox(self)
        box.setIcon(QMessageBox.Warning)
        box.setWindowTitle(i18n.t("err.title"))
        box.setText(message)
        if detail:
            box.setDetailedText(detail)
        box.setAttribute(Qt.WA_DeleteOnClose)
        box.open()

    def _log(self, line: str) -> None:
        if hasattr(self, "logbox"):
            self.logbox.append(line)

    def closeEvent(self, event) -> None:  # noqa: N802
        if self.remote.is_connected():
            self._log("останавливаю демон…")
            self.remote.shutdown()
        event.accept()


def main() -> int:
    i18n.set_lang("ru")
    app = QApplication(sys.argv)
    app.setApplicationName("wifikit")
    app.setStyleSheet(QSS)
    window = MainWindow()
    window.show()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
