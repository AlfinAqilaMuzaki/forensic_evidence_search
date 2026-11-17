"""Tema tampilan: DARK dan LIGHT, gaya cyberpunk."""
from __future__ import annotations

from PySide6.QtCore import QSettings, Qt
from PySide6.QtGui import QColor, QFont, QIcon, QPainter, QPixmap

THEMES: dict[str, dict[str, str]] = {
    "dark": {
        "name": "DARK",
        "bg": "#050a14", "bg2": "#0a1424", "bg3": "#0e1c33", "bg4": "#13284a",
        "border": "#17406e", "border2": "#0f2a4a",
        "accent": "#00d4ff", "accent2": "#2f7bff", "accent3": "#7a5cff",
        "on_accent": "#02101f",
        "text": "#d8ecff", "muted": "#6f8fb3", "title": "#ffffff",
        "ok": "#00f0a0", "warn": "#ffb020", "bad": "#ff3d6e",
        "select": "#0f3e70", "mark": "#ffe066",
        "console_bg": "#030710", "console_fg": "#5cf2c4",
        "header_a": "#030814", "header_b": "#0a2350", "grid": "#0d3a6e",
        "stripe": "#d4a017",
    },
    "light": {
        "name": "LIGHT",
        "bg": "#f4ecdc", "bg2": "#fffaf0", "bg3": "#ffffff", "bg4": "#fbefd6",
        "border": "#d8b35a", "border2": "#ead6a6",
        "accent": "#e06a00", "accent2": "#b8860b", "accent3": "#8b4a00",
        "on_accent": "#ffffff",
        "text": "#2a1a04", "muted": "#8a6a35", "title": "#3a2200",
        "ok": "#14853b", "warn": "#c26a00", "bad": "#c62828",
        "select": "#ffd99a", "mark": "#ffd54a",
        "console_bg": "#2a1a04", "console_fg": "#ffd27a",
        "header_a": "#3b2405", "header_b": "#a86200", "grid": "#d9a441",
        "stripe": "#ffcc33",
    },
}

_current = "dark"


def current() -> str:
    return _current


def pal() -> dict[str, str]:
    return THEMES[_current]


def set_current(name: str) -> None:
    global _current
    _current = name if name in THEMES else "dark"
    QSettings("CyberForensic", "EvidenceSearch").setValue("theme", _current)


def load_saved() -> str:
    v = QSettings("CyberForensic", "EvidenceSearch").value("theme", "dark")
    set_current(str(v))
    return _current


HEAD_FONT = "Bahnschrift"
BODY_FONT = "Segoe UI"
MONO_FONT = "Consolas"
ICON_FONT = "Segoe Fluent Icons"   # fallback otomatis ke Segoe MDL2 Assets

# Glyph Segoe Fluent/MDL2
G = {
    "folder": "", "search": "", "play": "", "stop": "", "shield": "",
    "lock": "", "video": "", "audio": "", "image": "", "doc": "",
    "list": "", "log": "", "check": "", "warn": "", "theme": "",
    "open": "", "export": "", "hash": "", "refresh": "", "db": "",
    "scan": "", "eye": "", "fingerprint": "", "info": "", "save": "",
    "photo2": "", "text": "", "chip": "", "error": "", "clock": "",
}


def glyph_icon(name: str, color: str | None = None, size: int = 20) -> QIcon:
    ch = G.get(name, name)
    pm = QPixmap(size * 2, size * 2)
    pm.fill(Qt.transparent)
    p = QPainter(pm)
    p.setRenderHint(QPainter.Antialiasing)
    f = QFont(ICON_FONT)
    if not f.exactMatch():
        f = QFont("Segoe MDL2 Assets")
    f.setPixelSize(int(size * 1.5))
    p.setFont(f)
    p.setPen(QColor(color or pal()["accent"]))
    p.drawText(pm.rect(), Qt.AlignCenter, ch)
    p.end()
    return QIcon(pm)


def qss() -> str:
    c = pal()
    dark = _current == "dark"
    btn_grad = (f"qlineargradient(x1:0,y1:0,x2:1,y2:0, stop:0 {c['accent2']}, stop:1 {c['accent']})")
    return f"""
* {{ font-family: "{BODY_FONT}"; font-size: 10pt; }}
QMainWindow, QWidget#Root, QStackedWidget, QWidget#Page {{ background: {c['bg']}; }}
QWidget {{ color: {c['text']}; }}
QToolTip {{ background: {c['bg3']}; color: {c['text']}; border: 1px solid {c['accent']}; padding: 6px; }}

/* ---------- kartu ---------- */
QFrame#Card {{ background: {c['bg2']}; border: 1px solid {c['border2']}; border-top: 2px solid {c['accent']};
              border-radius: 2px; }}
QLabel#CardTitle {{ font-family: "{HEAD_FONT}"; font-size: 11pt; font-weight: 600; color: {c['accent']};
                   letter-spacing: 2px; background: transparent; }}
QLabel#CardHint, QLabel#Muted {{ color: {c['muted']}; background: transparent; }}
QLabel {{ background: transparent; }}
QLabel#PageTitle {{ font-family: "{HEAD_FONT}"; font-size: 17pt; font-weight: 600; color: {c['title']};
                   letter-spacing: 3px; }}
QLabel#PageSub {{ color: {c['muted']}; letter-spacing: 1px; }}
QFrame#Stat {{ background: {c['bg3']}; border: 1px solid {c['border2']}; border-left: 3px solid {c['accent']};
              border-radius: 2px; }}
QLabel#StatValue {{ font-family: "{HEAD_FONT}"; font-size: 19pt; font-weight: 600; color: {c['title']}; }}
QLabel#StatCaption {{ font-family: "{HEAD_FONT}"; font-size: 8.5pt; color: {c['muted']}; letter-spacing: 1px; }}
QLabel#Chip {{ font-family: "{HEAD_FONT}"; font-size: 8.5pt; letter-spacing: 1px; padding: 3px 9px;
              border-radius: 2px; border: 1px solid {c['ok']}; color: {c['ok']}; }}
QLabel#ChipWarn {{ font-family: "{HEAD_FONT}"; font-size: 8.5pt; letter-spacing: 1px; padding: 3px 9px;
                  border-radius: 2px; border: 1px solid {c['warn']}; color: {c['warn']}; }}
QLabel#HeaderChip {{ font-family: "{HEAD_FONT}"; font-size: 8.5pt; letter-spacing: 1px; padding: 4px 10px;
    color: #ffffff; background: rgba(0,0,0,110); border: 1px solid {c['stripe']}; border-radius: 2px; }}
QFrame#Credit {{ background: {c['bg3']}; border: 1px solid {c['border2']}; border-left: 3px solid {c['stripe'] if dark else c['accent']}; }}
QLabel#CreditName {{ font-family: "{HEAD_FONT}"; font-size: 10pt; font-weight: 700; color: {c['title']}; letter-spacing: 0.5px; }}
QScrollArea#SideScroll {{ background: {c['bg2']}; border: none; border-right: 1px solid {c['border']}; }}
QScrollArea#SideScroll > QWidget > QWidget {{ background: {c['bg2']}; }}
QLabel#PathLabel {{ font-family: "{MONO_FONT}"; font-size: 9pt; color: {c['muted']}; }}

/* ---------- sidebar ---------- */
QFrame#Sidebar {{ background: {c['bg2']}; border: none; }}
QPushButton#Nav {{ text-align: left; padding: 12px 14px 12px 14px; border: none; border-left: 3px solid transparent;
                  background: transparent; color: {c['muted']}; font-family: "{HEAD_FONT}"; font-size: 10.5pt;
                  letter-spacing: 0.5px; border-radius: 0; }}
QPushButton#Nav:hover {{ color: {c['text']}; background: {c['bg3']}; }}
QPushButton#Nav:checked {{ color: {c['accent']}; background: {c['select']}; border-left: 3px solid {c['accent']}; }}
QLabel#SideFoot {{ color: {c['muted']}; font-family: "{MONO_FONT}"; font-size: 8pt; }}

/* ---------- tombol ---------- */
QPushButton {{ background: {c['bg3']}; color: {c['text']}; border: 1px solid {c['border']}; border-radius: 2px;
              padding: 8px 14px; font-family: "{HEAD_FONT}"; font-size: 10pt; letter-spacing: 1px; }}
QPushButton:hover {{ border-color: {c['accent']}; color: {c['accent']}; background: {c['bg4']}; }}
QPushButton:pressed {{ background: {c['select']}; }}
QPushButton:disabled {{ color: {c['muted']}; border-color: {c['border2']}; background: {c['bg2']}; }}
QPushButton#Primary {{ background: {btn_grad}; color: {c['on_accent']}; border: 1px solid {c['accent']};
                      font-weight: 700; padding: 9px 18px; }}
QPushButton#Primary:hover {{ background: {c['accent']}; color: {c['on_accent']}; }}
QPushButton#Primary:disabled {{ background: {c['bg3']}; color: {c['muted']}; border-color: {c['border2']}; }}
QPushButton#Danger {{ border: 1px solid {c['bad']}; color: {c['bad']}; }}
QPushButton#Danger:hover {{ background: {c['bad']}; color: #ffffff; }}
QPushButton#Danger:disabled {{ border-color: {c['border2']}; color: {c['muted']}; }}
QPushButton#Ghost {{ background: transparent; border: 1px solid {c['border2']}; }}
QToolButton {{ background: transparent; border: none; }}

/* ---------- input ---------- */
QLineEdit, QComboBox, QSpinBox, QDoubleSpinBox {{ background: {c['bg3']}; color: {c['text']};
    border: 1px solid {c['border']}; border-radius: 2px; padding: 6px 8px; selection-background-color: {c['accent']};
    selection-color: {c['on_accent']}; }}
QLineEdit:focus, QComboBox:focus, QSpinBox:focus, QDoubleSpinBox:focus {{ border: 1px solid {c['accent']}; }}
QLineEdit#BigSearch {{ font-size: 13pt; padding: 10px 12px; border: 2px solid {c['accent']}; }}
QLineEdit[readOnly="true"] {{ color: {c['muted']}; font-family: "{MONO_FONT}"; }}
QComboBox::drop-down {{ border: none; width: 22px; }}
QComboBox QAbstractItemView {{ background: {c['bg3']}; border: 1px solid {c['accent']}; selection-background-color: {c['select']};
                              selection-color: {c['accent']}; outline: 0; }}
QCheckBox {{ spacing: 7px; background: transparent; }}
QCheckBox::indicator {{ width: 15px; height: 15px; border: 1px solid {c['border']}; background: {c['bg3']}; border-radius: 2px; }}
QCheckBox::indicator:hover {{ border-color: {c['accent']}; }}
QCheckBox::indicator:checked {{ background: {c['accent']}; border-color: {c['accent']};
    image: none; }}

/* ---------- progress ---------- */
QProgressBar {{ background: {c['bg3']}; border: 1px solid {c['border']}; border-radius: 2px; height: 20px;
               text-align: center; color: {c['title']}; font-family: "{HEAD_FONT}"; letter-spacing: 1px; }}
QProgressBar::chunk {{ background: {btn_grad}; }}

/* ---------- tabel & list ---------- */
QTableView, QListWidget, QTreeView {{ background: {c['bg2']}; alternate-background-color: {c['bg3']};
    border: 1px solid {c['border2']}; gridline-color: {c['border2']}; selection-background-color: {c['select']};
    selection-color: {c['title'] if dark else c['text']}; outline: 0; }}
QTableView::item {{ padding: 4px; }}
QHeaderView::section {{ background: {c['bg3']}; color: {c['accent']}; border: none; border-bottom: 2px solid {c['accent']};
    border-right: 1px solid {c['border2']}; padding: 7px 6px; font-family: "{HEAD_FONT}"; font-size: 9pt; letter-spacing: 1px; }}
QTableCornerButton::section {{ background: {c['bg3']}; border: none; }}
QListWidget#Grid::item {{ border: 1px solid {c['border2']}; background: {c['bg3']}; margin: 4px; padding: 6px; }}
QListWidget#Grid::item:selected {{ border: 2px solid {c['accent']}; background: {c['select']}; }}
QListWidget#Grid::item:hover {{ border: 1px solid {c['accent']}; }}

QTextBrowser, QPlainTextEdit {{ background: {c['bg3']}; border: 1px solid {c['border2']}; color: {c['text']};
    selection-background-color: {c['accent']}; selection-color: {c['on_accent']}; }}
QPlainTextEdit#Console {{ background: {c['console_bg']}; color: {c['console_fg']}; font-family: "{MONO_FONT}"; font-size: 9pt;
    border: 1px solid {c['border']}; }}

QSplitter::handle {{ background: {c['border2']}; }}
QSplitter::handle:hover {{ background: {c['accent']}; }}
QScrollBar:vertical {{ background: {c['bg2']}; width: 10px; margin: 0; }}
QScrollBar::handle:vertical {{ background: {c['border']}; min-height: 30px; }}
QScrollBar::handle:vertical:hover {{ background: {c['accent']}; }}
QScrollBar:horizontal {{ background: {c['bg2']}; height: 10px; margin: 0; }}
QScrollBar::handle:horizontal {{ background: {c['border']}; min-width: 30px; }}
QScrollBar::handle:horizontal:hover {{ background: {c['accent']}; }}
QScrollBar::add-line, QScrollBar::sub-line {{ width: 0; height: 0; }}
QScrollBar::add-page, QScrollBar::sub-page {{ background: none; }}
QStatusBar {{ background: {c['bg2']}; color: {c['muted']}; border-top: 1px solid {c['border']}; }}
QStatusBar QLabel {{ color: {c['muted']}; font-family: "{MONO_FONT}"; font-size: 8.5pt; padding: 0 8px; }}
QMessageBox {{ background: {c['bg2']}; }}
QScrollArea {{ background: transparent; border: none; }}
"""
