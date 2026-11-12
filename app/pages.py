"""Страницы приложения. Логика — только вызовы демона и отрисовка ответов."""

from __future__ import annotations

import re
from pathlib import Path

from PySide6.QtCore import Qt, QTimer, QUrl, Signal
from PySide6.QtGui import QDesktopServices, QFont
from PySide6.QtWidgets import (QCheckBox, QComboBox, QFileDialog, QFrame, QGridLayout,
                               QHBoxLayout, QHeaderView, QLabel, QLineEdit,
                               QPlainTextEdit, QProgressBar, QPushButton, QSpinBox,
                               QTableWidget, QTableWidgetItem, QVBoxLayout, QWidget)

from app import i18n
from app.positions import PositionsEditor
from app.safe import expect_dict, safe_callback, safe_slot
from app.remote import Remote, Task
from app.theme import ACCENT, DANGER, MUTED, WARN


class State:
    def __init__(self) -> None:
        self.target: dict | None = None
        self.aps: dict[str, dict] = {}
        self.capture_result: dict | None = None
        self.lang = "ru"


def h1(text: str) -> QLabel:
    label = QLabel(text)
    label.setObjectName("h1")
    return label


def h2(text: str) -> QLabel:
    label = QLabel(text.upper())
    label.setObjectName("h2")
    return label


def muted(text: str = "") -> QLabel:
    label = QLabel(text)
    label.setObjectName("muted")
    label.setWordWrap(True)
    return label


def badge(text: str, kind: str = "badge") -> QLabel:
    label = QLabel(text.upper())
    label.setObjectName(kind)
    label.setAlignment(Qt.AlignCenter)
    return label


def divider() -> QFrame:
    line = QFrame()
    line.setFrameShape(QFrame.HLine)
    line.setStyleSheet("color:#242a36")
    return line


class Page(QWidget):
    def __init__(self, remote: Remote, state: State):
        super().__init__()
        self.remote = remote
        self.state = state

    def call(self, method: str, on_done=None, on_fail=None, **params) -> Task:
        """Все ответы демона проходят через защищённые обёртки.

        Исключение внутри слота в PySide6 валит процесс, поэтому обработчик
        не должен бросать ничего наружу — ни из-за данных, ни из-за логики.
        """
        task = Task(self.remote, method, **params)
        if on_done:
            task.done.connect(safe_callback(self, method, on_done))
        task.failed.connect(safe_callback(self, f"{method}:fail", on_fail or self.show_error))
        return task.start()

    def show_error(self, message: str, detail: str = "") -> None:
        """Ошибка показывается панелью в окне: модальные диалоги в PySide6 роняли процесс."""
        window = self.window()
        notify = getattr(window, "notify_error", None)
        if callable(notify):
            notify(message, detail)
        else:
            print(f"[error] {message} {detail}")

    def refresh(self) -> None:  # переопределяется
        pass


# --------------------------------------------------------------------------- scan
class ScanPage(Page):
    target_changed = Signal(dict)

    def __init__(self, remote: Remote, state: State):
        super().__init__(remote, state)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(24, 20, 24, 20)
        lay.setSpacing(10)
        top = QHBoxLayout()
        top.addWidget(h1(i18n.t("scan.start")))
        top.addStretch(1)
        self.seconds = QSpinBox()
        self.seconds.setRange(5, 120)
        self.seconds.setValue(15)
        self.seconds.setSuffix(" с")
        top.addWidget(self.seconds)
        self.btn = QPushButton(i18n.t("scan.start"))
        self.btn.setObjectName("primary")
        self.btn.clicked.connect(self._scan)
        top.addWidget(self.btn)
        lay.addLayout(top)
        self.table = QTableWidget(0, 6)
        self.table.setHorizontalHeaderLabels([
            i18n.t("scan.col.ssid"), i18n.t("scan.col.bssid"), i18n.t("scan.col.ch"),
            i18n.t("scan.col.rssi"), i18n.t("scan.col.sec"), i18n.t("scan.col.hint"),
        ])
        self.table.horizontalHeader().setSectionResizeMode(0, QHeaderView.Stretch)
        self.table.horizontalHeader().setSectionResizeMode(5, QHeaderView.Stretch)
        self.table.verticalHeader().setVisible(False)
        self.table.setSelectionBehavior(QTableWidget.SelectRows)
        self.table.setEditTriggers(QTableWidget.NoEditTriggers)
        self.table.itemSelectionChanged.connect(self._selected)
        lay.addWidget(self.table, 1)
        self.status = muted(i18n.t("scan.empty"))
        lay.addWidget(self.status)
        # сторож: «сканирую…» не должно висеть вечно, если демон не ответил
        self._watchdog = QTimer(self)
        self._watchdog.setSingleShot(True)
        self._watchdog.timeout.connect(self._scan_stuck)

    def _scan(self) -> None:
        self.btn.setEnabled(False)
        self.status.setText("сканирую…")
        self._watchdog.start(int(self.seconds.value() * 1000) + 12000)
        self.call("scan_start", self._done, self._fail, seconds=float(self.seconds.value()))

    def _scan_stuck(self) -> None:
        if self.btn.isEnabled():
            return
        self.btn.setEnabled(True)
        self.status.setText("демон не ответил на скан — смотрите журнал")
        self.show_error("Скан не завершился",
                        "Демон не вернул результат за отведённое время.\n"
                        "Проверьте адаптер сенсора и хвост журнала.")

    def _fail(self, message: str, detail: str) -> None:
        self._watchdog.stop()
        self.btn.setEnabled(True)
        self.status.setText(message)
        self.show_error(message, detail)

    def _done(self, data: dict) -> None:
        self._watchdog.stop()
        data = expect_dict(self, "scan_start", data)
        if data is None:
            self.btn.setEnabled(True)
            return
        self.btn.setEnabled(True)
        self.status.setText(f"найдено: {data.get('count', 0)}")
        self.state.aps = {ap["bssid"]: ap for ap in data["aps"]}
        self.table.setRowCount(0)
        for ap in data["aps"]:
            self._add_row(ap)

    def _add_row(self, ap: dict) -> None:
        row = self.table.rowCount()
        self.table.insertRow(row)
        ssid = ap["ssid"] or i18n.t("scan.hidden")
        values = [ssid, ap["bssid"], str(ap["channel"]), f"{ap['rssi']} dBm", self._sec(ap), ap["hint"]]
        for col, text in enumerate(values):
            item = QTableWidgetItem(text)
            if col >= 2:
                item.setFont(QFont("monospace", 11))
            if col == 4:
                item.setForeground(_sec_color(ap))
            if col == 5:
                item.setForeground(Qt.gray)
            self.table.setItem(row, col, item)
        self.table.item(row, 1).setData(Qt.UserRole, ap["bssid"])

    @staticmethod
    def _sec(ap: dict) -> str:
        bits = []
        if ap["wpa3"]:
            bits.append("WPA3")
        if ap["wpa2"]:
            bits.append("WPA2")
        if ap["wpa"]:
            bits.append("WPA")
        if ap["open"]:
            bits.append("OPEN")
        if ap["pmf"] == "pmf_req":
            bits.append("PMF!")
        return " ".join(bits) or "—"

    def _selected(self) -> None:
        rows = self.table.selectionModel().selectedRows()
        if not rows:
            return
        bssid = self.table.item(rows[0].row(), 1).data(Qt.UserRole)
        ap = self.state.aps.get(bssid)
        if ap:
            self.state.target = ap
            self.target_changed.emit(ap)


def _sec_color(ap: dict):
    from PySide6.QtGui import QColor

    if ap["open"]:
        return QColor(WARN)
    if not ap["crackable"]:
        return QColor(DANGER)
    if ap["pmf"] == "pmf_req":
        return QColor(WARN)
    return QColor(ACCENT)


# ------------------------------------------------------------------------ capture
class CapturePage(Page):
    def __init__(self, remote: Remote, state: State):
        super().__init__(remote, state)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(24, 20, 24, 20)
        lay.setSpacing(12)
        lay.addWidget(h1(i18n.t("nav.capture")))
        self.target = muted("цель не выбрана — отметьте точку в «Точки»")
        lay.addWidget(self.target)
        self.hint = muted("")
        lay.addWidget(self.hint)

        opts = QHBoxLayout()
        opts.addWidget(QLabel(i18n.t("capture.minutes")))
        self.minutes = QSpinBox()
        self.minutes.setRange(1, 60)
        self.minutes.setValue(5)
        opts.addWidget(self.minutes)
        self.deauth = QCheckBox(i18n.t("capture.deauth"))
        self.deauth.setChecked(True)
        opts.addWidget(self.deauth)
        opts.addStretch(1)
        lay.addLayout(opts)

        buttons = QHBoxLayout()
        self.btn_start = QPushButton(i18n.t("capture.start"))
        self.btn_start.setObjectName("primary")
        self.btn_start.clicked.connect(lambda: self._start("handshake"))
        self.btn_pmkid = QPushButton(i18n.t("capture.pmkid_first"))
        self.btn_pmkid.clicked.connect(lambda: self._start("pmkid"))
        self.btn_stop = QPushButton(i18n.t("capture.stop"))
        self.btn_stop.setObjectName("danger")
        self.btn_stop.setEnabled(False)
        self.btn_stop.clicked.connect(lambda: self.call("capture_stop", self._stopped))
        buttons.addWidget(self.btn_start)
        buttons.addWidget(self.btn_pmkid)
        buttons.addWidget(self.btn_stop)
        buttons.addStretch(1)
        lay.addLayout(buttons)

        lay.addWidget(h2(i18n.t("capture.result")))
        self.result = muted(i18n.t("capture.none"))
        lay.addWidget(self.result)
        self.console = QPlainTextEdit()
        self.console.setReadOnly(True)
        self.console.setObjectName("console")
        lay.addWidget(self.console, 1)

    def on_target(self, ap: dict) -> None:
        self.state.target = ap
        name = ap["ssid"] or ap["bssid"]
        badges = []
        if ap["wpa3"]:
            badges.append("WPA3")
        if ap["pmf"] == "pmf_req":
            badges.append("PMF обязателен")
        self.target.setText(f"{name} · {ap['bssid']} · кан {ap['channel']}")
        self.hint.setText(ap["hint"] + (" · " + ", ".join(badges) if badges else ""))

    def _start(self, mode: str) -> None:
        ap = self.state.target
        if not ap:
            self.show_error("выберите точку в разделе «Точки»")
            return
        self.btn_start.setEnabled(False)
        self.btn_pmkid.setEnabled(False)
        self.call("capture_start", self._started, self._fail,
                  bssid=ap["bssid"], mode=mode, minutes=float(self.minutes.value()))

    def _fail(self, message: str, detail: str) -> None:
        self.btn_start.setEnabled(True)
        self.btn_pmkid.setEnabled(True)
        self.show_error(message, detail)

    def _started(self, data: dict) -> None:
        data = expect_dict(self, "capture_start", data)
        if data is None:
            return
        self.btn_stop.setEnabled(True)
        self.console.setPlainText("\n".join((data.get("job") or {}).get("argv") or []))
        target = self.state.target
        if self.deauth.isChecked() and target:
            self.call("deauth_start", lambda _d: None, bssid=target["bssid"])

    def _stopped(self, data: dict) -> None:
        self.btn_stop.setEnabled(False)
        self.btn_start.setEnabled(True)
        self.btn_pmkid.setEnabled(True)
        self.call("deauth_stop", lambda _d: None)

    def refresh(self) -> None:
        self.call("capture_status", self._status)

    def _status(self, data: dict) -> None:
        data = expect_dict(self, "capture_status", data)
        if data is None:
            return
        job = data.get("job")
        if job and job.get("state") in ("starting", "running", "stopping"):
            self.result.setText(f"идёт захват, {data.get('elapsed')} с")
            return
        result = data.get("result")
        if not result:
            return
        self.btn_stop.setEnabled(False)
        self.btn_start.setEnabled(True)
        self.btn_pmkid.setEnabled(True)
        if result["success"]:
            self.result.setText(f"{i18n.t('capture.ok')}: PMKID {result['pmkid']}, EAPOL {result['eapol']}")
            self.result.setObjectName("ok")
        else:
            self.result.setText(i18n.t("capture.fail") + (": " + "; ".join(result["notes"]) if result["notes"] else ""))
            self.result.setObjectName("bad")
        self.result.setStyleSheet("")
        self.state.capture_result = result


# -------------------------------------------------------------------------- crack
class CrackPage(Page):
    def __init__(self, remote: Remote, state: State):
        super().__init__(remote, state)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(24, 20, 24, 20)
        lay.setSpacing(10)
        lay.addWidget(h1(i18n.t("nav.crack")))
        self.info = muted(i18n.t("crack.no_hash"))
        lay.addWidget(self.info)

        grid = QGridLayout()
        grid.setHorizontalSpacing(10)
        grid.addWidget(QLabel(i18n.t("crack.attack")), 0, 0)
        self.attack = QComboBox()
        self.attack.addItem("по позициям", "positions")
        self.attack.addItem(i18n.t("crack.wordlist"), "wordlist")
        self.attack.addItem(i18n.t("crack.mask"), "mask")
        self.attack.addItem(i18n.t("crack.hybrid"), "hybrid")
        self.attack.currentIndexChanged.connect(self._sync)
        grid.addWidget(self.attack, 0, 1)

        self.lbl_wl = QLabel(i18n.t("crack.wordlist"))
        grid.addWidget(self.lbl_wl, 1, 0)
        self.wordlist = QLineEdit()
        grid.addWidget(self.wordlist, 1, 1)
        self.pick_wl = QPushButton("…")
        self.pick_wl.setFixedWidth(34)
        self.pick_wl.clicked.connect(self._choose_wordlist)
        grid.addWidget(self.pick_wl, 1, 2)

        self.lbl_rules = QLabel(i18n.t("crack.rules"))
        grid.addWidget(self.lbl_rules, 2, 0)
        self.rules = QComboBox()
        self.rules.addItem("—", None)
        self.rules.addItem("best64", "best64")
        self.rules.addItem("dive", "dive")
        self.rules.addItem("rockyou-30000", "rockyou-30000")
        grid.addWidget(self.rules, 2, 1)

        self.lbl_mask = QLabel(i18n.t("crack.mask_value"))
        grid.addWidget(self.lbl_mask, 3, 0)
        self.mask = QComboBox()
        self.mask.setEditable(True)
        for label, value in (("8 цифр", "?d?d?d?d?d?d?d?d"), ("6 цифр", "?d?d?d?d?d?d"),
                             ("8 строчных", "?l?l?l?l?l?l?l?l"), ("hex 8", "?h?h?h?h?h?h?h?h")):
            self.mask.addItem(label, value)
        grid.addWidget(self.mask, 3, 1)
        grid.setColumnStretch(1, 1)
        lay.addLayout(grid)

        self.positions = PositionsEditor()
        self.positions.setVisible(False)
        self.positions.changed.connect(self._schedule_preview)
        lay.addWidget(self.positions)
        self._preview_timer = QTimer(self)
        self._preview_timer.setSingleShot(True)
        self._preview_timer.setInterval(350)
        self._preview_timer.timeout.connect(self._preview_masks)

        buttons = QHBoxLayout()
        self.btn_candidates = QPushButton(i18n.t("crack.candidates"))
        self.btn_candidates.clicked.connect(self._candidates)
        self.btn_start = QPushButton(i18n.t("crack.start"))
        self.btn_start.setObjectName("primary")
        self.btn_start.clicked.connect(self._start)
        self.btn_stop = QPushButton(i18n.t("crack.stop"))
        self.btn_stop.setObjectName("danger")
        self.btn_stop.setEnabled(False)
        self.btn_stop.clicked.connect(lambda: self.call("crack_stop", self._status))
        buttons.addWidget(self.btn_candidates)
        buttons.addWidget(self.btn_start)
        buttons.addWidget(self.btn_stop)
        buttons.addStretch(1)
        lay.addLayout(buttons)

        stat = QHBoxLayout()
        self.speed = muted("")
        stat.addWidget(QLabel(i18n.t("crack.speed")))
        stat.addWidget(self.speed, 1)
        lay.addLayout(stat)
        self.progress = QProgressBar()
        self.progress.setRange(0, 100)
        lay.addWidget(self.progress)
        lay.addWidget(h2(i18n.t("crack.found")))
        self.found = QPlainTextEdit()
        self.found.setReadOnly(True)
        self.found.setObjectName("console")
        lay.addWidget(self.found, 1)
        self._sync()

    def _sync(self) -> None:
        kind = self.attack.currentData()
        use_wl = kind in ("wordlist", "hybrid")
        use_rules = kind == "wordlist"
        use_mask = kind in ("mask", "hybrid")
        for widget in (self.lbl_wl, self.wordlist, self.pick_wl):
            widget.setVisible(use_wl)
        for widget in (self.lbl_rules, self.rules):
            widget.setVisible(use_rules)
        for widget in (self.lbl_mask, self.mask):
            widget.setVisible(use_mask)
        self.positions.setVisible(kind == "positions")
        if kind == "positions":
            self._schedule_preview()

    def _schedule_preview(self) -> None:
        self._preview_timer.start()

    def _preview_masks(self) -> None:
        low, high = self.positions.lengths()
        self.call("mask_preview", self._preview_done, lambda m, d: self.positions.hint.setText(m),
                  positions=self.positions.positions(), length_min=low, length_max=high)

    def _preview_done(self, spec: dict) -> None:
        spec = expect_dict(self, "mask_preview", spec)
        if spec is not None:
            self.positions.apply_spec(spec)

    def _choose_wordlist(self) -> None:
        path, _ = QFileDialog.getOpenFileName(self, i18n.t("crack.wordlist"), str(Path.home()))
        if path:
            self.wordlist.setText(path)

    def _candidates(self) -> None:
        self.call("candidates", self._cand_done)

    def _cand_done(self, data: dict) -> None:
        self.wordlist.setText(data["path"])
        self.info.setText(f"кандидатов: {data['count']} — можно крошить словарём с правилами")

    def _start(self) -> None:
        self.btn_start.setEnabled(False)
        self.btn_stop.setEnabled(True)
        kind = self.attack.currentData()
        raw_mask = self.mask.currentData() or self.mask.currentText()
        low, high = self.positions.lengths()
        self.call("crack_start", self._status, self._fail,
                  attack=kind,
                  wordlist=self.wordlist.text() or None,
                  rules=self.rules.currentData(),
                  mask_raw=raw_mask if kind in ("mask", "hybrid") else None,
                  positions=self.positions.positions() if kind == "positions" else None,
                  length_min=low if kind == "positions" else None,
                  length_max=high if kind == "positions" else None)

    def _fail(self, message: str, detail: str) -> None:
        self.btn_start.setEnabled(True)
        self.btn_stop.setEnabled(False)
        self.show_error(message, detail)

    def refresh(self) -> None:
        self.call("crack_status", self._status)

    def _status(self, data: dict) -> None:
        data = expect_dict(self, "crack_status", data)
        if data is None:
            return
        job = data.get("job")
        running = bool(data.get("running"))
        self.btn_stop.setEnabled(running)
        self.btn_start.setEnabled(not running)
        self.progress.setValue(int(data.get("progress") or 0))
        self.speed.setText(data.get("speed") or "")
        if data.get("found"):
            self.found.setPlainText("\n".join(data["found"]))


# ---------------------------------------------------------------------- evil twin
class EvilPage(Page):
    def __init__(self, remote: Remote, state: State):
        super().__init__(remote, state)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(24, 20, 24, 20)
        lay.setSpacing(10)
        lay.addWidget(h1(i18n.t("nav.evil")))
        self.warn = muted(i18n.t("evil.need"))
        lay.addWidget(self.warn)
        self.target = muted("цель не выбрана")
        lay.addWidget(self.target)

        row = QHBoxLayout()
        row.addWidget(QLabel(i18n.t("evil.template")))
        self.template = QComboBox()
        self.template.setMinimumWidth(220)
        row.addWidget(self.template, 1)
        self.upload = QPushButton(i18n.t("evil.upload"))
        self.upload.clicked.connect(self._upload)
        row.addWidget(self.upload)
        lay.addLayout(row)

        opts = QHBoxLayout()
        self.clone = QCheckBox(i18n.t("evil.clone"))
        self.clone.setChecked(True)
        self.verify = QCheckBox(i18n.t("evil.verify"))
        self.verify.setChecked(True)
        opts.addWidget(self.clone)
        opts.addWidget(self.verify)
        opts.addStretch(1)
        lay.addLayout(opts)

        buttons = QHBoxLayout()
        self.btn_up = QPushButton(i18n.t("evil.raise"))
        self.btn_up.setObjectName("primary")
        self.btn_up.clicked.connect(self._raise)
        self.btn_down = QPushButton(i18n.t("evil.drop"))
        self.btn_down.setObjectName("danger")
        self.btn_down.setEnabled(False)
        self.btn_down.clicked.connect(self._drop)
        self.btn_open = QPushButton(i18n.t("evil.preview"))
        self.btn_open.clicked.connect(lambda: QDesktopServices.openUrl(QUrl("http://192.168.77.1:8080/")))
        buttons.addWidget(self.btn_up)
        buttons.addWidget(self.btn_down)
        buttons.addWidget(self.btn_open)
        buttons.addStretch(1)
        lay.addLayout(buttons)

        self.ap_state = muted("")
        lay.addWidget(self.ap_state)

        lay.addWidget(h2(i18n.t("evil.clients")))
        self.clients = QTableWidget(0, 2)
        self.clients.setHorizontalHeaderLabels(["MAC", "IP"])
        self.clients.verticalHeader().setVisible(False)
        self.clients.setFixedHeight(110)
        lay.addWidget(self.clients)

        lay.addWidget(h2(i18n.t("evil.submits")))
        self.submits = QTableWidget(0, 3)
        self.submits.setHorizontalHeaderLabels(["Время", "Поля", "Вердикт"])
        self.submits.horizontalHeader().setSectionResizeMode(1, QHeaderView.Stretch)
        self.submits.verticalHeader().setVisible(False)
        lay.addWidget(self.submits, 1)

    def on_target(self, ap: dict) -> None:
        self.state.target = ap
        self.target.setText(f"{ap['ssid'] or ap['bssid']} · {ap['bssid']} · кан {ap['channel']}")
        self.call("adapters_list", self._check_adapters)

    def _check_adapters(self, data: dict) -> None:
        data = expect_dict(self, "adapters_list", data)
        if data is None:
            return
        ok = bool(data.get("probe_iface") and data.get("ap_iface")
                  and data["probe_iface"] != data["ap_iface"])
        self.warn.setText("адаптеры назначены" if ok else i18n.t("evil.need"))
        self.btn_up.setEnabled(ok)

    def refresh(self) -> None:
        self.call("portal_templates", self._templates, self.show_error)

    def _templates(self, data: dict) -> None:
        data = expect_dict(self, "portal_templates", data)
        if data is None:
            return
        current = self.template.currentData()
        self.template.clear()
        for tpl in data["templates"]:
            self.template.addItem(f"{tpl['name']} ({tpl['lang']}, шагов: {tpl['steps']})", tpl["id"])
        if current:
            index = self.template.findData(current)
            if index >= 0:
                self.template.setCurrentIndex(index)

    def _upload(self) -> None:
        path, _ = QFileDialog.getOpenFileName(self, i18n.t("evil.upload"), str(Path.home()),
                                              "HTML/ZIP (*.html *.htm *.zip)")
        if not path:
            return
        name = Path(path).stem
        self.call("portal_install", lambda _d: self.refresh(), self.show_error, path=path, name=name)

    def _raise(self) -> None:
        ap = self.state.target
        if not ap:
            self.show_error("выберите точку")
            return
        self.btn_up.setEnabled(False)
        self.call("ap_start", self._raised, self._fail, bssid=ap["bssid"], clone_bssid=self.clone.isChecked())

    def _fail(self, message: str, detail: str) -> None:
        self.btn_up.setEnabled(True)
        self.show_error(message, detail)

    def _raised(self, data: dict) -> None:
        self.btn_down.setEnabled(True)
        template = self.template.currentData()
        if not template:
            self.ap_state.setText("точка поднята, шаблон не выбран")
            return
        self.call("portal_start", self._portal_up, self._fail,
                  template_id=template, verify=self.verify.isChecked())

    def _portal_up(self, data: dict) -> None:
        data = expect_dict(self, "portal_start", data)
        if data is None:
            return
        name = (data.get("template") or {}).get("name", "")
        self.ap_state.setText(f"точка и портал подняты: {name}")

    def _drop(self) -> None:
        self.btn_down.setEnabled(False)
        self.btn_up.setEnabled(True)
        self.call("ap_stop", lambda _d: self.ap_state.setText("точка погашена"))

    def update_status(self, ap: dict, portal: dict) -> None:
        if ap.get("running"):
            self.ap_state.setText(f"поднята · SSID {ap.get('ssid')} · клиентов {len(ap.get('clients') or [])}")
        self.clients.setRowCount(0)
        for client in ap.get("clients") or []:
            row = self.clients.rowCount()
            self.clients.insertRow(row)
            self.clients.setItem(row, 0, QTableWidgetItem(client["mac"]))
            self.clients.setItem(row, 1, QTableWidgetItem(client["ip"]))
        subs = portal.get("submissions") or []
        self.submits.setRowCount(0)
        for sub in subs[-40:]:
            row = self.submits.rowCount()
            self.submits.insertRow(row)
            stamp = __import__("time").strftime("%H:%M:%S", __import__("time").localtime(sub["ts"]))
            fields = ", ".join(f"{k}={v}" for k, v in sub["fields"].items())
            self.submits.setItem(row, 0, QTableWidgetItem(stamp))
            self.submits.setItem(row, 1, QTableWidgetItem(fields))
            verdict = QTableWidgetItem({"ok": "верно", "retry": "неверно"}.get(sub["verdict"], "…"))
            self.submits.setItem(row, 2, verdict)


# --------------------------------------------------------------------------- log
class LogPage(Page):
    def __init__(self, remote: Remote, state: State):
        super().__init__(remote, state)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(24, 20, 24, 20)
        lay.setSpacing(10)
        top = QHBoxLayout()
        top.addWidget(h1(i18n.t("nav.log")))
        top.addStretch(1)
        clear = QPushButton(i18n.t("log.clear"))
        clear.clicked.connect(lambda: self.box.clear())
        top.addWidget(clear)
        lay.addLayout(top)
        self.box = QPlainTextEdit()
        self.box.setReadOnly(True)
        self.box.setObjectName("console")
        self.box.setMaximumBlockCount(5000)
        lay.addWidget(self.box, 1)

    def append(self, line: str) -> None:
        self.box.appendPlainText(line)


PAGES = {
    "scan": (ScanPage, i18n.t("nav.scan")),
    "capture": (CapturePage, i18n.t("nav.capture")),
    "crack": (CrackPage, i18n.t("nav.crack")),
    "evil": (EvilPage, i18n.t("nav.evil")),
    "log": (LogPage, i18n.t("nav.log")),
}
