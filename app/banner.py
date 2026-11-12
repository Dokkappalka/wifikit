"""Встроенная панель сообщений вместо модальных окон.

Модальные QMessageBox в PySide6 — источник падений: диалог с WA_DeleteOnClose
удаляет C++-объект, а Python-обёртка живёт дальше и при сборке мусора пытается
освободить его повторно → SIGSEGV/SIGBUS. Панель живёт в окне, ничего не
удаляет и не блокирует интерфейс.
"""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (QFrame, QHBoxLayout, QLabel, QPlainTextEdit, QPushButton,
                               QSizePolicy, QVBoxLayout, QWidget)

KINDS = {
    "error": ("#c9604f", "Ошибка"),
    "warn": ("#c9a04f", "Внимание"),
    "info": ("#4c9f8a", "Готово"),
}


class Banner(QFrame):
    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self.setObjectName("banner")
        self.setVisible(False)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Maximum)

        root = QVBoxLayout(self)
        root.setContentsMargins(14, 10, 14, 10)
        root.setSpacing(6)

        top = QHBoxLayout()
        top.setSpacing(10)
        self.dot = QLabel("●")
        self.dot.setFixedWidth(12)
        top.addWidget(self.dot, 0, Qt.AlignTop)

        titles = QVBoxLayout()
        titles.setSpacing(2)
        self.title = QLabel("")
        self.title.setObjectName("banner_title")
        self.title.setWordWrap(True)
        titles.addWidget(self.title)
        self.subtitle = QLabel("")
        self.subtitle.setObjectName("muted")
        self.subtitle.setWordWrap(True)
        self.subtitle.setVisible(False)
        titles.addWidget(self.subtitle)
        top.addLayout(titles, 1)

        self.btn_action = QPushButton("")
        self.btn_action.setVisible(False)
        top.addWidget(self.btn_action, 0, Qt.AlignTop)

        self.btn_details = QPushButton("Подробнее")
        self.btn_details.setVisible(False)
        self.btn_details.clicked.connect(self._toggle_details)
        top.addWidget(self.btn_details, 0, Qt.AlignTop)

        self.btn_close = QPushButton("Скрыть")
        self.btn_close.clicked.connect(self.hide_banner)
        top.addWidget(self.btn_close, 0, Qt.AlignTop)
        root.addLayout(top)

        self.details = QPlainTextEdit()
        self.details.setReadOnly(True)
        self.details.setObjectName("console")
        self.details.setVisible(False)
        self.details.setMinimumHeight(90)
        self.details.setMaximumHeight(220)
        root.addWidget(self.details)

        self._title_text = ""

    # ------------------------------------------------------------------ api
    def notify(self, title: str, detail: str = "", kind: str = "error",
               subtitle: str = "", action: tuple[str, object] | None = None) -> None:
        colour, default_title = KINDS.get(kind, KINDS["error"])
        self._title_text = default_title
        self.dot.setStyleSheet(f"color:{colour}; font-size:14px")
        self.title.setText(title)
        self.subtitle.setText(subtitle)
        self.subtitle.setVisible(bool(subtitle))
        self.details.setPlainText(detail)
        self.details.setVisible(False)
        self.btn_details.setVisible(bool(detail.strip()))
        self.btn_details.setText("Подробнее")
        if action:
            label, handler = action
            self.btn_action.setText(label)
            self.btn_action.setVisible(True)
            try:
                self.btn_action.clicked.disconnect()
            except (RuntimeError, TypeError):
                pass
            self.btn_action.clicked.connect(handler)  # type: ignore[arg-type]
        else:
            self.btn_action.setVisible(False)
        self.setVisible(True)

    def hide_banner(self) -> None:
        self.setVisible(False)

    def _toggle_details(self) -> None:
        shown = self.details.isVisible()
        self.details.setVisible(not shown)
        self.btn_details.setText("Свернуть" if not shown else "Подробнее")