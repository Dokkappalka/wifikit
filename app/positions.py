"""Редактор перебора по позициям: каждая позиция — тип символов или фиксированный символ."""

from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (QComboBox, QHBoxLayout, QHeaderView, QLabel, QLineEdit,
                               QPushButton, QSpinBox, QTableWidget, QVBoxLayout, QWidget)

KINDS = [
    ("любой", "any"),
    ("цифры", "digit"),
    ("строчные", "lower"),
    ("ПРОПИСНЫЕ", "upper"),
    ("hex", "hex"),
    ("знаки", "special"),
    ("свой набор", "custom"),
    ("символ", "fixed"),
]
DEFAULT_ROWS = 8


class PositionsEditor(QWidget):
    changed = Signal()

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(8)

        top = QHBoxLayout()
        top.addWidget(QLabel("длина от"))
        self.len_min = QSpinBox()
        self.len_min.setRange(1, 63)
        self.len_min.setValue(DEFAULT_ROWS)
        top.addWidget(self.len_min)
        top.addWidget(QLabel("до"))
        self.len_max = QSpinBox()
        self.len_max.setRange(1, 63)
        self.len_max.setValue(DEFAULT_ROWS)
        top.addWidget(self.len_max)
        self.btn_add = QPushButton("+ позиция")
        self.btn_add.setFixedWidth(96)
        self.btn_add.clicked.connect(lambda: self._add_row())
        self.btn_del = QPushButton("− позиция")
        self.btn_del.setFixedWidth(96)
        self.btn_del.clicked.connect(self._del_row)
        top.addWidget(self.btn_add)
        top.addWidget(self.btn_del)
        top.addStretch(1)
        lay.addLayout(top)

        self.table = QTableWidget(0, 3)
        self.table.setHorizontalHeaderLabels(["позиция", "тип", "значение"])
        self.table.verticalHeader().setVisible(False)
        self.table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(2, QHeaderView.Stretch)
        self.table.setFixedHeight(268)
        # строка таблицы должна быть выше виджета внутри, иначе текст обрезается
        self.table.verticalHeader().setDefaultSectionSize(40)
        self.table.verticalHeader().setMinimumSectionSize(40)
        lay.addWidget(self.table)

        self.hint = QLabel("")
        self.hint.setObjectName("muted")
        self.hint.setWordWrap(True)
        lay.addWidget(self.hint)

        for _ in range(DEFAULT_ROWS):
            self._add_row(emit=False)
        self.len_min.valueChanged.connect(lambda _v: self.changed.emit())
        self.len_max.valueChanged.connect(lambda _v: self.changed.emit())

    # ------------------------------------------------------------------ rows
    def _add_row(self, kind: str = "any", value: str = "", emit: bool = True) -> None:
        row = self.table.rowCount()
        if row >= 63:
            return
        self.table.insertRow(row)

        label = QLabel(str(row + 1))
        label.setObjectName("mono")
        label.setAlignment(Qt.AlignCenter)
        self.table.setCellWidget(row, 0, label)

        combo = QComboBox()
        for title, key in KINDS:
            combo.addItem(title, key)
        index = combo.findData(kind)
        if index >= 0:
            combo.setCurrentIndex(index)
        self.table.setCellWidget(row, 1, combo)

        edit = QLineEdit(value)
        edit.setPlaceholderText("символ или набор символов")
        self.table.setCellWidget(row, 2, edit)

        combo.currentIndexChanged.connect(lambda _i, c=combo, e=edit: self._sync_row(c, e))
        edit.textChanged.connect(lambda _t: self.changed.emit())
        self._sync_row(combo, edit)
        if emit:
            self.changed.emit()

    def _del_row(self) -> None:
        if self.table.rowCount() > 1:
            self.table.removeRow(self.table.rowCount() - 1)
            self.changed.emit()

    @staticmethod
    def _sync_row(combo: QComboBox, edit: QLineEdit) -> None:
        kind = combo.currentData()
        edit.setEnabled(kind in ("fixed", "custom"))
        edit.setPlaceholderText({"fixed": "один символ", "custom": "например abc123"}.get(kind, ""))

    # ------------------------------------------------------------------ data
    def positions(self) -> list[dict]:
        out = []
        for row in range(self.table.rowCount()):
            combo = self.table.cellWidget(row, 1)
            edit = self.table.cellWidget(row, 2)
            if not isinstance(combo, QComboBox) or not isinstance(edit, QLineEdit):
                continue
            out.append({"kind": combo.currentData(), "value": edit.text()})
        return out

    def lengths(self) -> tuple[int, int]:
        return self.len_min.value(), self.len_max.value()

    def set_lengths(self, low: int, high: int) -> None:
        self.len_min.setValue(low)
        self.len_max.setValue(high)

    def apply_spec(self, spec: dict) -> None:
        self.hint.setText(
            f"маска {spec['mask']} · перебор {spec['keyspace_human']}"
            + ("".join("\n" + w for w in spec.get("warnings") or [])))