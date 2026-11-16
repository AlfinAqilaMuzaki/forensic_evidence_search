"""Halaman 04 - Inventaris & hash seluruh file bukti, 05 - Audit log berantai."""
from __future__ import annotations

import csv
import os
import subprocess
import time
from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QAbstractItemView, QComboBox, QHBoxLayout, QHeaderView, QLineEdit, QMessageBox, QTableView,
    QVBoxLayout, QWidget,
)

from ..forensic import fconfig
from .page_extract import page_header
from .state import AppState
from .widgets import Card, RowsModel, button, chip, label

STATUS_TXT = {"done": "SELESAI", "pending": "ANTRIAN", "processing": "DIPROSES", "error": "GAGAL",
              "crash": "CRASH", "unsupported": "TDK DIDUKUNG", "missing": "HILANG"}


def _size(n) -> str:
    n = float(n or 0)
    for u in ("B", "KB", "MB", "GB"):
        if n < 1024:
            return f"{n:.0f} {u}" if u == "B" else f"{n:.1f} {u}"
        n /= 1024
    return f"{n:.1f} TB"


def _table(model: RowsModel) -> QTableView:
    t = QTableView()
    t.setModel(model)
    t.setSelectionBehavior(QAbstractItemView.SelectRows)
    t.setAlternatingRowColors(True)
    t.setSortingEnabled(True)
    t.verticalHeader().setVisible(False)
    t.verticalHeader().setDefaultSectionSize(28)
    t.setWordWrap(False)
    t.horizontalHeader().setStretchLastSection(True)
    t.horizontalHeader().setSectionResizeMode(QHeaderView.Interactive)
    return t


class InventoryPage(QWidget):
    COLS = ["ID", "Nama file", "Jenis", "Status", "Segmen", "Ukuran", "Deteksi", "SHA-256", "MD5", "Path", "Keterangan"]

    def __init__(self, state: AppState):
        super().__init__()
        self.setObjectName("Page")
        self.state = state
        self._all: list[tuple] = []
        root = QVBoxLayout(self)
        root.setContentsMargins(18, 14, 18, 14)
        root.setSpacing(12)
        root.addWidget(page_header("INVENTARIS & HASH BUKTI",
                                   "Seluruh file di folder bukti beserta hash SHA-256/MD5, status ekstraksi, "
                                   "dan deteksi file yang ekstensinya disamarkan"))
        c = Card()
        f = QHBoxLayout()
        self.filter = QLineEdit()
        self.filter.setPlaceholderText("Filter nama / path / hash…")
        self.filter.textChanged.connect(self._apply)
        self.cmb_kind = QComboBox()
        self.cmb_kind.addItem("SEMUA JENIS", None)
        for k in ("video", "audio", "image", "document", "other"):
            self.cmb_kind.addItem(fconfig.KIND_LABEL[k].upper(), k)
        self.cmb_kind.currentIndexChanged.connect(self._apply)
        self.cmb_st = QComboBox()
        self.cmb_st.addItem("SEMUA STATUS", None)
        for k, v in STATUS_TXT.items():
            self.cmb_st.addItem(v, k)
        self.cmb_st.addItem("EKSTENSI DISAMARKAN", "_mismatch")
        self.cmb_st.currentIndexChanged.connect(self._apply)
        f.addWidget(self.filter, 2)
        f.addWidget(self.cmb_kind)
        f.addWidget(self.cmb_st)
        b = button("REFRESH", "refresh")
        b.clicked.connect(self.refresh)
        f.addWidget(b)
        b = button("EXPORT CSV", "export", "Primary")
        b.clicked.connect(self.export)
        f.addWidget(b)
        c.body.addLayout(f)
        self.count = label("", "CardHint")
        c.body.addWidget(self.count)
        root.addWidget(c)

        tc = Card("Daftar file bukti", "list")
        self.model = RowsModel(self.COLS)
        self.model.mono_cols.update({7, 8})
        self.model.align_right.update({0, 4, 5})
        self.model.colors[3] = lambda r: {"SELESAI": "ok", "GAGAL": "bad", "CRASH": "bad", "HILANG": "bad",
                                          "ANTRIAN": "warn"}.get(r[3])
        self.model.colors[6] = lambda r: "warn" if "DISAMARKAN" in str(r[6]) else None
        self.table = _table(self.model)
        for i, w in enumerate((55, 230, 80, 100, 65, 80, 150, 200, 150, 300)):
            self.table.setColumnWidth(i, w)
        self.table.doubleClicked.connect(lambda *_: self.open_text())
        tc.body.addWidget(self.table, 1)
        ab = QHBoxLayout()
        b1 = button("LIHAT TEKS HASIL EKSTRAKSI", "text")
        b1.clicked.connect(self.open_text)
        b2 = button("LOKASI FILE", "folder")
        b2.clicked.connect(self.open_location)
        ab.addWidget(b1)
        ab.addWidget(b2)
        ab.addStretch(1)
        tc.body.addLayout(ab)
        root.addWidget(tc, 1)
        state.data_changed.connect(self.refresh)

    def refresh(self) -> None:
        conn = self.state.reader()
        if conn is None:
            self._all = []
            self._apply()
            return
        try:
            self._all = conn.execute(
                "SELECT id, name, kind, status, n_segments, size, detected_by, ext_mismatch, sha256, md5, path, "
                "error, extract_txt FROM files ORDER BY id").fetchall()
        finally:
            conn.close()
        self._apply()

    def _apply(self) -> None:
        q = self.filter.text().strip().lower()
        k, st = self.cmb_kind.currentData(), self.cmb_st.currentData()
        rows, pay = [], []
        for r in self._all:
            (fid, name, kind, status, nseg, size, det, mism, sha, md5, path, err, txt) = r
            if k and kind != k:
                continue
            if st == "_mismatch":
                if not mism:
                    continue
            elif st and status != st:
                continue
            if q and q not in f"{name} {path} {sha} {md5}".lower():
                continue
            rows.append([fid, name, fconfig.KIND_LABEL.get(kind, kind).upper(), STATUS_TXT.get(status, status),
                         nseg or 0, _size(size), ("DISAMARKAN (cek isi file)" if mism else ("sesuai ekstensi" if det == "ekstensi" else det or "-")),
                         sha or "", md5 or "", path, err or ""])
            pay.append(r)
        self.model.set_rows(rows, pay)
        self.count.setText(f"Menampilkan {len(rows):,} dari {len(self._all):,} file".replace(",", "."))

    def _cur(self):
        s = self.table.selectionModel().selectedRows()
        return self.model.payload[s[0].row()] if s else None

    def open_text(self) -> None:
        r = self._cur()
        if not r:
            return
        if r[12] and self.state.workspace and (self.state.workspace / r[12]).exists():
            os.startfile(str(self.state.workspace / r[12]))  # type: ignore[attr-defined]
        else:
            QMessageBox.information(self, "Teks", "File ini belum diekstrak / tidak berisi teks.")

    def open_location(self) -> None:
        r = self._cur()
        if r:
            subprocess.run(["explorer", "/select,", str(Path(r[10]))])

    def export(self) -> None:
        if not self.state.workspace or not self._all:
            return
        out_dir = self.state.workspace / "laporan"
        out_dir.mkdir(exist_ok=True)
        out = out_dir / f"inventaris_bukti_{time.strftime('%Y%m%d_%H%M%S')}.csv"
        with open(out, "w", newline="", encoding="utf-8-sig") as fh:
            w = csv.writer(fh)
            w.writerow(["ID", "Nama", "Jenis", "Status", "Segmen teks", "Ukuran (byte)", "Deteksi tipe",
                        "Ekstensi disamarkan", "SHA-256", "MD5", "Path", "Keterangan"])
            for r in self._all:
                w.writerow([r[0], r[1], r[2], r[3], r[4], r[5], r[6], "YA" if r[7] else "", r[8], r[9], r[10], r[11]])
        if self.state.store:
            self.state.store.audit("EXPORT_INVENTARIS", f"{len(self._all)} file -> {out}")
        QMessageBox.information(self, "Export", f"Inventaris disimpan:\n{out}")
        subprocess.run(["explorer", "/select,", str(out)])


class AuditPage(QWidget):
    def __init__(self, state: AppState):
        super().__init__()
        self.setObjectName("Page")
        self.state = state
        root = QVBoxLayout(self)
        root.setContentsMargins(18, 14, 18, 14)
        root.setSpacing(12)
        root.addWidget(page_header("AUDIT LOG BERANTAI HASH",
                                   "Setiap aksi tercatat otomatis. Tiap entri memuat hash entri sebelumnya — "
                                   "perubahan/penghapusan catatan langsung terdeteksi"))
        c = Card()
        r = QHBoxLayout()
        self.chain = chip("RANTAI: BELUM DICEK")
        r.addWidget(self.chain)
        self.info = label("", "CardHint", wrap=True)
        r.addWidget(self.info, 1)
        b = button("VERIFIKASI RANTAI", "shield", "Primary")
        b.clicked.connect(self.verify)
        r.addWidget(b)
        b = button("BUKA audit_log.txt", "open")
        b.clicked.connect(self.open_txt)
        r.addWidget(b)
        b = button("REFRESH", "refresh")
        b.clicked.connect(self.refresh)
        r.addWidget(b)
        c.body.addLayout(r)
        root.addWidget(c)
        tc = Card("Catatan audit", "log")
        self.model = RowsModel(["#", "Waktu", "Operator", "Aksi", "Detail", "Hash entri"])
        self.model.mono_cols.add(5)
        self.model.colors[3] = lambda r: "accent"
        self.table = _table(self.model)
        for i, w in enumerate((50, 170, 170, 170, 520)):
            self.table.setColumnWidth(i, w)
        tc.body.addWidget(self.table, 1)
        root.addWidget(tc, 1)
        state.data_changed.connect(self.refresh)

    def refresh(self) -> None:
        conn = self.state.reader()
        if conn is None:
            self.model.set_rows([])
            return
        try:
            rows = conn.execute("SELECT id, ts_text, examiner, action, detail, entry_hash FROM audit "
                                "ORDER BY id DESC").fetchall()
            info = dict(conn.execute("SELECT key, value FROM case_info"))
        finally:
            conn.close()
        self.model.set_rows([list(r) for r in rows])
        self.info.setText(f"{len(rows)} entri  •  workspace dibuat {info.get('created_at', '-')}  •  "
                          f"operator {info.get('operator', '-')}  •  {info.get('tool', '')}")

    def verify(self) -> None:
        if not self.state.store:
            return
        ok, msg = self.state.store.verify_audit_chain()
        self.chain.setText(("RANTAI UTUH" if ok else "RANTAI RUSAK").upper())
        self.chain.setObjectName("Chip" if ok else "ChipWarn")
        self.chain.style().unpolish(self.chain)
        self.chain.style().polish(self.chain)
        (QMessageBox.information if ok else QMessageBox.critical)(self, "Verifikasi audit log", msg)

    def open_txt(self) -> None:
        if self.state.workspace and (self.state.workspace / fconfig.AUDIT_TXT).exists():
            os.startfile(str(self.state.workspace / fconfig.AUDIT_TXT))  # type: ignore[attr-defined]
