"""Главное окно wifikit."""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QFont
from PySide6.QtWidgets import (QApplication, QComboBox, QFileDialog, QFrame, QHBoxLayout,
                               QInputDialog, QLabel, QMainWindow, QPushButton,
                               QSplitter, QStackedWidget, QVBoxLayout, QWidget)

from app import i18n
from app.banner import Banner
from app.pages import PAGES, CapturePage, EvilPage, LogPage, ScanPage, State
from app.remote import Remote, Task
from app.safe import expect_dict, install_hooks, safe_callback, safe_slot
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
        self._initialized = False
        self.lang = "ru"
        self.setWindowTitle("wifikit")
        self.resize(1180, 760)
        self._build()
        self._connect()
        self.timer = QTimer(self)
        self.timer.timeout.connect(self._tick)
        self.timer.start(1800)
        self.retry_timer = QTimer(self)
        self.retry_timer.setInterval(20000)
        self.retry_timer.setSingleShot(True)
        self.retry_timer.timeout.connect(self._retry_connect)

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

        self.banner = Banner()
        banner_wrap = QHBoxLayout()
        banner_wrap.setContentsMargins(16, 8, 16, 0)
        banner_wrap.addWidget(self.banner)
        outer.addLayout(banner_wrap)

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
        self._show("scan")

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

    @safe_slot
    def _conn_failed(self, message: str, detail: str) -> None:
        self._log(f"{message}: {detail}")
        self.lbl_project.setText("демон: нет связи")
        self._set_offline(True)
        self.notify_error(
            "Демон не подключён — интерфейс работает, команды недоступны",
            detail,
            subtitle="Введите пароль в запросе polkit. Если окна не было — запустите: sudo /usr/lib/wifikit/daemon.py",
            action=("Подключиться заново", self._retry_connect),
        )
        # одна автоматическая попытка переподключения, чтобы не дёргать пользователя
        if not self.retry_timer.isActive():
            self.retry_timer.start()

    def _set_offline(self, offline: bool) -> None:
        """Пока демона нет — кнопки действий выключены, чтобы не врать пользователю."""
        page = self.pages.get("scan")
        button = getattr(page, "btn", None)
        if button is not None:
            button.setEnabled(not offline)

    def _retry_connect(self) -> None:
        if self.remote.is_connected():
            return
        self._log("повторная попытка подключиться к демону…")
        self._connect()

    @safe_slot
    def _after_connect(self) -> None:
        self._log("связь есть")
        self.banner.hide_banner()
        self.lbl_project.setText("демон подключён")
        self._set_offline(False)
        self._load_adapters()
        self.call("deps_check", self._deps_ready)

    @safe_slot
    def _deps_ready(self, data: dict) -> None:
        data = expect_dict(self, "deps_check", data)
        if data is None:
            return
        missing = data.get("missing") or []
        if not missing:
            return
        lines = [f"{d['binary']}\t{d.get('version') or ''}\t{d.get('note') or ''}"
                 for d in data.get("deps", []) if not d.get("ok")]
        self.notify_error(
            f"Не хватает {len(missing)} инструмент(ов): {', '.join(missing)}",
            "\n".join(lines),
            kind="warn",
            subtitle="Часть функций будет недоступна. Установить: sudo packaging/install.sh",
        )

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
            def _apply(data) -> None:
                if isinstance(data, dict):
                    holder[name] = data
                if len(holder) == 2:
                    evil.update_status(holder.get("ap", {}), holder.get("portal", {}))
            return safe_callback(self, f"tick:{name}", _apply)

        tasks[0].done.connect(collect("ap"))
        tasks[1].done.connect(collect("portal"))
        for task in tasks:
            task.start()
        for key in ("capture", "crack"):
            page = self.pages.get(key)
            if page and self.stack.currentWidget() is page:
                page.refresh()  # type: ignore[attr-defined]

    @safe_slot
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

    @safe_slot
    def _fill_adapters(self, data: dict) -> None:
        data = expect_dict(self, "adapters_list", data)
        if data is None:
            return
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

    @safe_slot
    def _project_ready(self, data: dict) -> None:
        data = expect_dict(self, "project", data)
        if data is None:
            return
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
    @safe_slot
    def _toggle_lang(self) -> None:
        self.lang = "en" if self.lang == "ru" else "ru"
        i18n.set_lang(self.lang)
        self.btn_lang.setText("ru" if self.lang == "en" else "en")
        self._log("язык переключён — перезапустите, чтобы применить ко всем надписям")

    def notify_error(self, message: str, detail: str = "", kind: str = "error",
                     subtitle: str = "", action=None) -> None:
        self.banner.notify(message, detail, kind=kind, subtitle=subtitle, action=action)

    def show_error(self, message: str, detail: str = "") -> None:
        self.notify_error(message, detail)

    def _log(self, line: str) -> None:
        if hasattr(self, "logbox"):
            self.logbox.append(line)

    def closeEvent(self, event) -> None:  # noqa: N802
        if self.remote.is_connected():
            self._log("останавливаю демон…")
            self.remote.shutdown()
        event.accept()


def main() -> int:
    install_hooks()
    i18n.set_lang("ru")
    app = QApplication(sys.argv)
    app.setApplicationName("wifikit")
    font = QFont()
    font.setFamilies(["Inter", "Noto Sans", "DejaVu Sans"])
    font.setPointSize(10)
    app.setFont(font)
    app.setStyleSheet(QSS)
    window = MainWindow()
    window.show()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
