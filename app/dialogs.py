"""Модальные окна: ошибка и ввод строки.

Модалки удобны, проблема была в реализации: QMessageBox с WA_DeleteOnClose
удалял C++-объект под живой Python-обёрткой и ронял процесс после закрытия.
Здесь обычный QDialog, который держит ссылку владелец, без автоудаления,
с явным шрифтом и стилями приложения.
"""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (QDialog, QDialogButtonBox, QHBoxLayout, QLabel, QLineEdit,
                               QPlainTextEdit, QPushButton, QVBoxLayout, QWidget)

COLOURS = {"error": "#c9604f", "warn": "#c9a04f", "info": "#4c9f8a"}


class ErrorDialog(QDialog):
    def __init__(self, parent: QWidget, message: str, detail: str = "", kind: str = "error",
                 subtitle: str = "", action: tuple[str, object] | None = None):
        super().__init__(parent)
        self.setWindowTitle("wifikit")
        self.setModal(True)
        self.setMinimumWidth(520)
        self.setAttribute(Qt.WA_QuitOnClose, False)

        root = QVBoxLayout(self)
        root.setContentsMargins(18, 16, 18, 14)
        root.setSpacing(10)

        head = QHBoxLayout()
        head.setSpacing(10)
        dot = QLabel("●")
        dot.setStyleSheet(f"color:{COLOURS.get(kind, COLOURS['error'])}; font-size:15px")
        head.addWidget(dot, 0, Qt.AlignTop)
        title = QLabel(message)
        title.setWordWrap(True)
        title.setStyleSheet("font-size:14px; font-weight:600")
        head.addWidget(title, 1)
        root.addLayout(head)

        if subtitle:
            sub = QLabel(subtitle)
            sub.setObjectName("muted")
            sub.setWordWrap(True)
            root.addWidget(sub)

        self.details = QPlainTextEdit(detail)
        self.details.setReadOnly(True)
        self.details.setObjectName("console")
        self.details.setVisible(bool(detail.strip()))
        self.details.setMinimumHeight(120)
        root.addWidget(self.details)

        buttons = QHBoxLayout()
        button_box = QDialogButtonBox()
        ok = button_box.addButton("Понятно", QDialogButtonBox.AcceptRole)
        ok.setObjectName("primary")
        ok.clicked.connect(self.accept)
        button_box.rejected.connect(self.reject)
        if detail.strip():
            toggle = QPushButton("Скрыть подробности")
            state = {"shown": True}

            def _toggle() -> None:
                state["shown"] = not state["shown"]
                self.details.setVisible(state["shown"])
                toggle.setText("Скрыть подробности" if state["shown"] else "Подробности")
                self.adjustSize()

            toggle.clicked.connect(_toggle)
            button_box.addButton(toggle, QDialogButtonBox.ActionRole)

        self.action_fired = False
        if action:
            label, handler = action

            def _run() -> None:
                self.action_fired = True
                try:
                    handler()  # type: ignore[operator]
                finally:
                    self.accept()

            run_button = button_box.addButton(label, QDialogButtonBox.ActionRole)
            run_button.setObjectName("primary")
            run_button.clicked.connect(_run)

        buttons.addWidget(button_box)
        root.addLayout(buttons)


class TextDialog(QDialog):
    """Запрос одной строки (имя проекта) без QInputDialog."""

    def __init__(self, parent: QWidget, title: str, label: str, value: str = ""):
        super().__init__(parent)
        self.setWindowTitle(title)
        self.setModal(True)
        self.setMinimumWidth(420)

        root = QVBoxLayout(self)
        root.setContentsMargins(18, 16, 18, 14)
        root.setSpacing(10)
        caption = QLabel(label)
        root.addWidget(caption)
        self.edit = QLineEdit(value)
        self.edit.selectAll()
        root.addWidget(self.edit)

        box = QDialogButtonBox()
        ok = box.addButton("OK", QDialogButtonBox.AcceptRole)
        ok.setObjectName("primary")
        ok.setDefault(True)
        ok.clicked.connect(self.accept)
        box.addButton("Отмена", QDialogButtonBox.RejectRole)
        box.rejected.connect(self.reject)
        root.addWidget(box)
        self.edit.returnPressed.connect(self.accept)

    def value(self) -> str:
        return self.edit.text().strip()