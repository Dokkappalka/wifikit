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

def dark_palette():
    """Тёмная палитра приложения.

    Нужна именно палитра, а не только QSS: непокрытые стилями места (рамка попапа
    QComboBox, меню, подсказки) берут цвета из палитры. Без неё вокруг списков
    появляются белые полосы.
    """
    from PySide6.QtGui import QColor, QPalette

    palette = QPalette()
    colours = {
        QPalette.Window: BG,
        QPalette.WindowText: TEXT,
        QPalette.Base: PANEL,
        QPalette.AlternateBase: CARD,
        QPalette.ToolTipBase: CARD,
        QPalette.ToolTipText: TEXT,
        QPalette.Text: TEXT,
        QPalette.Button: CARD,
        QPalette.ButtonText: TEXT,
        QPalette.BrightText: "#ffffff",
        QPalette.Link: ACCENT,
        QPalette.Highlight: ACCENT_DIM,
        QPalette.HighlightedText: "#eef6f3",
        QPalette.PlaceholderText: MUTED,
    }
    for role, value in colours.items():
        palette.setColor(role, QColor(value))
    for role in (QPalette.WindowText, QPalette.Text, QPalette.ButtonText):
        palette.setColor(QPalette.Disabled, role, QColor("#5b6272"))
    return palette


QSS = f"""
/* Только документированные классы и субконтролы Qt.
   Приватные виджеты (QComboBoxPrivateContainer и подобные) и стилизация
   внутренних QFrame попапа не поддерживаются и роняют QStyleSheetStyle. */

QMainWindow, QDialog, QWidget#root {{ background: {BG}; }}
QWidget {{ color: {TEXT}; font-size: 13px; }}
QLabel, QCheckBox, QRadioButton {{ background: transparent; }}
QFrame#sidebar {{ background: {PANEL}; border-right: 1px solid {BORDER}; }}
QFrame#topbar {{ background: {PANEL}; border-bottom: 1px solid {BORDER}; }}
QStatusBar {{ background: {PANEL}; border-top: 1px solid {BORDER}; }}
QStatusBar QLabel {{ color: #b6bdcb; padding-left: 8px; font-size: 12px; }}

QLabel#brand {{ font-size: 15px; font-weight: 600; }}
QLabel#muted, QLabel.muted {{ color: {MUTED}; }}
QLabel:disabled {{ color: #5b6272; }}
QLabel#h1 {{ font-size: 17px; font-weight: 600; }}
QLabel#h2 {{ font-size: 11px; color: {MUTED}; font-weight: 600; }}
QLabel#mono, QLabel.mono {{ font-family: "JetBrains Mono", "SF Mono", Menlo, monospace; }}
QLabel#ok {{ color: {ACCENT}; }}
QLabel#bad {{ color: {DANGER}; }}
QLabel#warn {{ color: {WARN}; }}
QLabel#badge, QLabel#badge_ok, QLabel#badge_warn, QLabel#badge_bad {{
  border: 1px solid {BORDER}; border-radius: 4px; padding: 1px 5px; font-size: 11px; color: {MUTED}; }}
QLabel#badge_ok {{ border-color: {ACCENT_DIM}; color: {ACCENT}; }}
QLabel#badge_warn {{ border-color: {WARN}; color: {WARN}; }}
QLabel#badge_bad {{ border-color: {DANGER}; color: {DANGER}; }}

QPushButton {{ background: {CARD}; border: 1px solid {BORDER}; border-radius: 6px; padding: 7px 13px; color: {TEXT}; }}
QPushButton:hover {{ border-color: {ACCENT_DIM}; }}
QPushButton:pressed {{ background: {BG}; }}
QPushButton:disabled {{ color: #5b6272; }}
QPushButton#primary {{ background: {ACCENT_DIM}; border-color: {ACCENT}; color: #eef6f3; font-weight: 600; }}
QPushButton#primary:hover {{ background: {ACCENT}; }}
QPushButton#danger {{ border-color: {DANGER}; color: {DANGER}; }}
QPushButton#nav {{ background: transparent; border: none; border-left: 3px solid transparent; border-radius: 0;
  padding: 9px 14px; text-align: left; color: {MUTED}; }}
QPushButton#nav:hover {{ color: {TEXT}; background: {CARD}; }}
QPushButton#nav:checked {{ color: {TEXT}; border-left: 3px solid {ACCENT}; background: {CARD}; font-weight: 600; }}

QLineEdit, QComboBox, QSpinBox, QPlainTextEdit {{
  background: {PANEL}; border: 1px solid {BORDER}; border-radius: 6px; padding: 6px 8px;
  selection-background-color: {ACCENT_DIM}; }}
QLineEdit:focus, QComboBox:focus, QSpinBox:focus {{ border-color: {ACCENT_DIM}; }}
QComboBox {{ padding: 5px 22px 5px 9px; min-height: 20px; }}
QComboBox::drop-down {{ subcontrol-origin: padding; subcontrol-position: center right; width: 18px; border: none; }}
QComboBox QAbstractItemView {{
  background: {CARD}; border: 1px solid {BORDER}; padding: 3px;
  selection-background-color: {ACCENT_DIM}; selection-color: {TEXT}; }}

QTableWidget {{
  background: {PANEL}; border: 1px solid {BORDER}; gridline-color: {BORDER};
  selection-background-color: {CARD}; selection-color: {TEXT}; }}
QHeaderView::section {{
  background: {PANEL}; color: {MUTED}; border: none; border-bottom: 1px solid {BORDER};
  padding: 6px; font-size: 11px; font-weight: 600; }}
QTableWidget::item {{ padding: 4px; }}
QTableWidget QComboBox, QTableWidget QLineEdit {{ padding: 3px 6px; margin: 3px; min-height: 22px; }}

QProgressBar {{ background: {PANEL}; border: 1px solid {BORDER}; border-radius: 4px; height: 6px; text-align: center; }}
QProgressBar::chunk {{ background: {ACCENT_DIM}; border-radius: 3px; }}

QCheckBox {{ spacing: 7px; }}
QCheckBox::indicator {{ width: 14px; height: 14px; border: 1px solid {BORDER}; border-radius: 3px; background: {PANEL}; }}
QCheckBox::indicator:checked {{ background: {ACCENT}; border-color: {ACCENT}; }}

QPlainTextEdit#console {{ font-family: "JetBrains Mono", Menlo, monospace; font-size: 11px;
  color: #c3cad6; background: #0b0d11; }}
QToolTip {{ background: {CARD}; color: {TEXT}; border: 1px solid {BORDER}; padding: 4px; }}
"""
