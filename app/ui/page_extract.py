"""Halaman 01 - Pusat Ekstraksi: statistik bukti, parameter, progres, log."""
from __future__ import annotations

import os
import time

from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import (
    QCheckBox, QComboBox, QDoubleSpinBox, QGridLayout, QHBoxLayout, QMessageBox, QPlainTextEdit,
    QProgressBar, QVBoxLayout, QWidget,
)

from ..forensic import fconfig
from ..forensic.extractors import fmt_ts
from ..forensic.pipeline import CaseProcessor, ExtractOptions
from ..forensic.store import CaseStore
from .state import AppState
from .widgets import Card, StatCard, TaskRunner, button, label


def page_header(title: str, sub: str) -> QWidget:
    w = QWidget()
    v = QVBoxLayout(w)
    v.setContentsMargins(2, 0, 0, 4)
    v.setSpacing(0)
    v.addWidget(label(title, "PageTitle"))
    v.addWidget(label(sub, "PageSub"))
    return w


class ExtractPage(QWidget):
    def __init__(self, state: AppState):
        super().__init__()
        self.setObjectName("Page")
        self.state = state
        self.runner = TaskRunner(self)
        self.runner.progress.connect(self._on_progress)
        self.runner.log.connect(self.log)
        self.runner.busy_changed.connect(self._on_busy)
        self._t_start = 0.0
        self._build()
        state.evidence_changed.connect(self._on_evidence)
        state.data_changed.connect(self.refresh_stats)
        self._timer = QTimer(self)
        self._timer.setInterval(3000)
        self._timer.timeout.connect(self.refresh_stats)

    # ------------------------------------------------------------------ UI
    def _build(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(18, 14, 18, 14)
        root.setSpacing(12)
        root.addWidget(page_header("PUSAT EKSTRAKSI BUKTI",
                                   "Ekstrak teks dari seluruh video, audio, foto & dokumen  •  hash SHA-256/MD5  •  audit log"))

        # --- statistik
        grid = QGridLayout()
        grid.setSpacing(8)
        self.stats = {
            "total": StatCard("Total file", "db"),
            "video": StatCard("Video", "video"),
            "audio": StatCard("Audio", "audio"),
            "image": StatCard("Foto", "image"),
            "document": StatCard("Dokumen", "doc"),
            "database": StatCard("Database/Chat", "chip"),
            "done": StatCard("Selesai", "check", "ok"),
            "pending": StatCard("Antrian", "clock", "warn"),
            "error": StatCard("Gagal", "error", "bad"),
            "segments": StatCard("Segmen teks", "text"),
            "mismatch": StatCard("Ekstensi disamarkan", "warn", "warn"),
        }
        for i, w in enumerate(self.stats.values()):
            grid.addWidget(w, i // 6, i % 6)
        root.addLayout(grid)

        mid = QHBoxLayout()
        mid.setSpacing(12)

        # --- parameter
        pc = Card("Parameter ekstraksi", "chip")
        g = QGridLayout()
        g.setHorizontalSpacing(14)
        g.setVerticalSpacing(8)
        self.chk = {}
        for i, (k, txt) in enumerate((("document", "Dokumen  (PDF, Word, Excel, PPT, TXT, Email, export chat)"),
                                      ("database", "Database chat  (WhatsApp msgstore.db / ChatStorage.sqlite, SQLite)"),
                                      ("image", "Foto  (OCR teks dalam gambar)"),
                                      ("audio", "Audio  (transkrip suara → teks)"),
                                      ("video", "Video"))):
            c = QCheckBox(txt)
            c.setChecked(True)
            self.chk[k] = c
            g.addWidget(c, i, 0, 1, 2)
        vrow = QHBoxLayout()
        vrow.setContentsMargins(26, 0, 0, 0)
        vrow.setSpacing(22)
        self.chk_vid_asr = QCheckBox("suara di video")
        self.chk_vid_ocr = QCheckBox("teks di layar video")
        for c in (self.chk_vid_asr, self.chk_vid_ocr):
            c.setChecked(True)
            vrow.addWidget(c)
        vrow.addStretch(1)
        g.addLayout(vrow, 5, 0, 1, 2)
        self.chk["video"].toggled.connect(lambda on: (self.chk_vid_asr.setEnabled(on), self.chk_vid_ocr.setEnabled(on)))

        self.cmb_model = QComboBox()
        self.cmb_model.addItem("SMALL  — lebih akurat", "small")
        self.cmb_model.addItem("BASE  — lebih cepat", "base")
        self.cmb_lang = QComboBox()
        for t, d in (("Indonesia", "id"), ("Deteksi otomatis", None), ("Inggris", "en"),
                     ("Jawa", "jw"), ("Melayu", "ms"), ("Sunda", "su")):
            self.cmb_lang.addItem(t, d)
        self.spin_interval = QDoubleSpinBox()
        self.spin_interval.setRange(0.5, 30)
        self.spin_interval.setSingleStep(0.5)
        self.spin_interval.setSuffix("  detik")
        self.spin_interval.setValue(fconfig.VIDEO_FRAME_INTERVAL)
        self.chk_pdf_ocr = QCheckBox("OCR halaman PDF hasil scan")
        self.chk_pdf_ocr.setChecked(True)
        self.chk_retry = QCheckBox("Ulangi file yang sebelumnya gagal")
        rows = (("Model transkrip", self.cmb_model), ("Bahasa suara", self.cmb_lang),
                ("Ambil frame video tiap", self.spin_interval))
        for i, (t, w) in enumerate(rows):
            g.addWidget(label(t, "Muted"), 6 + i, 0)
            g.addWidget(w, 6 + i, 1)
        g.addWidget(self.chk_pdf_ocr, 9, 0, 1, 2)
        g.addWidget(self.chk_retry, 10, 0, 1, 2)
        g.setColumnStretch(1, 1)
        pc.body.addLayout(g)
        pc.body.addStretch(1)
        mid.addWidget(pc, 5)

        # --- status proses
        sc = Card("Status proses", "scan")
        self.phase = label("SIAP — pilih folder barang bukti lalu tekan MULAI", "CardHint", wrap=True)
        sc.body.addWidget(self.phase)
        self.progress = QProgressBar()
        self.progress.setFormat("%p%")
        self.progress.setMinimumHeight(26)
        sc.body.addWidget(self.progress)
        self.cur_file = label("-", "PathLabel", wrap=True)
        sc.body.addWidget(self.cur_file)
        info = QHBoxLayout()
        self.lbl_count = label("0 / 0 file", "Muted")
        self.lbl_eta = label("Sisa waktu: -", "Muted")
        self.lbl_elapsed = label("Berjalan: -", "Muted")
        for w in (self.lbl_count, self.lbl_elapsed, self.lbl_eta):
            info.addWidget(w)
        info.addStretch(1)
        sc.body.addLayout(info)
        sc.body.addStretch(1)
        b1 = QHBoxLayout()
        self.btn_start = button("MULAI / LANJUTKAN EKSTRAKSI", "play", "Primary",
                                "Proses semua file baru/belum selesai. Aman dihentikan & dilanjutkan kapan saja.")
        self.btn_start.setMinimumHeight(42)
        self.btn_start.clicked.connect(self.start)
        self.btn_stop = button("STOP", "stop", "Danger", "Hentikan; progres tersimpan")
        self.btn_stop.setMinimumHeight(42)
        self.btn_stop.setEnabled(False)
        self.btn_stop.clicked.connect(self.stop)
        b1.addWidget(self.btn_start, 3)
        b1.addWidget(self.btn_stop, 1)
        sc.body.addLayout(b1)
        b2 = QHBoxLayout()
        self.btn_verify = button("VERIFIKASI INTEGRITAS", "fingerprint", "",
                                 "Hash ulang semua file bukti & bandingkan dengan hash awal + cek rantai audit")
        self.btn_verify.clicked.connect(self.verify)
        self.btn_open = button("BUKA FOLDER DATA", "open", "", "Folder hasil ekstraksi, frame, & bukti diamankan")
        self.btn_open.clicked.connect(lambda: self.state.workspace and os.startfile(str(self.state.workspace)))
        b2.addWidget(self.btn_verify)
        b2.addWidget(self.btn_open)
        sc.body.addLayout(b2)
        mid.addWidget(sc, 6)
        root.addLayout(mid)

        lc = Card("Log aktivitas", "log")
        self.console = QPlainTextEdit()
        self.console.setObjectName("Console")
        self.console.setReadOnly(True)
        self.console.setMaximumBlockCount(50000)
        lc.body.addWidget(self.console)
        root.addWidget(lc, 1)

    # ------------------------------------------------------------- helpers
    def log(self, m: str) -> None:
        self.console.appendPlainText(f"[{time.strftime('%H:%M:%S')}] {m}")

    def _on_evidence(self) -> None:
        self.log(f"Folder bukti aktif: {self.state.evidence_dir}")
        self.log(f"Data hasil analisis: {self.state.workspace}")
        self.phase.setText("SIAP — tekan MULAI / LANJUTKAN EKSTRAKSI")

    def refresh_stats(self) -> None:
        conn = self.state.reader()
        if conn is None:
            for s in self.stats.values():
                s.set(0)
            return
        try:
            by_kind = dict(conn.execute("SELECT kind, COUNT(*) FROM files WHERE status!='missing' GROUP BY kind"))
            by_st = dict(conn.execute("SELECT status, COUNT(*) FROM files GROUP BY status"))
            segs = conn.execute("SELECT COUNT(*) FROM segments").fetchone()[0]
            mism = conn.execute("SELECT COUNT(*) FROM files WHERE ext_mismatch=1").fetchone()[0]
        finally:
            conn.close()
        self.stats["total"].set(sum(by_kind.values()))
        for k in ("video", "audio", "image", "document", "database"):
            self.stats[k].set(by_kind.get(k, 0))
        self.stats["done"].set(by_st.get("done", 0))
        self.stats["pending"].set(by_st.get("pending", 0) + by_st.get("processing", 0))
        self.stats["error"].set(by_st.get("error", 0) + by_st.get("crash", 0))
        self.stats["segments"].set(segs)
        self.stats["mismatch"].set(mism)

    def _on_busy(self, busy: bool) -> None:
        self.btn_start.setEnabled(not busy)
        self.btn_verify.setEnabled(not busy)
        self.btn_stop.setEnabled(busy)
        if busy:
            self._t_start = time.time()
            self._timer.start()
        else:
            self._timer.stop()
            self.refresh_stats()
            self.state.data_changed.emit()

    def _on_progress(self, d: int, t: int, m: str) -> None:
        self.progress.setMaximum(max(1, t))
        self.progress.setValue(d if t else 0)
        msg, _, eta = m.partition(" | sisa ~")
        self.cur_file.setText(msg)
        self.lbl_count.setText(f"{d} / {t} file" if t else msg)
        self.lbl_elapsed.setText(f"Berjalan: {fmt_ts(time.time() - self._t_start)[:8]}")
        if eta:
            self.lbl_eta.setText(f"Sisa waktu: ~{eta[:8]}")

    def _need(self) -> bool:
        if not self.state.workspace:
            QMessageBox.warning(self, "Folder bukti", "Pilih FOLDER BARANG BUKTI terlebih dahulu (di bagian atas).")
            return False
        return True

    def busy(self) -> bool:
        return self.runner.busy()

    # ------------------------------------------------------------- aksi
    def options(self) -> ExtractOptions:
        kinds = {k for k, c in self.chk.items() if c.isChecked()}
        if "video" in kinds and not (self.chk_vid_asr.isChecked() or self.chk_vid_ocr.isChecked()):
            kinds.discard("video")
        return ExtractOptions(
            kinds=kinds, whisper_model=self.cmb_model.currentData(), language=self.cmb_lang.currentData(),
            frame_interval=self.spin_interval.value(), video_ocr=self.chk_vid_ocr.isChecked(),
            video_asr=self.chk_vid_asr.isChecked(), pdf_ocr=self.chk_pdf_ocr.isChecked(),
            retry_failed=self.chk_retry.isChecked())

    def start(self) -> None:
        if not self._need() or self.runner.busy():
            return
        opts = self.options()
        if not opts.kinds:
            QMessageBox.warning(self, "Jenis file", "Centang minimal satu jenis file.")
            return
        ws, ev = self.state.workspace, self.state.evidence_dir
        self.phase.setText("BERJALAN — scan, hash, lalu ekstraksi teks (dokumen → foto → audio → video)")
        self.log("=== MULAI EKSTRAKSI ===")

        def job(lg, pr, stop):
            store = CaseStore(ws)  # koneksi DB khusus thread ini
            try:
                return CaseProcessor(store, ev).run(opts, lg, pr, stop)
            finally:
                store.close()
        self.runner.start(job, self._done, self._err)

    def _done(self, st) -> None:
        state = "DIHENTIKAN (bisa dilanjutkan)" if st.stopped else "SELESAI"
        self.phase.setText(f"{state} — diproses {st.processed} file, gagal {st.errors}, waktu {fmt_ts(st.elapsed)[:8]}")
        self.log(f"=== EKSTRAKSI {state}: diproses={st.processed} gagal={st.errors} ===")
        if not st.stopped:
            self.progress.setValue(self.progress.maximum())

    def _err(self, msg: str) -> None:
        self.phase.setText("GAGAL — lihat log")
        self.log(f"[FATAL] {msg}")
        QMessageBox.critical(self, "Gagal", msg)

    def stop(self) -> None:
        self.runner.stop()
        self.log("Permintaan STOP dikirim — menunggu langkah yang sedang berjalan selesai...")
        self.phase.setText("MENGHENTIKAN...")

    def verify(self) -> None:
        if not self._need() or self.runner.busy():
            return
        ws, ev = self.state.workspace, self.state.evidence_dir
        self.phase.setText("VERIFIKASI — menghitung ulang hash semua file bukti")

        def job(lg, pr, stop):
            store = CaseStore(ws)
            try:
                return CaseProcessor(store, ev).verify_integrity(lg, pr, stop)
            finally:
                store.close()
        self.runner.start(job, self._verify_done, self._err)

    def _verify_done(self, res: dict) -> None:
        clean = not res["changed"] and not res["missing"]
        msg = (f"File dicek     : {res['total']}\nHash cocok     : {res['ok']}\n"
               f"Hash BERUBAH   : {len(res['changed'])}\nFile hilang    : {len(res['missing'])}\n\n{res['audit_chain']}")
        self.phase.setText("VERIFIKASI: SEMUA UTUH" if clean else "VERIFIKASI: ADA PERUBAHAN — lihat log")
        self.log("=== VERIFIKASI INTEGRITAS ===")
        for ln in msg.splitlines():
            self.log("  " + ln)
        for p in res["changed"][:200]:
            self.log(f"  [BERUBAH] {p}")
        for p in res["missing"][:200]:
            self.log(f"  [HILANG]  {p}")
        (QMessageBox.information if clean else QMessageBox.warning)(self, "Verifikasi Integritas", msg)

    def shutdown(self) -> None:
        self.runner.shutdown()
