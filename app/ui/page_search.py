"""Halaman 02 - Pencarian kalimat di semua video/audio/foto/dokumen."""
from __future__ import annotations

import html
import os
import subprocess
import time
from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtGui import QGuiApplication, QPixmap
from PySide6.QtWidgets import (
    QAbstractItemView, QComboBox, QGridLayout, QHBoxLayout, QHeaderView, QLineEdit, QMessageBox,
    QSpinBox, QSplitter, QTableView, QTextBrowser, QVBoxLayout, QWidget,
)

from ..forensic import fconfig
from ..forensic.extractors import fmt_ts
from ..forensic.report import secure_hits
from ..forensic.search import Hit, TextSearcher
from . import theme
from .page_extract import page_header
from .state import AppState
from .widgets import Card, RowsModel, TaskRunner, button, chip, label


def _loc(h: Hit) -> str:
    return f"{fmt_ts(h.t_start)} – {fmt_ts(h.t_end)}" if h.t_start is not None else (h.label or "-")


class SearchPage(QWidget):
    def __init__(self, state: AppState):
        super().__init__()
        self.setObjectName("Page")
        self.state = state
        self.hits: list[Hit] = []
        self.searcher: TextSearcher | None = None
        self._last = ("", "")
        self.runner = TaskRunner(self)
        self.runner.busy_changed.connect(self._on_busy)
        self.sec_runner = TaskRunner(self)
        self._build()
        state.evidence_changed.connect(self._reset)

    def _build(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(18, 14, 18, 14)
        root.setSpacing(12)
        root.addWidget(page_header("PENCARIAN TEKS LINTAS BUKTI",
                                   "Cari kalimat di ucapan (video/audio), teks di layar/foto, dokumen, chat & media sosial sekaligus"))

        sc = Card()
        r = QHBoxLayout()
        self.q = QLineEdit()
        self.q.setObjectName("BigSearch")
        self.q.setPlaceholderText("Ketik kalimat yang dicari…   contoh:  hay tolong lakukan penyerangan itu")
        self.q.returnPressed.connect(self.search)
        r.addWidget(self.q, 1)
        self.btn_search = button("CARI", "search", "Primary")
        self.btn_search.setMinimumHeight(46)
        self.btn_search.setMinimumWidth(130)
        self.btn_search.clicked.connect(self.search)
        r.addWidget(self.btn_search)
        sc.body.addLayout(r)
        f = QHBoxLayout()
        f.setSpacing(8)
        self.cmb_mode = QComboBox()
        self.cmb_mode.addItem("FUZZY — toleran salah dengar/OCR", "fuzzy")
        self.cmb_mode.addItem("FRASA PERSIS", "frasa")
        self.cmb_mode.addItem("SEMUA KATA (urutan bebas)", "semua")
        self.spin_thr = QSpinBox()
        self.spin_thr.setRange(50, 100)
        self.spin_thr.setValue(80)
        self.spin_thr.setToolTip("Skor minimal mode fuzzy. Turunkan (mis. 70) untuk rekaman suara yang kurang jelas.")
        self.cmb_kind = QComboBox()
        self.cmb_kind.addItem("SEMUA JENIS FILE", None)
        for k in ("video", "audio", "image", "document", "database"):
            self.cmb_kind.addItem(fconfig.KIND_LABEL[k].upper(), k)
        f.addWidget(label("Mode", "Muted"))
        f.addWidget(self.cmb_mode)
        f.addSpacing(8)
        f.addWidget(label("Skor min.", "Muted"))
        f.addWidget(self.spin_thr)
        f.addSpacing(8)
        f.addWidget(label("Jenis", "Muted"))
        f.addWidget(self.cmb_kind)
        f.addStretch(1)
        self.summary = label("", "CardHint")
        f.addWidget(self.summary)
        sc.body.addLayout(f)
        root.addWidget(sc)

        split = QSplitter(Qt.Horizontal)
        # --- tabel hasil
        tc = Card("Hasil temuan", "list")
        self.model = RowsModel(["Skor", "Jenis", "Sumber teks", "Lokasi", "Kutipan", "Nama file"])
        self.model.colors[0] = lambda row: "ok" if row[0] >= 95 else ("warn" if row[0] < 85 else "accent")
        self.model.align_right.add(0)
        self.table = QTableView()
        self.table.setModel(self.model)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setAlternatingRowColors(True)
        self.table.setSortingEnabled(True)
        self.table.verticalHeader().setVisible(False)
        self.table.verticalHeader().setDefaultSectionSize(30)
        self.table.setWordWrap(False)
        hh = self.table.horizontalHeader()
        hh.setStretchLastSection(True)
        for i, w in enumerate((56, 82, 130, 150, 330)):
            self.table.setColumnWidth(i, w)
        hh.setSectionResizeMode(QHeaderView.Interactive)
        self.table.selectionModel().selectionChanged.connect(self._detail)
        self.table.doubleClicked.connect(lambda *_: self.play_or_open())
        tc.body.addWidget(self.table)
        ab = QHBoxLayout()
        self.btn_sec_sel = button("AMANKAN TERPILIH", "lock", "", "Salin file asli + verifikasi hash + laporan")
        self.btn_sec_sel.clicked.connect(lambda: self.secure(True))
        self.btn_sec_all = button("AMANKAN SEMUA + LAPORAN", "shield", "Primary",
                                  "Semua temuan → paket bukti (salinan read-only, frame, teks, manifest hash, laporan HTML/CSV)")
        self.btn_sec_all.clicked.connect(lambda: self.secure(False))
        ab.addWidget(self.btn_sec_sel)
        ab.addStretch(1)
        ab.addWidget(self.btn_sec_all)
        tc.body.addLayout(ab)
        split.addWidget(tc)

        # --- detail
        dc = Card("Detail temuan", "eye")
        self.preview = label("PRATINJAU", "Muted")
        self.preview.setAlignment(Qt.AlignCenter)
        self.preview.setMinimumHeight(200)
        self.preview.setStyleSheet(f"border:1px dashed {theme.pal()['border']};")
        dc.body.addWidget(self.preview)
        g = QGridLayout()
        g.setHorizontalSpacing(10)
        g.setVerticalSpacing(3)
        self.d = {}
        for i, k in enumerate(("File", "Jenis", "Lokasi", "Terkait", "Path", "SHA-256", "MD5")):
            g.addWidget(label(k.upper(), "StatCaption"), i, 0, Qt.AlignTop)
            v = label("-", "PathLabel" if k in ("Path", "SHA-256", "MD5") else "", wrap=True)
            v.setTextInteractionFlags(Qt.TextSelectableByMouse)
            self.d[k] = v
            g.addWidget(v, i, 1)
        g.setColumnStretch(1, 1)
        dc.body.addLayout(g)
        self.text = QTextBrowser()
        dc.body.addWidget(self.text, 1)
        bb = QHBoxLayout()
        self.btn_play = button("PUTAR / BUKA", "play", "", "Video/audio diputar 2 detik sebelum kalimat")
        self.btn_play.clicked.connect(self.play_or_open)
        b2 = button("LOKASI FILE", "folder")
        b2.clicked.connect(self.open_location)
        b3 = button("SALIN HASH", "hash")
        b3.clicked.connect(self.copy_hash)
        for b in (self.btn_play, b2, b3):
            bb.addWidget(b)
        dc.body.addLayout(bb)
        split.addWidget(dc)
        split.setSizes([820, 460])
        split.setChildrenCollapsible(False)
        root.addWidget(split, 1)

    def on_theme(self) -> None:
        self.preview.setStyleSheet(f"border:1px dashed {theme.pal()['border']};")
        self._detail()

    # ------------------------------------------------------------------
    def _reset(self) -> None:
        if self.searcher:
            self.searcher.close()
        self.searcher = None
        self.hits = []
        self.model.set_rows([])
        self.summary.setText("")
        self._clear_detail()

    def _on_busy(self, b: bool) -> None:
        self.btn_search.setEnabled(not b)
        self.btn_search.setText("MENCARI…" if b else "CARI")

    def search(self) -> None:
        if not self.state.workspace:
            QMessageBox.warning(self, "Folder bukti", "Pilih FOLDER BARANG BUKTI terlebih dahulu.")
            return
        q = self.q.text().strip()
        if not q or self.runner.busy():
            return
        if self.searcher is None:
            if not (self.state.workspace / fconfig.CASE_DB).exists():
                return
            self.searcher = TextSearcher(self.state.workspace)
        mode, kind, thr = self.cmb_mode.currentData(), self.cmb_kind.currentData(), self.spin_thr.value()
        searcher = self.searcher
        t0 = time.time()

        def job(_lg, _pr, _stop):
            return searcher.search(q, mode=mode, threshold=thr, kinds={kind} if kind else None), time.time() - t0
        self._last = (q, mode)
        self.runner.start(job, lambda res: self._show(res, q, mode, kind),
                          lambda m: QMessageBox.critical(self, "Pencarian gagal", m))

    def _show(self, res, q, mode, kind) -> None:
        hits, dt = res
        self.hits = hits
        if self.state.store:
            self.state.store.audit("PENCARIAN_TEKS", f"\"{q}\" mode={mode} jenis={kind or 'semua'} hasil={len(hits)}")
        rows = []
        for h in hits:
            snip = h.text
            if h.match_span:
                s, e = h.match_span
                snip = ("…" if s > 50 else "") + h.text[max(0, s - 50):e + 90]
            rows.append([round(h.score), h.kind_label.upper(), h.source_label, _loc(h), snip, h.name])
        self.model.set_rows(rows, hits)
        by = {}
        for h in hits:
            by[h.kind_label] = by.get(h.kind_label, 0) + 1
        nfiles = len({h.file_id for h in hits})
        parts = "  ".join(f"{k}: {v}" for k, v in sorted(by.items()))
        self.summary.setText(f"{len(hits)} TEMUAN  •  {nfiles} FILE  •  {dt:.2f} dtk    {parts}"
                             if hits else f"Tidak ada temuan ({dt:.2f} dtk). Coba mode FUZZY atau turunkan skor min.")
        if hits:
            self.table.selectRow(0)
        else:
            self._clear_detail()

    # ------------------------------------------------------------------
    def _current(self) -> Hit | None:
        rows = self.table.selectionModel().selectedRows()
        if not rows:
            return None
        return self.model.payload[rows[0].row()]

    def _clear_detail(self) -> None:
        self.preview.clear()
        self.preview.setText("PRATINJAU")
        for v in self.d.values():
            v.setText("-")
        self.text.clear()

    def _detail(self, *_a) -> None:
        h = self._current()
        if not h:
            return
        pix = None
        if h.frame_path and self.state.workspace:
            pix = QPixmap(str(self.state.workspace / h.frame_path))
        elif h.kind == "image":
            pix = QPixmap(h.path)
        if pix is not None and not pix.isNull():
            self.preview.setPixmap(pix.scaled(max(200, self.preview.width() - 4), 260,
                                              Qt.KeepAspectRatio, Qt.SmoothTransformation))
        else:
            self.preview.clear()
            self.preview.setText(f"{h.kind_label.upper()}\n{h.name}")
        self.d["File"].setText(h.name)
        self.d["Jenis"].setText(f"{h.kind_label} — {h.source_label}   (skor {h.score:.0f})")
        self.d["Lokasi"].setText(_loc(h))
        if h.ref:
            self.d["Terkait"].setText(f"{h.ref}" + ("  (ada di folder bukti)" if h.ref_path else "  (file tidak ditemukan)"))
        else:
            self.d["Terkait"].setText(h.context or "-")
        self.d["Path"].setText(h.path)
        self.d["SHA-256"].setText(h.sha256 or "-")
        self.d["MD5"].setText(h.md5 or "-")
        c = theme.pal()
        t = h.text
        if h.match_span:
            s, e = h.match_span
            body = (html.escape(t[:s]) + f"<span style='background:{c['mark']};color:#000;font-weight:700'>"
                    + html.escape(t[s:e]) + "</span>" + html.escape(t[e:]))
        else:
            body = html.escape(t)
        self.text.setHtml(f"<div style='white-space:pre-wrap;font-size:11pt;line-height:140%'>{body}</div>")
        if h.ref_path:
            self.btn_play.setText("BUKA FILE TERKAIT")
        else:
            self.btn_play.setText("PUTAR DI DETIK INI" if h.t_start is not None else "BUKA FILE")

    def play_or_open(self) -> None:
        h = self._current()
        if not h:
            return
        if h.ref_path and os.path.exists(h.ref_path):
            os.startfile(h.ref_path)  # type: ignore[attr-defined]  # voice note/foto dari pesan chat
            return
        if h.kind == "database":
            subprocess.run(["explorer", "/select,", str(Path(h.path))])
            return
        if not os.path.exists(h.path):
            QMessageBox.warning(self, "File tidak ada", f"File tidak ditemukan:\n{h.path}")
            return
        if h.t_start is not None and h.kind in ("audio", "video"):
            ffplay = fconfig.find_tool("ffplay")
            if ffplay:
                start = max(0.0, h.t_start - 2)
                args = [ffplay, "-ss", f"{start:.2f}", "-window_title", f"{h.name}  @ {fmt_ts(h.t_start)}"]
                if h.kind == "audio":
                    args += ["-showmode", "1"]
                subprocess.Popen(args + [h.path], creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
                return
        os.startfile(h.path)  # type: ignore[attr-defined]

    def open_location(self) -> None:
        h = self._current()
        if h:
            subprocess.run(["explorer", "/select,", str(Path(h.path))])

    def copy_hash(self) -> None:
        h = self._current()
        if h:
            QGuiApplication.clipboard().setText(f"{h.path}\nSHA-256: {h.sha256}\nMD5: {h.md5}")

    def secure(self, selected_only: bool) -> None:
        if not self.hits or self.sec_runner.busy() or not self.state.store:
            return
        if selected_only:
            idx = sorted({i.row() for i in self.table.selectionModel().selectedRows()})
            hits = [self.model.payload[i] for i in idx]
        else:
            hits = list(self.model.payload)
        if not hits:
            return
        q, mode = self._last
        ws = self.state.workspace
        self.btn_sec_all.setEnabled(False)
        self.btn_sec_sel.setEnabled(False)

        def job(lg, pr, _stop):
            from ..forensic.store import CaseStore
            store = CaseStore(ws)
            try:
                return secure_hits(store, hits, q, mode, True, lg, pr)
            finally:
                store.close()

        def done(out):
            self.btn_sec_all.setEnabled(True)
            self.btn_sec_sel.setEnabled(True)
            self.state.data_changed.emit()
            QMessageBox.information(self, "Bukti diamankan",
                                    f"{len(hits)} temuan diamankan.\n\nSalinan file (read-only, hash terverifikasi), "
                                    f"frame, teks, manifest hash, dan laporan disimpan di:\n{out}")
            try:
                os.startfile(str(out / "laporan.html"))  # type: ignore[attr-defined]
            except OSError:
                pass

        def err(m):
            self.btn_sec_all.setEnabled(True)
            self.btn_sec_sel.setEnabled(True)
            QMessageBox.critical(self, "Gagal mengamankan", m)
        self.sec_runner.start(job, done, err)

    def shutdown(self) -> None:
        self.runner.shutdown()
        self.sec_runner.shutdown()
        if self.searcher:
            self.searcher.close()
