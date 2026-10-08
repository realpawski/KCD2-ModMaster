"""Design tokens and application stylesheet."""
from __future__ import annotations

from pathlib import Path

ASSETS = (Path(__file__).resolve().parent / "assets").as_posix()

BG0 = "#0b0c10"
BG1 = "#111319"
BG2 = "#171a22"
BG3 = "#1e222c"
BG4 = "#272c38"
BORDER = "#232733"
BORDER_LIGHT = "#343a48"
TEXT = "#e9ebef"
TEXT_DIM = "#a2a8b5"
TEXT_MUTED = "#6c7383"
ACCENT = "#d6a54e"
ACCENT_HOVER = "#e3b663"
ACCENT_PRESSED = "#bf8f3d"
ACCENT_TEXT = "#16110a"
ACCENT_BG = "#2a2416"
OK = "#58b886"
WARN = "#e88a4c"
ERR = "#e35d5d"
INFO = "#6aa7e6"
ACCENT_DIM = TEXT_DIM

FONT = '"Segoe UI Variable Text", "Segoe UI", "Inter", sans-serif'
RADIUS = 8


def pill(color: str, filled: bool = False) -> str:
    """Inline style for a small status pill."""
    if filled:
        return (f"background: {color}; color: {ACCENT_TEXT}; border-radius: 9px; "
                "padding: 2px 9px; font-size: 8pt; font-weight: 700;")
    return (f"background: transparent; color: {color}; border: 1px solid {color}; "
            "border-radius: 9px; padding: 1px 8px; font-size: 8pt; font-weight: 600;")


QSS = f"""
* {{
    font-family: {FONT};
    font-size: 9.75pt;
    color: {TEXT};
    outline: none;
}}

QMainWindow, QWidget#Root, QWidget#Page, QStackedWidget {{
    background: {BG0};
}}

QDialog {{
    background: {BG1};
}}

QScrollArea, QScrollArea > QWidget, QScrollArea > QWidget > QWidget {{
    background: transparent;
    border: none;
}}

QScrollArea#InspectorArea, QWidget#InspectorBody {{
    background: {BG1};
}}

QToolTip {{
    background: {BG3};
    color: {TEXT};
    border: 1px solid {BORDER_LIGHT};
    border-radius: 6px;
    padding: 6px 10px;
    font-size: 9pt;
}}

/* Sidebar */
QFrame#Sidebar {{
    background: {BG1};
    border-right: 1px solid {BORDER};
}}

QLabel#Brand {{
    font-size: 11.5pt;
    font-weight: 700;
    color: {TEXT};
}}

QLabel#BrandSub {{
    color: {TEXT_MUTED};
    font-size: 7.5pt;
    font-weight: 600;
    letter-spacing: 1px;
}}

QListWidget#Nav {{
    background: transparent;
    border: none;
    padding: 4px 10px;
}}

QListWidget#Nav::item {{
    padding: 8px 12px;
    border-radius: 7px;
    margin: 1px 0;
    color: {TEXT_DIM};
}}

QListWidget#Nav::item:hover {{
    background: {BG3};
    color: {TEXT};
}}

QListWidget#Nav::item:selected {{
    background: {ACCENT_BG};
    color: {ACCENT};
    font-weight: 600;
}}

QListWidget#Nav::item:disabled {{
    color: {TEXT_MUTED};
    background: transparent;
    font-size: 7.5pt;
    font-weight: 700;
    letter-spacing: 1px;
    padding: 14px 12px 4px 12px;
}}

/* Typography */
QLabel#H1 {{
    font-size: 17pt;
    font-weight: 700;
    color: {TEXT};
}}

QLabel#H2 {{
    font-size: 11.5pt;
    font-weight: 600;
    color: {TEXT};
}}

QLabel#H3 {{
    font-size: 10pt;
    font-weight: 600;
    color: {TEXT};
}}

QLabel#Section {{
    font-size: 7.75pt;
    font-weight: 700;
    letter-spacing: 1.2px;
    color: {TEXT_MUTED};
}}

QLabel#Dim {{
    color: {TEXT_DIM};
}}

QLabel#Muted {{
    color: {TEXT_MUTED};
    font-size: 8.75pt;
}}

QLabel#Mono {{
    font-family: "Cascadia Mono", "Consolas", monospace;
    font-size: 8.75pt;
    color: {TEXT_DIM};
}}

QLabel#Badge {{
    background: {BG3};
    color: {TEXT_DIM};
    border: 1px solid {BORDER_LIGHT};
    border-radius: 9px;
    padding: 2px 9px;
    font-size: 8pt;
    font-weight: 600;
}}

QLabel#BadgeAccent {{
    background: {ACCENT_BG};
    color: {ACCENT};
    border: 1px solid {ACCENT_PRESSED};
    border-radius: 9px;
    padding: 2px 9px;
    font-size: 8pt;
    font-weight: 700;
}}

QLabel#Error {{ color: {ERR}; }}
QLabel#Warn {{ color: {WARN}; }}
QLabel#Ok {{ color: {OK}; }}

/* Surfaces */
QFrame#Card {{
    background: {BG1};
    border: 1px solid {BORDER};
    border-radius: {RADIUS + 2}px;
}}

QFrame#CardInset {{
    background: {BG2};
    border: 1px solid {BORDER};
    border-radius: {RADIUS}px;
}}

QFrame#Divider {{
    background: {BORDER};
    max-height: 1px;
    min-height: 1px;
    border: none;
}}

QFrame#PreviewToolbar {{
    background: {BG1};
    border-bottom: 1px solid {BORDER};
}}

QFrame#PreviewToolbar QPushButton {{
    padding: 4px 10px;
    min-height: 22px;
    font-size: 8.75pt;
}}

QFrame#PreviewHud {{
    background: {BG1};
    border-top: 1px solid {BORDER};
}}

QGroupBox {{
    background: {BG1};
    border: 1px solid {BORDER};
    border-radius: {RADIUS + 2}px;
    margin-top: 22px;
    padding: 16px 14px 12px 14px;
    font-weight: 600;
}}

QGroupBox::title {{
    subcontrol-origin: margin;
    subcontrol-position: top left;
    left: 2px;
    padding: 0 4px 4px 4px;
    color: {TEXT_MUTED};
    font-size: 7.75pt;
    font-weight: 700;
    letter-spacing: 1.2px;
}}

/* Inputs */
QLineEdit, QComboBox, QSpinBox, QDoubleSpinBox, QPlainTextEdit, QTextEdit {{
    background: {BG2};
    border: 1px solid {BORDER_LIGHT};
    border-radius: 6px;
    padding: 6px 9px;
    selection-background-color: {ACCENT_PRESSED};
    selection-color: {ACCENT_TEXT};
}}

QLineEdit, QComboBox, QSpinBox, QDoubleSpinBox {{
    min-height: 20px;
}}

QLineEdit:hover, QComboBox:hover, QSpinBox:hover, QDoubleSpinBox:hover,
QPlainTextEdit:hover, QTextEdit:hover {{
    border-color: #454c5d;
}}

QLineEdit:focus, QComboBox:focus, QSpinBox:focus, QDoubleSpinBox:focus,
QPlainTextEdit:focus, QTextEdit:focus {{
    border-color: {ACCENT};
}}

QLineEdit:read-only {{
    background: {BG1};
    color: {TEXT_DIM};
}}

QLineEdit:disabled, QComboBox:disabled, QSpinBox:disabled, QDoubleSpinBox:disabled {{
    color: {TEXT_MUTED};
    background: {BG1};
    border-color: {BORDER};
}}

QLineEdit[changed="true"], QSpinBox[changed="true"], QDoubleSpinBox[changed="true"],
QComboBox[changed="true"] {{
    border-color: {ACCENT_PRESSED};
    background: {ACCENT_BG};
}}

QLineEdit[invalid="true"], QSpinBox[invalid="true"], QDoubleSpinBox[invalid="true"] {{
    border-color: {ERR};
}}

QLineEdit#Search {{
    background: {BG1};
    border-radius: 8px;
    padding: 9px 12px;
    font-size: 10.5pt;
}}

QSpinBox::up-button, QDoubleSpinBox::up-button,
QSpinBox::down-button, QDoubleSpinBox::down-button {{
    width: 16px;
    border: none;
    background: transparent;
}}

QComboBox::drop-down {{
    border: none;
    width: 22px;
}}

QComboBox QAbstractItemView {{
    background: {BG2};
    border: 1px solid {BORDER_LIGHT};
    border-radius: 6px;
    padding: 4px;
    selection-background-color: {BG4};
    selection-color: {TEXT};
}}

QCheckBox {{
    spacing: 8px;
    color: {TEXT};
}}

QCheckBox::indicator {{
    width: 16px;
    height: 16px;
    border-radius: 4px;
    border: 1px solid {BORDER_LIGHT};
    background: {BG2};
}}

QCheckBox::indicator:hover {{
    border-color: {ACCENT};
}}

QCheckBox::indicator:checked {{
    background: {ACCENT};
    border-color: {ACCENT};
    image: url({ASSETS}/check.svg);
}}

QCheckBox::indicator:disabled {{
    background: {BG1};
    border-color: {BORDER};
}}

QCheckBox::indicator:checked:disabled {{
    background: {BG4};
}}

QRadioButton {{
    spacing: 8px;
    color: {TEXT};
}}

QRadioButton::indicator {{
    width: 16px;
    height: 16px;
    border-radius: 8px;
    border: 1px solid {BORDER_LIGHT};
    background: {BG2};
}}

QRadioButton::indicator:hover {{
    border-color: {ACCENT};
}}

QRadioButton::indicator:checked {{
    background: {ACCENT};
    border-color: {ACCENT};
    image: url({ASSETS}/radio.svg);
}}

/* Buttons */
QPushButton, QToolButton {{
    background: {BG2};
    border: 1px solid {BORDER_LIGHT};
    border-radius: 7px;
    padding: 7px 14px;
    min-height: 18px;
    color: {TEXT};
    font-weight: 500;
}}

QPushButton:hover, QToolButton:hover {{
    background: {BG3};
    border-color: #454c5d;
}}

QPushButton:pressed, QToolButton:pressed {{
    background: {BG4};
}}

QPushButton:checked {{
    background: {ACCENT_BG};
    border-color: {ACCENT_PRESSED};
    color: {ACCENT};
}}

QPushButton:disabled, QToolButton:disabled {{
    color: {TEXT_MUTED};
    background: {BG1};
    border-color: {BORDER};
}}

QPushButton#Primary {{
    background: {ACCENT};
    border: 1px solid {ACCENT};
    color: {ACCENT_TEXT};
    font-weight: 700;
}}

QPushButton#Primary:hover {{
    background: {ACCENT_HOVER};
    border-color: {ACCENT_HOVER};
}}

QPushButton#Primary:pressed {{
    background: {ACCENT_PRESSED};
}}

QPushButton#Primary:disabled {{
    background: {BG3};
    border-color: {BORDER};
    color: {TEXT_MUTED};
}}

QPushButton#Ghost {{
    background: transparent;
    border: 1px solid transparent;
    color: {TEXT_DIM};
}}

QPushButton#Ghost:hover {{
    background: {BG3};
    color: {TEXT};
}}

QPushButton#Danger {{
    background: transparent;
    border: 1px solid #5a2c2c;
    color: {ERR};
}}

QPushButton#Danger:hover {{
    background: #2a1717;
    border-color: {ERR};
}}

QPushButton#Danger:disabled {{
    color: {TEXT_MUTED};
    border-color: {BORDER};
}}

QFrame#Tile {{
    background: {BG2};
    border: 1px solid {BORDER};
    border-radius: {RADIUS + 2}px;
}}

QFrame#Tile:hover {{
    border-color: {ACCENT_PRESSED};
    background: {BG3};
}}

QFrame#Tile QLabel {{
    background: transparent;
    border: none;
}}

/* Tabs */
QTabWidget::pane {{
    border: none;
    background: transparent;
    top: -1px;
}}

QTabBar {{
    background: transparent;
}}

QTabBar::tab {{
    background: transparent;
    color: {TEXT_DIM};
    padding: 9px 16px;
    border: none;
    border-bottom: 2px solid transparent;
    font-weight: 600;
    margin-right: 4px;
}}

QTabBar::tab:hover {{
    color: {TEXT};
}}

QTabBar::tab:selected {{
    color: {ACCENT};
    border-bottom: 2px solid {ACCENT};
}}

/* Tables and lists */
QTableView, QTreeView, QListWidget, QListView {{
    background: {BG1};
    alternate-background-color: #13151c;
    border: 1px solid {BORDER};
    border-radius: {RADIUS}px;
    gridline-color: transparent;
    selection-background-color: {ACCENT_BG};
    selection-color: {TEXT};
}}

QTableView::item, QTreeView::item {{
    padding: 0 8px;
    border: none;
}}

QTableView::item:selected, QTreeView::item:selected, QListWidget::item:selected {{
    background: {ACCENT_BG};
    color: {TEXT};
}}

QTableView::item:hover, QTreeView::item:hover {{
    background: {BG3};
}}

QListWidget::item {{
    padding: 8px 10px;
    border-radius: 6px;
}}

QListWidget#ModList {{
    padding: 6px;
}}

QListWidget#ModList::item {{
    padding: 0;
    margin: 0 0 4px 0;
    border-radius: 8px;
}}

QListWidget::item:hover {{
    background: {BG3};
}}

QHeaderView {{
    background: transparent;
}}

QHeaderView::section {{
    background: {BG1};
    color: {TEXT_MUTED};
    border: none;
    border-bottom: 1px solid {BORDER};
    padding: 9px 8px;
    font-size: 7.75pt;
    font-weight: 700;
    letter-spacing: 0.8px;
}}

QHeaderView::up-arrow, QHeaderView::down-arrow {{
    subcontrol-origin: padding;
    subcontrol-position: center right;
    width: 9px;
    height: 9px;
    right: 6px;
}}

QTableCornerButton::section {{
    background: {BG1};
    border: none;
}}

QPlainTextEdit#Console, QPlainTextEdit#Log {{
    background: {BG0};
    border: none;
    border-radius: 0;
    font-family: "Cascadia Mono", "Consolas", monospace;
    font-size: 8.75pt;
    color: {TEXT_DIM};
    padding: 8px 12px;
}}

QPlainTextEdit#Log {{
    background: {BG1};
    border: 1px solid {BORDER};
    border-radius: {RADIUS}px;
}}

QProgressBar {{
    background: {BG2};
    border: none;
    border-radius: 3px;
    max-height: 6px;
    text-align: center;
    color: transparent;
}}

QProgressBar::chunk {{
    background: {ACCENT};
    border-radius: 3px;
}}

/* Scrollbars */
QScrollBar:vertical {{
    background: transparent;
    width: 10px;
    margin: 2px;
}}

QScrollBar::handle:vertical {{
    background: {BG4};
    border-radius: 3px;
    min-height: 32px;
}}

QScrollBar::handle:vertical:hover {{
    background: #3a4050;
}}

QScrollBar:horizontal {{
    background: transparent;
    height: 10px;
    margin: 2px;
}}

QScrollBar::handle:horizontal {{
    background: {BG4};
    border-radius: 3px;
    min-width: 32px;
}}

QScrollBar::add-line, QScrollBar::sub-line,
QScrollBar::add-page, QScrollBar::sub-page {{
    background: none;
    border: none;
    width: 0;
    height: 0;
}}

QMenu {{
    background: {BG2};
    border: 1px solid {BORDER_LIGHT};
    border-radius: 8px;
    padding: 4px;
}}

QMenu::item {{
    padding: 7px 22px 7px 12px;
    border-radius: 5px;
}}

QMenu::item:selected {{
    background: {BG4};
}}

QMenu::separator {{
    height: 1px;
    background: {BORDER};
    margin: 4px 6px;
}}

QSplitter::handle {{
    background: {BG0};
}}

QSplitter::handle:horizontal {{
    width: 6px;
}}

QSplitter::handle:vertical {{
    height: 6px;
}}

QSplitter::handle:hover {{
    background: {BORDER_LIGHT};
}}

QStatusBar {{
    background: {BG1};
    color: {TEXT_MUTED};
    border-top: 1px solid {BORDER};
    font-size: 8.5pt;
}}

QMessageBox QLabel {{
    color: {TEXT};
}}
"""
