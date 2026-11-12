"""Главное окно wifikit."""

from __future__ import annotations

import faulthandler
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QFont
from PySide6.QtWidgets import (QApplication, QComboBox, QFileDialog, QFrame, QHBoxLayout,
                               QLabel, QMainWindow, QPushButton, QStackedWidget, QStatusBar,
                               QVBoxLayout, QWidget)

from app import i18n
from app.dialogs import ErrorDialog, TextDialog
from app.pages import PAGES, CapturePage, EvilPage, LogPage, State
from app.remote import Remote, Task
from app.safe import (decide_safe_mode, expect_dict, gui_log_path, install_hooks, mark_clean,
                      mark_running, previous_crash, safe_callback, safe_slot)
from app.theme import QSS, dark_palette

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
        self._dialogs: list[QWidget] = []
        self.lang = "ru"
        self.setWindowTitle("wifikit")
        self.resize(1180, 780)
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
        root.setObjectName("root")
        outer = QVBoxLayout(root)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        top = QFrame()
        top.setObjectName("topbar")
        top.setFixedHeight(54)
        bar = QHBoxLayout(top)
        bar.setContentsMargins(16, 8, 16, 8)
        bar.setSpacing(10)

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
        self.combo_probe.setMinimumWidth(190)
        self.combo_probe.currentIndexChanged.connect(lambda: self._assign("probe"))
        bar.addWidget(self.combo_probe)

        bar.addWidget(QLabel(i18n.t("adapters.ap")))
        self.combo_ap = QComboBox()
        self.combo_ap.setMinimumWidth(190)
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
        for button in (self.btn_new, self.btn_open, self.btn_report):
            bottom.addWidget(button)
        side_lay.addLayout(bottom)
        body.addWidget(side)

        self.stack = QStackedWidget()
        for key, (cls, _) in PAGES.items():
            page = cls(self.remote, self.state)
            self.pages[key] = page
            self.stack.addWidget(page)
        self.logbox: LogPage = self.pages["log"]  # type: ignore[assignment]
        body.addWidget(self.stack, 1)
        outer.addLayout(body, 1)

        self.setCentralWidget(root)

        status = QStatusBar()
        status.setSizeGripEnabled(False)
        status.setFixedHeight(26)
        self.status_text = QLabel("")
        self.status_text.setObjectName("muted")
        status.addWidget(self.status_text, 1)
        self.setStatusBar(status)

        self.pages["scan"].target_changed.connect(self._on_target)  # type: ignore[attr-defined]
        self._show("scan")

    # ------------------------------------------------------------------- conn
    def call(self, method: str, on_done=None, on_fail=None, **params) -> Task:
        """То же, что Page.call: вызов демона с защищёнными колбэками."""
        task = Task(self.remote, method, **params)
        if on_done:
            task.done.connect(safe_callback(self, method, on_done))
        task.failed.connect(safe_callback(self, f"{method}:fail", on_fail or self.show_error))
        return task.start()

    @staticmethod
    def _safe_connect(signal, slot) -> None:
        try:
            signal.connect(slot)
        except TypeError:
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
            "Демон не подключён",
            detail,
            subtitle="Команды недоступны, пока демон не запущен. Пароль спрашивает polkit.",
            action=("Подключиться заново", self._retry_connect),
        )
        if not self.retry_timer.isActive():
            self.retry_timer.start()

    def _set_offline(self, offline: bool) -> None:
        for key in ("scan", "capture", "crack", "evil"):
            page = self.pages.get(key)
            for name in ("btn", "btn_start", "btn_up"):
                button = getattr(page, name, None)
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
        if missing:
            self._log("не хватает: " + ", ".join(missing))
            self.status_text.setText("не хватает инструментов: " + ", ".join(missing[:4]))

    # ------------------------------------------------------------------ pages
    def _show(self, key: str) -> None:
        for name, button in self.nav_buttons.items():
            button.setChecked(name == key)
        self.stack.setCurrentWidget(self.pages[key])
        page = self.pages[key]
        refresh = getattr(page, "refresh", None)
        if callable(refresh):
            refresh()

    @safe_slot
    def _tick(self) -> None:
        if not self.remote.is_connected():
            return
        if not self._initialized:
            self._initialized = True
            self._after_connect()
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
        self.lbl_target.setText(f"{ap.get('ssid') or ap.get('bssid')} · {ap.get('bssid')}")
        capture: CapturePage = self.pages["capture"]  # type: ignore[assignment]
        capture.on_target(ap)
        evil: EvilPage = self.pages["evil"]  # type: ignore[assignment]
        evil.on_target(ap)

    # --------------------------------------------------------------- adapters
    def _load_adapters(self) -> None:
        task = Task(self.remote, "adapters_list")
        task.done.connect(safe_callback(self, "adapters_list", self._fill_adapters))
        task.failed.connect(safe_callback(self, "adapters_list:fail", self.show_error))
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
            for adapter in data.get("adapters", []):
                usable = adapter.get("suitable_probe") if role == "probe" else adapter.get("suitable_ap")
                label = f"{adapter.get('iface')} · {adapter.get('driver') or '?'}"
                if not usable:
                    label += f" ({i18n.t('adapters.unsuitable')})"
                combo.addItem(label, adapter.get("iface"))
                if not usable:
                    item = combo.model().item(combo.count() - 1)
                    if item is not None:
                        item.setEnabled(False)
            current = data.get(f"{role}_iface")
            if current:
                index = combo.findData(current)
                if index >= 0:
                    combo.setCurrentIndex(index)
            combo.blockSignals(False)
        if not data.get("adapters"):
            self._log("Wi-Fi адаптеров не найдено")

    @safe_slot
    def _assign(self, role: str) -> None:
        combo = self.combo_probe if role == "probe" else self.combo_ap
        iface = combo.currentData()
        task = Task(self.remote, "adapters_assign", role=role, iface=iface or "")
        task.failed.connect(safe_callback(self, "adapters_assign:fail", self.show_error))
        task.start()

    # --------------------------------------------------------------- project
    @safe_slot
    def _new_project(self) -> None:
        dialog = TextDialog(self, i18n.t("project.new"), i18n.t("project.name"))
        self._dialogs.append(dialog)
        if dialog.exec() != TextDialog.Accepted:
            return
        name = dialog.value()
        if not name:
            return
        task = Task(self.remote, "project_new", name=name)
        task.done.connect(safe_callback(self, "project_new", self._project_ready))
        task.failed.connect(safe_callback(self, "project_new:fail", self.show_error))
        task.start()

    @safe_slot
    def _open_project(self) -> None:
        base = Path.home() / "wifikit-projects"
        path = QFileDialog.getExistingDirectory(self, i18n.t("project.open"), str(base))
        if not path:
            return
        task = Task(self.remote, "project_open", path=path)
        task.done.connect(safe_callback(self, "project_open", self._project_ready))
        task.failed.connect(safe_callback(self, "project_open:fail", self.show_error))
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

    @safe_slot
    def _report(self) -> None:
        task = Task(self.remote, "report_export", fmt="md")
        task.done.connect(safe_callback(self, "report", lambda d: self._log(f"отчёт: {d.get('path')}")))
        task.failed.connect(safe_callback(self, "report:fail", self.show_error))
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
        dialog = ErrorDialog(self, message, detail, kind=kind, subtitle=subtitle, action=action)
        self._dialogs.append(dialog)
        dialog.finished.connect(lambda _r, d=dialog: self._forget(d))
        dialog.exec()

    def _forget(self, dialog: QWidget) -> None:
        try:
            self._dialogs.remove(dialog)
        except ValueError:
            pass

    def show_error(self, message: str, detail: str = "") -> None:
        self.notify_error(message, detail)

    def _log(self, line: str) -> None:
        self.logbox.append(line)
        if hasattr(self, "status_text"):
            self.status_text.setText(line[:160])

    def closeEvent(self, event) -> None:  # noqa: N802
        if self.remote.is_connected():
            self._log("останавливаю демон…")
            self.remote.shutdown()
        event.accept()


def main() -> int:
    install_hooks()
    # падение должно давать Python-стек в лог, а не только «core dumped»
    try:
        handle = open(gui_log_path(), "a", encoding="utf-8")
        faulthandler.enable(file=handle, all_threads=True)
    except OSError:
        faulthandler.enable(all_threads=True)
    i18n.set_lang("ru")
    app = QApplication(sys.argv)
    app.setApplicationName("wifikit")
    # Fusion предсказуемее нативных стилей: одинаково рисует и на GTK, и в VM
    app.setStyle("Fusion")
    app.setPalette(dark_palette())
    font = QFont()
    font.setFamilies(["Inter", "Noto Sans", "DejaVu Sans"])
    font.setPointSize(10)
    app.setFont(font)
    # WIFIKIT_PLAIN=1 — принудительно без стилей, =0 — принудительно со стилями,
    # не задано — без стилей только если прошлый запуск упал нативно
    forced = os.environ.get("WIFIKIT_PLAIN")
    crashed_before = previous_crash()
    safe_mode = decide_safe_mode(forced, crashed_before)
    if not safe_mode:
        app.setStyleSheet(QSS)
    mark_running()
    window = MainWindow()
    window.show()
    if safe_mode and forced is None:
        window.notify_error(
            "Прошлый запуск завершился падением",
            "Стили отключены, чтобы приложение осталось рабочим (Fusion + тёмная палитра).\n\n"
            "Вернуть оформление: запустить WIFIKIT_PLAIN=0 wifikit.\n"
            "Если после этого снова упадёт — пришлите ~/.local/state/wifikit/gui.log "
            "и отчёт wifikit-crash.",
            kind="warn",
            subtitle="Безопасный режим",
        )
    code = app.exec()
    mark_clean()
    return code


if __name__ == "__main__":
    raise SystemExit(main())