"""Komponen UI bersama: header bergaya cyberpunk, kartu, stat, tombol ber-ikon,
model tabel cepat (untuk puluhan ribu baris), dan worker thread."""
from __future__ import annotations

import logging
import math
import weakref
from typing import Any, Callable, Optional

from PySide6.QtCore import QAbstractTableModel, QModelIndex, QObject, QPointF, QRectF, QSize, Qt, QThread, Signal
from PySide6.QtGui import QBrush, QColor, QFont, QLinearGradient, QPainter, QPainterPath, QPen, QPixmap, QPolygonF
from PySide6.QtWidgets import (
    QFrame, QHBoxLayout, QLabel, QPushButton, QSizePolicy, QVBoxLayout, QWidget,
)

from . import theme

log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Registry ikon -> diwarnai ulang saat tema berganti
# ---------------------------------------------------------------------------
_ICON_REG: list[tuple[weakref.ref, str, str, int]] = []
_REPAINT_REG: list[weakref.ref] = []


def register_icon(w, glyph: str, color_key: str = "accent", size: int = 18) -> None:
    _ICON_REG.append((weakref.ref(w), glyph, color_key, size))
    w.setIcon(theme.glyph_icon(glyph, theme.pal()[color_key], size))
    w.setIconSize(QSize(size, size))


def refresh_theme_widgets() -> None:
    alive = []
    for ref, glyph, key, size in _ICON_REG:
        w = ref()
        if w is None:
            continue
        try:
            w.setIcon(theme.glyph_icon(glyph, theme.pal()[key], size))
            alive.append((ref, glyph, key, size))
        except RuntimeError:  # widget C++ sudah dihapus
            pass
    _ICON_REG[:] = alive
    keep = []
    for ref in _REPAINT_REG:
        w = ref()
        if w is not None:
            try:
                w.on_theme()
                keep.append(ref)
            except RuntimeError:
                pass
    _REPAINT_REG[:] = keep


def themed(w):
    """Daftarkan widget yang punya method on_theme() (dipanggil saat ganti tema)."""
    _REPAINT_REG.append(weakref.ref(w))
    return w


def button(text: str, glyph: str | None = None, kind: str = "", tip: str = "") -> QPushButton:
    b = QPushButton(text)
    if kind:
        b.setObjectName(kind)
    if glyph:
        key = {"Primary": "on_accent", "Danger": "bad"}.get(kind, "accent")
        register_icon(b, glyph, key)
    if tip:
        b.setToolTip(tip)
    b.setCursor(Qt.PointingHandCursor)
    return b


def label(text: str = "", obj: str = "", wrap: bool = False) -> QLabel:
    lb = QLabel(text)
    if obj:
        lb.setObjectName(obj)
    lb.setWordWrap(wrap)
    return lb


# ---------------------------------------------------------------------------
# Kartu
# ---------------------------------------------------------------------------
class Card(QFrame):
    def __init__(self, title: str = "", glyph: str | None = None, hint: str = "", parent=None):
        super().__init__(parent)
        self.setObjectName("Card")
        self.outer = QVBoxLayout(self)
        self.outer.setContentsMargins(14, 10, 14, 12)
        self.outer.setSpacing(8)
        if title:
            row = QHBoxLayout()
            row.setSpacing(8)
            if glyph:
                ic = QLabel()
                ic.setFixedSize(20, 20)
                self._icon_lbl, self._glyph = ic, glyph
                themed(self)
                self.on_theme()
                row.addWidget(ic)
            t = label(title.upper(), "CardTitle")
            row.addWidget(t)
            row.addStretch(1)
            self.header_row = row
            self.outer.addLayout(row)
            if hint:
                self.outer.addWidget(label(hint, "CardHint", wrap=True))
        self.body = QVBoxLayout()
        self.body.setSpacing(8)
        self.outer.addLayout(self.body, 1)

    def on_theme(self) -> None:
        if hasattr(self, "_icon_lbl"):
            self._icon_lbl.setPixmap(theme.glyph_icon(self._glyph, theme.pal()["accent"], 18).pixmap(18, 18))


class StatCard(QFrame):
    def __init__(self, caption: str, glyph: str, color_key: str = "accent"):
        super().__init__()
        self.setObjectName("Stat")
        self.setMinimumWidth(120)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        lay = QHBoxLayout(self)
        lay.setContentsMargins(12, 8, 12, 8)
        self.icon = QLabel()
        self.icon.setFixedSize(30, 30)
        self._glyph, self._key = glyph, color_key
        lay.addWidget(self.icon)
        col = QVBoxLayout()
        col.setSpacing(0)
        self.value = label("0", "StatValue")
        col.addWidget(self.value)
        col.addWidget(label(caption.upper(), "StatCaption"))
        lay.addLayout(col, 1)
        themed(self)
        self.on_theme()

    def on_theme(self) -> None:
        self.icon.setPixmap(theme.glyph_icon(self._glyph, theme.pal()[self._key], 26).pixmap(26, 26))

    def set(self, v: Any) -> None:
        self.value.setText(f"{v:,}".replace(",", ".") if isinstance(v, int) else str(v))


def chip(text: str, warn: bool = False) -> QLabel:
    return label(text, "ChipWarn" if warn else "Chip")


# ---------------------------------------------------------------------------
# Header bergaya cyberpunk (digambar manual)
# ---------------------------------------------------------------------------
class Emblem(QWidget):
    """Lambang perisai heksagonal + lensa (generik). Bila ada file `logo.png`
    di folder aplikasi, logo itu yang dipakai."""

    def __init__(self, size: int = 58, logo: Optional[str] = None):
        super().__init__()
        self.setFixedSize(size, size)
        self._logo = QPixmap(logo) if logo else QPixmap()

    def paintEvent(self, _e):  # noqa: N802
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        c = theme.pal()
        r = self.rect().adjusted(3, 3, -3, -3)
        if not self._logo.isNull():
            p.drawPixmap(r, self._logo.scaled(r.size(), Qt.KeepAspectRatio, Qt.SmoothTransformation))
            return
        cx, cy, rad = r.center().x(), r.center().y(), r.width() / 2
        hexa = QPolygonF([QPointF(cx + rad * math.cos(math.radians(60 * i - 90)),
                                  cy + rad * math.sin(math.radians(60 * i - 90))) for i in range(6)])
        g = QLinearGradient(r.topLeft(), r.bottomRight())
        g.setColorAt(0, QColor(c["accent2"]))
        g.setColorAt(1, QColor(c["header_a"]))
        p.setBrush(QBrush(g))
        p.setPen(QPen(QColor(c["stripe"]), 2))
        p.drawPolygon(hexa)
        inner = QPolygonF([QPointF(cx + rad * 0.72 * math.cos(math.radians(60 * i - 90)),
                                   cy + rad * 0.72 * math.sin(math.radians(60 * i - 90))) for i in range(6)])
        p.setBrush(Qt.NoBrush)
        p.setPen(QPen(QColor(c["accent"]), 1.2))
        p.drawPolygon(inner)
        # lensa pencari
        p.setPen(QPen(QColor("#ffffff"), 2.6))
        lr = rad * 0.32
        p.drawEllipse(QPointF(cx - 3, cy - 3), lr, lr)
        p.drawLine(QPointF(cx - 3 + lr * 0.7, cy - 3 + lr * 0.7), QPointF(cx + rad * 0.42, cy + rad * 0.42))
        p.setPen(QPen(QColor(c["stripe"]), 1.6))
        p.drawLine(QPointF(cx - 3 - lr * 0.5, cy - 3), QPointF(cx - 3 + lr * 0.5, cy - 3))


class HeaderBar(QWidget):
    def __init__(self, title: str, subtitle: str, logo: Optional[str] = None, author: str = ""):
        super().__init__()
        self.setFixedHeight(96)
        self._title, self._sub, self._author = title, subtitle, author
        lay = QHBoxLayout(self)
        lay.setContentsMargins(18, 10, 18, 10)
        lay.setSpacing(14)
        self.emblem = Emblem(66, logo)
        lay.addWidget(self.emblem)
        lay.addSpacing(330)  # ruang teks judul (digambar di paintEvent)
        lay.addStretch(1)
        self.right = QHBoxLayout()
        self.right.setSpacing(8)
        lay.addLayout(self.right)
        themed(self)

    def on_theme(self) -> None:
        self.update()
        self.emblem.update()

    def paintEvent(self, _e):  # noqa: N802
        c = theme.pal()
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        w, h = self.width(), self.height()
        g = QLinearGradient(0, 0, w, 0)
        g.setColorAt(0, QColor(c["header_a"]))
        g.setColorAt(0.65, QColor(c["header_b"]))
        g.setColorAt(1, QColor(c["header_a"]))
        p.fillRect(self.rect(), g)
        # grid siber
        gc = QColor(c["grid"])
        gc.setAlpha(55)
        p.setPen(QPen(gc, 1))
        for x in range(0, w, 22):
            p.drawLine(x, 0, x, h)
        for y in range(0, h, 22):
            p.drawLine(0, y, w, y)
        # garis diagonal aksen
        sc = QColor(c["stripe"])
        p.setPen(Qt.NoPen)
        for i, a in enumerate((200, 120, 60)):
            sc.setAlpha(a)
            p.setBrush(sc)
            x0 = int(w * 0.50) + i * 26
            path = QPainterPath()
            path.moveTo(x0, h)
            path.lineTo(x0 + 14, h)
            path.lineTo(x0 + 14 + h * 0.6, 0)
            path.lineTo(x0 + h * 0.6, 0)
            path.closeSubpath()
            p.drawPath(path)
        # garis bawah neon
        p.fillRect(0, h - 3, w, 3, QColor(c["accent"]))
        p.fillRect(0, h - 3, 260, 3, QColor(c["stripe"]))
        # teks judul
        x = 18 + 66 + 16
        f = QFont(theme.HEAD_FONT)
        f.setPixelSize(26)
        f.setWeight(QFont.Bold)
        f.setLetterSpacing(QFont.AbsoluteSpacing, 3)
        p.setFont(f)
        glow = QColor(c["accent"])
        glow.setAlpha(90)
        p.setPen(glow)
        p.drawText(QRectF(x + 1, 9, 700, 36), Qt.AlignLeft | Qt.AlignVCenter, self._title)
        p.setPen(QColor("#ffffff"))
        p.drawText(QRectF(x, 8, 700, 36), Qt.AlignLeft | Qt.AlignVCenter, self._title)
        f2 = QFont(theme.HEAD_FONT)
        f2.setPixelSize(12)
        f2.setLetterSpacing(QFont.AbsoluteSpacing, 2.5)
        p.setFont(f2)
        p.setPen(QColor(c["stripe"]))
        p.drawText(QRectF(x, 42, 800, 20), Qt.AlignLeft | Qt.AlignVCenter, self._sub)
        if self._author:
            f3 = QFont(theme.MONO_FONT)
            f3.setPixelSize(11)
            f3.setLetterSpacing(QFont.AbsoluteSpacing, 1)
            p.setFont(f3)
            col = QColor("#ffffff")
            col.setAlpha(200)
            p.setPen(col)
            p.drawText(QRectF(x, 64, 900, 18), Qt.AlignLeft | Qt.AlignVCenter, self._author)


# ---------------------------------------------------------------------------
# Model tabel cepat
# ---------------------------------------------------------------------------
class RowsModel(QAbstractTableModel):
    def __init__(self, headers: list[str], parent=None):
        super().__init__(parent)
        self.headers = headers
        self.rows: list[list[Any]] = []
        self.payload: list[Any] = []
        self.colors: dict[int, Callable[[list], Optional[str]]] = {}
        self.mono_cols: set[int] = set()
        self.align_right: set[int] = set()

    def set_rows(self, rows: list[list[Any]], payload: Optional[list[Any]] = None) -> None:
        self.beginResetModel()
        self.rows = rows
        self.payload = payload if payload is not None else [None] * len(rows)
        self.endResetModel()

    def rowCount(self, parent=QModelIndex()):  # noqa: N802
        return 0 if parent.isValid() else len(self.rows)

    def columnCount(self, parent=QModelIndex()):  # noqa: N802
        return len(self.headers)

    def headerData(self, s, o, role=Qt.DisplayRole):  # noqa: N802
        if role == Qt.DisplayRole and o == Qt.Horizontal:
            return self.headers[s].upper()
        return None

    def data(self, idx, role=Qt.DisplayRole):
        if not idx.isValid():
            return None
        v = self.rows[idx.row()][idx.column()]
        if role == Qt.DisplayRole:
            return "" if v is None else str(v).replace("\n", " ")
        if role == Qt.ToolTipRole:
            s = "" if v is None else str(v)
            return s[:1500] if len(s) > 40 else None
        if role == Qt.ForegroundRole and idx.column() in self.colors:
            col = self.colors[idx.column()](self.rows[idx.row()])
            return QColor(theme.pal()[col]) if col else None
        if role == Qt.FontRole and idx.column() in self.mono_cols:
            f = QFont(theme.MONO_FONT)
            f.setPointSizeF(8.5)
            return f
        if role == Qt.TextAlignmentRole and idx.column() in self.align_right:
            return int(Qt.AlignRight | Qt.AlignVCenter)
        return None

    def sort(self, column, order=Qt.AscendingOrder):
        if not self.rows:
            return
        self.layoutAboutToBeChanged.emit()
        pairs = list(zip(self.rows, self.payload))

        def key(p):
            v = p[0][column]
            return (0, v) if isinstance(v, (int, float)) else (1, str(v or "").lower())
        pairs.sort(key=key, reverse=(order == Qt.DescendingOrder))
        self.rows = [p[0] for p in pairs]
        self.payload = [p[1] for p in pairs]
        self.layoutChanged.emit()


# ---------------------------------------------------------------------------
# Worker thread generik
# ---------------------------------------------------------------------------
class Worker(QObject):
    progress = Signal(int, int, str)
    log = Signal(str)
    finished = Signal(object)
    error = Signal(str)

    def __init__(self, fn):
        super().__init__()
        self.fn = fn
        self._stop = False

    def stop(self) -> None:
        self._stop = True

    def run(self) -> None:
        try:
            res = self.fn(lambda m: self.log.emit(m), lambda d, t, m: self.progress.emit(d, t, m),
                          lambda: self._stop)
            self.finished.emit(res)
        except Exception as exc:  # noqa: BLE001
            log.exception("Tugas gagal")
            self.error.emit(f"{type(exc).__name__}: {exc}")


class TaskRunner(QObject):
    """Menjalankan satu tugas berat di thread terpisah; sinyal ke GUI aman."""
    busy_changed = Signal(bool)
    progress = Signal(int, int, str)
    log = Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._thread: Optional[QThread] = None
        self._worker: Optional[Worker] = None
        self._on_done = None
        self._on_err = None

    def busy(self) -> bool:
        return self._thread is not None and self._thread.isRunning()

    def start(self, fn, on_done, on_error=None) -> bool:
        if self.busy():
            return False
        self._on_done, self._on_err = on_done, on_error
        self._thread = QThread()
        self._worker = Worker(fn)
        self._worker.moveToThread(self._thread)
        self._thread.started.connect(self._worker.run)
        self._worker.progress.connect(self.progress)
        self._worker.log.connect(self.log)
        self._worker.finished.connect(self._done)
        self._worker.error.connect(self._error)
        self._worker.finished.connect(self._thread.quit, Qt.DirectConnection)
        self._worker.error.connect(self._thread.quit, Qt.DirectConnection)
        self._thread.finished.connect(self._thread_finished)
        self._thread.start()
        self.busy_changed.emit(True)
        return True

    def _done(self, res):
        if self._on_done:
            self._on_done(res)

    def _error(self, msg):
        if self._on_err:
            self._on_err(msg)

    def _thread_finished(self):
        self.busy_changed.emit(False)

    def stop(self) -> None:
        if self._worker:
            self._worker.stop()

    def shutdown(self, wait_ms: int = 20000) -> None:
        self.stop()
        if self._thread and self._thread.isRunning():
            self._thread.quit()
            self._thread.wait(wait_ms)
