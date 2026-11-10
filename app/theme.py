"""Тема: строгая тёмная, один акцент, моноширинные цифры."""

from __future__ import annotations

BG = "#0f1115"
PANEL = "#151821"
CARD = "#191d27"
BORDER = "#242a36"
TEXT = "#dfe3ea"
MUTED = "#a4acba"
ACCENT = "#4c9f8a"
ACCENT_DIM = "#2f6b5d"
DANGER = "#c9604f"
WARN = "#c9a04f"

QSS = f"""
* {{ font-family: "Inter", "SF Pro Text", "Segoe UI", "Noto Sans", sans-serif; font-size: 13px; }}
QWidget {{ background: {BG}; color: {TEXT}; }}
QFrame#sidebar {{ background: {PANEL}; border-right: 1px solid {BORDER}; }}
QLabel#brand {{ font-size: 15px; font-weight: 600; letter-spacing: .04em; }}
QLabel#muted, QLabel.muted {{ color: {MUTED}; }}
QLabel#h1 {{ font-size: 17px; font-weight: 600; }}
QLabel#h2 {{ font-size: 11px; color: {MUTED}; text-transform: uppercase; letter-spacing: .1em; }}
QLabel#mono, QLabel.mono {{ font-family: "JetBrains Mono", "SF Mono", Menlo, monospace; }}
QLabel#ok {{ color: {ACCENT}; }}
QLabel#bad {{ color: {DANGER}; }}
QLabel#warn {{ color: {WARN}; }}

QPushButton {{ background: {CARD}; border: 1px solid {BORDER}; border-radius: 7px; padding: 7px 13px; color: {TEXT}; }}
QPushButton:hover {{ border-color: {ACCENT_DIM}; }}
QPushButton:pressed {{ background: {BG}; }}
QPushButton:disabled {{ color: #5b6272; border-color: {BORDER}; }}
QPushButton#primary {{ background: {ACCENT_DIM}; border-color: {ACCENT}; color: #eef6f3; font-weight: 600; }}
QPushButton#primary:hover {{ background: {ACCENT}; }}
QPushButton#danger {{ border-color: {DANGER}; color: {DANGER}; }}
QPushButton#nav {{ background: transparent; border: none; border-left: 3px solid transparent; border-radius: 0; padding: 9px 14px; text-align: left; color: {MUTED}; }}
QPushButton#nav:hover {{ color: {TEXT}; background: {CARD}; }}
QPushButton#nav:checked {{ color: {TEXT}; border-left: 3px solid {ACCENT}; background: {CARD}; font-weight: 600; padding-left: 13px; }}

QLineEdit, QComboBox, QSpinBox, QPlainTextEdit {{ background: {PANEL}; border: 1px solid {BORDER}; border-radius: 6px; padding: 6px 8px; selection-background-color: {ACCENT_DIM}; }}
QLineEdit:focus, QComboBox:focus, QSpinBox:focus {{ border-color: {ACCENT_DIM}; }}
QComboBox::drop-down {{ border: none; width: 18px; }}
QComboBox QAbstractItemView {{ background: {CARD}; border: 1px solid {BORDER}; selection-background-color: {ACCENT_DIM}; }}

QTableWidget {{ background: {PANEL}; border: 1px solid {BORDER}; border-radius: 8px; gridline-color: {BORDER}; selection-background-color: {CARD}; selection-color: {TEXT}; }}
QHeaderView::section {{ background: {PANEL}; color: {MUTED}; font-weight: 600; border: none; border-bottom: 1px solid {BORDER}; padding: 6px; font-size: 11px; text-transform: uppercase; }}
QTableWidget::item {{ padding: 4px; }}

QProgressBar {{ background: {PANEL}; border: 1px solid {BORDER}; border-radius: 4px; height: 6px; text-align: center; }}
QProgressBar::chunk {{ background: {ACCENT_DIM}; border-radius: 3px; }}

QCheckBox {{ spacing: 7px; }}
QCheckBox::indicator {{ width: 14px; height: 14px; border: 1px solid {BORDER}; border-radius: 3px; background: {PANEL}; }}
QCheckBox::indicator:checked {{ background: {ACCENT}; border-color: {ACCENT}; }}

QScrollArea {{ border: none; }}
QSplitter::handle {{ background: {BORDER}; height: 1px; }}
QPlainTextEdit#console {{ font-family: "JetBrains Mono", Menlo, monospace; font-size: 11.5px; color: #c3cad6; background: #0b0d11; border-top: 1px solid {BORDER}; }}
QToolTip {{ background: {CARD}; color: {TEXT}; border: 1px solid {BORDER}; padding: 4px; }}
QTableWidget QComboBox, QTableWidget QLineEdit {{ padding: 3px 6px; margin: 3px; min-height: 22px; }}
QTableWidget QComboBox QAbstractItemView {{ padding: 0; }}
QLabel#badge {{ border: 1px solid {BORDER}; border-radius: 4px; padding: 1px 5px; font-size: 10px; color: {MUTED}; text-transform: uppercase; }}
QLabel#badge_ok {{ border: 1px solid {ACCENT_DIM}; border-radius: 4px; padding: 1px 5px; font-size: 10px; color: {ACCENT}; }}
QLabel#badge_warn {{ border: 1px solid {WARN}; border-radius: 4px; padding: 1px 5px; font-size: 10px; color: {WARN}; }}
QLabel#badge_bad {{ border: 1px solid {DANGER}; border-radius: 4px; padding: 1px 5px; font-size: 10px; color: {DANGER}; }}

QSpinBox::up-button, QSpinBox::down-button {{ width: 14px; background: {CARD}; border: 1px solid {BORDER}; border-radius: 3px; margin: 1px; }}
QSpinBox::up-arrow {{ image: none; border-left: 3px solid transparent; border-right: 3px solid transparent; border-bottom: 4px solid {MUTED}; width: 0; height: 0; }}
QSpinBox::down-arrow {{ image: none; border-left: 3px solid transparent; border-right: 3px solid transparent; border-top: 4px solid {MUTED}; width: 0; height: 0; }}
QComboBox QAbstractItemView::item {{ padding: 5px 8px; }}
QLabel#placeholder {{ color: {MUTED}; font-size: 12px; }}
"""
