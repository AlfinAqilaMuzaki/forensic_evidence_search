"""Jendela utama: header cyberpunk, bar folder bukti, navigasi samping, 5 modul.

Semua operasi berat berjalan di thread terpisah (lihat ui/widgets.TaskRunner)
supaya UI tetap responsif pada ribuan/ratusan ribu file.
"""
from __future__ import annotations

import logging
import os
import sys

from PySide6.QtCore import Qt
from PySide6.QtGui import QFont, QIcon
from PySide6.QtWidgets import (
    QApplication, QButtonGroup, QFileDialog, QFrame, QHBoxLayout, QLineEdit, QMainWindow, QMessageBox,
    QStackedWidget, QVBoxLayout, QWidget,
)

from .forensic import TOOL_NAME, TOOL_VERSION
from .ui import theme
from .ui.page_extract import ExtractPage
from .ui.page_photo import PhotoPage
from .ui.page_records import AuditPage, InventoryPage
from .ui.page_search import SearchPage
from .ui.state import AppState
from .ui.widgets import HeaderBar, button, chip, label, refresh_theme_widgets, register_icon, themed
from .workspace import app_dir

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle(f"{TOOL_NAME} v{TOOL_VERSION}")
        self.resize(1480, 960)
        self.setMinimumSize(1180, 760)
        self.state = AppState()
        logo = app_dir() / "logo.png"
        self.setWindowIcon(theme.glyph_icon("shield", "#00d4ff", 32))
        self._build(str(logo) if logo.exists() else None)
        self.apply_theme(theme.current())
        last = self.state.last_evidence()
        if last and os.path.isdir(last):
            self._set_evidence(last, quiet=True)

    # ------------------------------------------------------------------ UI
    def _build(self, logo) -> None:
        root = QWidget()
        root.setObjectName("Root")
        v = QVBoxLayout(root)
        v.setContentsMargins(0, 0, 0, 0)
        v.setSpacing(0)

        self.header = HeaderBar("CYBER FORENSIC EVIDENCE SEARCH",
                                "EKSTRAKSI  •  PENCARIAN  •  PENGAMANAN BUKTI DIGITAL", logo)
        for t in ("● OFFLINE", "🔒 BUKTI READ-ONLY"):
            c = label(t, "HeaderChip")
            self.header.right.addWidget(c, 0, Qt.AlignVCenter)
        self.btn_theme = button("", "theme", "", "Ganti tema: Siber Biru (gelap) / Emas Oranye (terang)")
        self.btn_theme.clicked.connect(self.toggle_theme)
        self.header.right.addWidget(self.btn_theme, 0, Qt.AlignVCenter)
        v.addWidget(self.header)

        # --- bar folder bukti
        bar = QFrame()
        bar.setObjectName("Card")
        bl = QHBoxLayout(bar)
        bl.setContentsMargins(16, 10, 16, 10)
        bl.setSpacing(10)
        bl.addWidget(label("FOLDER BARANG BUKTI", "CardTitle"))
        self.ev_edit = QLineEdit()
        self.ev_edit.setReadOnly(True)
        self.ev_edit.setPlaceholderText("Belum dipilih — folder berisi video, foto, audio, dokumen (tidak akan diubah)")
        bl.addWidget(self.ev_edit, 3)
        b = button("PILIH FOLDER BUKTI", "folder", "Primary")
        b.clicked.connect(self.pick_evidence)
        bl.addWidget(b)
        bl.addSpacing(12)
        bl.addWidget(label("DATA HASIL", "StatCaption"))
        self.ws_lbl = label("-", "PathLabel")
        self.ws_lbl.setTextInteractionFlags(Qt.TextSelectableByMouse)
        bl.addWidget(self.ws_lbl, 2)
        b2 = button("", "open", "", "Buka folder data hasil analisis")
        b2.clicked.connect(lambda: self.state.workspace and self.state.workspace.exists()
                           and os.startfile(str(self.state.workspace)))
        bl.addWidget(b2)
        wrap = QWidget()
        wl = QVBoxLayout(wrap)
        wl.setContentsMargins(12, 10, 12, 0)
        wl.addWidget(bar)
        v.addWidget(wrap)

        # --- isi: sidebar + halaman
        body = QHBoxLayout()
        body.setContentsMargins(0, 8, 0, 0)
        body.setSpacing(0)
        side = QFrame()
        side.setObjectName("Sidebar")
        side.setFixedWidth(232)
        sl = QVBoxLayout(side)
        sl.setContentsMargins(0, 14, 0, 12)
        sl.setSpacing(2)
        sl.addWidget(label("  MODUL", "StatCaption"))
        self.stack = QStackedWidget()
        self.pages = {
            "extract": ExtractPage(self.state),
            "search": SearchPage(self.state),
            "photo": PhotoPage(self.state),
            "inventory": InventoryPage(self.state),
            "audit": AuditPage(self.state),
        }
        themed(self.pages["search"])
        nav = (("extract", "01  EKSTRAKSI BUKTI", "scan"), ("search", "02  CARI TEKS", "search"),
               ("photo", "03  CARI FOTO MIRIP", "image"), ("inventory", "04  INVENTARIS && HASH", "fingerprint"),
               ("audit", "05  AUDIT LOG", "log"))
        self.navgroup = QButtonGroup(self)
        self.navbtn = {}
        for key, text, glyph in nav:
            nb = button(text, glyph, "Nav")
            nb.setCheckable(True)
            nb.clicked.connect(lambda _=False, k=key: self.go(k))
            self.navgroup.addButton(nb)
            self.navbtn[key] = nb
            sl.addWidget(nb)
            self.stack.addWidget(self.pages[key])
        sl.addStretch(1)
        sl.addWidget(label("  ALUR KERJA", "StatCaption"))
        sl.addWidget(label("  1. Pilih folder bukti\n  2. Ekstraksi (sekali)\n  3. Cari teks / foto\n"
                           "  4. Amankan + laporan\n  5. Verifikasi integritas", "SideFoot"))
        sl.addSpacing(10)
        sl.addWidget(label(f"  {TOOL_NAME}\n  v{TOOL_VERSION} • offline", "SideFoot"))
        body.addWidget(side)
        body.addWidget(self.stack, 1)
        v.addLayout(body, 1)
        self.setCentralWidget(root)

        self.sb_ws = label("Folder bukti belum dipilih")
        self.statusBar().addWidget(self.sb_ws, 1)
        self.statusBar().addPermanentWidget(label("Folder bukti dibuka READ-ONLY  •  hash SHA-256/MD5  •  audit log berantai"))
        self.go("extract")

    # ------------------------------------------------------------- aksi
    def go(self, key: str) -> None:
        self.navbtn[key].setChecked(True)
        self.stack.setCurrentWidget(self.pages[key])
        if key in ("inventory", "audit"):
            self.pages[key].refresh()
        if key == "photo":
            self.pages["photo"].refresh_index_info()

    def pick_evidence(self) -> None:
        if self.any_busy():
            QMessageBox.warning(self, "Sedang berjalan", "Hentikan proses yang berjalan sebelum ganti folder bukti.")
            return
        d = QFileDialog.getExistingDirectory(self, "Pilih Folder Barang Bukti", self.state.evidence_dir or "")
        if d:
            self._set_evidence(d)

    def _set_evidence(self, d: str, quiet: bool = False) -> None:
        err = self.state.set_evidence(d)
        if err:
            if not quiet:
                QMessageBox.warning(self, "Folder bukti", err)
            return
        self.ev_edit.setText(self.state.evidence_dir)
        self.ws_lbl.setText(str(self.state.workspace))
        self.sb_ws.setText(f"BUKTI: {self.state.evidence_dir}   →   DATA: {self.state.workspace}")
        self.pages["photo"].refresh_index_info()

    def toggle_theme(self) -> None:
        self.apply_theme("light" if theme.current() == "dark" else "dark")

    def apply_theme(self, name: str) -> None:
        theme.set_current(name)
        QApplication.instance().setStyleSheet(theme.qss())
        refresh_theme_widgets()
        other = "EMAS ORANYE" if name == "dark" else "SIBER BIRU"
        self.btn_theme.setText(f"TEMA {other}")
        self.header.update()

    def any_busy(self) -> bool:
        p = self.pages
        runners = [p["extract"].runner, p["search"].runner, p["search"].sec_runner,
                   p["photo"].idx_runner, p["photo"].s_runner, p["photo"].sec_runner]
        return any(r.busy() for r in runners)

    def closeEvent(self, event) -> None:  # noqa: N802
        if self.any_busy():
            ans = QMessageBox.question(self, "Proses masih berjalan",
                                       "Masih ada proses berjalan. Hentikan dan tutup aplikasi?\n"
                                       "(Progres tersimpan dan bisa dilanjutkan nanti.)")
            if ans != QMessageBox.Yes:
                event.ignore()
                return
        for p in ("extract", "search", "photo"):
            self.pages[p].shutdown()
        self.state.close()
        super().closeEvent(event)


def main() -> None:
    QApplication.setHighDpiScaleFactorRoundingPolicy(Qt.HighDpiScaleFactorRoundingPolicy.PassThrough)
    app = QApplication(sys.argv)
    app.setApplicationName(TOOL_NAME)
    app.setFont(QFont(theme.BODY_FONT, 10))
    theme.load_saved()
    win = MainWindow()
    win.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
