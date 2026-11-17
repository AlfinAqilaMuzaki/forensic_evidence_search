"""Halaman 03 - Pencarian foto mirip (visual, image-to-image)."""
from __future__ import annotations

import os
import subprocess
from pathlib import Path

from PySide6.QtCore import QSize, Qt, Signal
from PySide6.QtGui import QGuiApplication, QIcon, QPixmap
from PySide6.QtWidgets import (
    QCheckBox, QFileDialog, QGridLayout, QHBoxLayout, QLabel, QListWidget, QListWidgetItem, QMessageBox,
    QProgressBar, QSpinBox, QSplitter, QVBoxLayout, QWidget,
)

from .. import config
from ..forensic.extractors import hash_file
from .page_extract import page_header
from .state import AppState
from . import theme
from .widgets import Card, TaskRunner, button, label, themed

IMG_FILTER = "Gambar (*.png *.jpg *.jpeg *.jfif *.webp *.bmp *.tif *.tiff *.gif)"


class DropImage(QLabel):
    dropped = Signal(str)

    def __init__(self):
        super().__init__("SERET FOTO\nKE SINI\n\natau klik\nPILIH FOTO")
        self.setWordWrap(True)
        self.setAlignment(Qt.AlignCenter)
        self.setAcceptDrops(True)
        self.setMinimumSize(170, 170)
        self.setMaximumSize(260, 240)
        from PySide6.QtWidgets import QSizePolicy
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self.setObjectName("Muted")
        themed(self)
        self.on_theme()

    def on_theme(self) -> None:
        self.setStyleSheet(f"border:2px dashed {theme.pal()['accent']};")

    def dragEnterEvent(self, e):  # noqa: N802
        if e.mimeData().hasUrls():
            e.acceptProposedAction()

    def dropEvent(self, e):  # noqa: N802
        urls = e.mimeData().urls()
        if urls:
            self.dropped.emit(urls[0].toLocalFile())


class PhotoPage(QWidget):
    def __init__(self, state: AppState):
        super().__init__()
        self.setObjectName("Page")
        self.setMinimumSize(760, 760)
        self.state = state
        self.query_path: str | None = None
        self.results: list = []
        self.engine_holder: dict = {"engine": None}
        self.idx_runner = TaskRunner(self)
        self.idx_runner.progress.connect(self._idx_progress)
        self.idx_runner.log.connect(lambda m: self.idx_status.setText(m))
        self.idx_runner.busy_changed.connect(self._idx_busy)
        self.s_runner = TaskRunner(self)
        self.s_runner.progress.connect(self._s_progress)
        self.s_runner.busy_changed.connect(self._s_busy)
        self.sec_runner = TaskRunner(self)
        self._build()
        state.evidence_changed.connect(self._on_evidence)

    @property
    def index_dir(self) -> Path | None:
        return config.index_dir_for_dataset(self.state.evidence_dir) if self.state.evidence_dir else None

    # ------------------------------------------------------------------ UI
    def _build(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(18, 14, 18, 14)
        root.setSpacing(12)
        root.addWidget(page_header("PENCARIAN FOTO MIRIP",
                                   "Temukan foto yang sama/mirip walau sudah di-crop, resize, kompres, screenshot, "
                                   "watermark, atau ganti nama  •  CLIP + pHash + ORB"))
        top = QHBoxLayout()
        top.setSpacing(12)

        qc = Card("Foto referensi", "image")
        row = QHBoxLayout()
        self.drop = DropImage()
        self.drop.dropped.connect(self.set_query)
        row.addWidget(self.drop, 1)
        qcol = QVBoxLayout()
        b = button("PILIH FOTO", "folder")
        b.clicked.connect(self.pick_query)
        qcol.addWidget(b)
        self.q_info = label("-", "PathLabel", wrap=True)
        self.q_info.setTextInteractionFlags(Qt.TextSelectableByMouse)
        self.q_info.setMaximumWidth(330)
        self.q_info.setMinimumWidth(150)
        qcol.addWidget(self.q_info)
        qcol.addStretch(1)
        g = QGridLayout()
        g.addWidget(label("Top-N hasil", "Muted"), 0, 0)
        self.topn = QSpinBox()
        self.topn.setRange(5, 500)
        self.topn.setValue(50)
        g.addWidget(self.topn, 0, 1)
        self.rerank = QCheckBox("ORB rerank (tahan crop)")
        self.rerank.setToolTip("Lebih akurat untuk foto yang di-crop/di-screenshot, sedikit lebih lambat")
        self.rerank.setChecked(True)
        g.addWidget(self.rerank, 1, 0, 1, 2)
        qcol.addLayout(g)
        self.btn_search = button("CARI FOTO MIRIP", "search", "Primary")
        self.btn_search.setMinimumHeight(42)
        self.btn_search.clicked.connect(self.search)
        qcol.addWidget(self.btn_search)
        self.s_prog = QProgressBar()
        self.s_prog.setFormat("%p%")
        qcol.addWidget(self.s_prog)
        row.addLayout(qcol, 1)
        qc.body.addLayout(row)
        top.addWidget(qc, 3)

        ic = Card("Index visual", "db", "Index dibuat sekali per folder bukti, lalu cukup UPDATE untuk file baru.")
        self.idx_count = label("-", "StatValue")
        ic.body.addWidget(self.idx_count)
        self.idx_loc = label("-", "PathLabel", wrap=True)
        ic.body.addWidget(self.idx_loc)
        self.idx_prog = QProgressBar()
        self.idx_prog.setFormat("%p%")
        ic.body.addWidget(self.idx_prog)
        self.idx_status = label("", "CardHint", wrap=True)
        ic.body.addWidget(self.idx_status)
        ic.body.addStretch(1)
        br = QHBoxLayout()
        self.btn_full = button("BUILD PENUH", "refresh", "", "Hitung ulang index semua foto dari awal")
        self.btn_full.clicked.connect(lambda: self.build(False))
        self.btn_upd = button("UPDATE", "play", "", "Hanya foto baru/berubah")
        self.btn_upd.clicked.connect(lambda: self.build(True))
        self.btn_istop = button("STOP", "stop", "Danger")
        self.btn_istop.setEnabled(False)
        self.btn_istop.clicked.connect(self.idx_runner.stop)
        for w in (self.btn_full, self.btn_upd, self.btn_istop):
            br.addWidget(w)
        ic.body.addLayout(br)
        top.addWidget(ic, 2)
        root.addLayout(top)

        split = QSplitter(Qt.Horizontal)
        rc = Card("Hasil (paling mirip dulu)", "photo2")
        self.grid = QListWidget()
        self.grid.setObjectName("Grid")
        self.grid.setViewMode(QListWidget.IconMode)
        self.grid.setIconSize(QSize(170, 170))
        self.grid.setGridSize(QSize(196, 236))
        self.grid.setResizeMode(QListWidget.Adjust)
        self.grid.setMovement(QListWidget.Static)
        self.grid.setUniformItemSizes(True)
        self.grid.setWordWrap(True)
        self.grid.setSelectionMode(QListWidget.ExtendedSelection)
        self.grid.itemSelectionChanged.connect(self._detail)
        self.grid.itemDoubleClicked.connect(lambda *_: self.open_file())
        self.res_summary = label("", "CardHint")
        rc.header_row.addWidget(self.res_summary)
        rc.body.addWidget(self.grid)
        ab = QHBoxLayout()
        self.btn_sec_sel = button("AMANKAN TERPILIH", "lock")
        self.btn_sec_sel.clicked.connect(lambda: self.secure(True))
        self.btn_sec_all = button("AMANKAN SEMUA + LAPORAN", "shield", "Primary")
        self.btn_sec_all.clicked.connect(lambda: self.secure(False))
        ab.addStretch(1)
        ab.addWidget(self.btn_sec_sel)
        ab.addWidget(self.btn_sec_all)
        rc.body.addLayout(ab)
        split.addWidget(rc)

        dc = Card("Detail & skor", "eye")
        self.big = label("", "Muted")
        self.big.setAlignment(Qt.AlignCenter)
        self.big.setFixedHeight(230)
        dc.body.addWidget(self.big)
        self.bars = {}
        sg = QGridLayout()
        for i, (k, t) in enumerate((("final", "SKOR AKHIR"), ("clip", "CLIP · isi/semantik"),
                                    ("phash", "pHASH · duplikat global"), ("orb", "ORB · fitur lokal/crop"))):
            sg.addWidget(label(t, "StatCaption"), i, 0)
            bar = QProgressBar()
            bar.setRange(0, 1000)
            bar.setFormat("-")
            bar.setMaximumHeight(18)
            self.bars[k] = bar
            sg.addWidget(bar, i, 1)
        sg.setColumnStretch(1, 1)
        dc.body.addLayout(sg)
        self.verdict = label("", "CardHint", wrap=True)
        dc.body.addWidget(self.verdict)
        self.p_path = label("-", "PathLabel", wrap=True)
        self.p_path.setTextInteractionFlags(Qt.TextSelectableByMouse)
        dc.body.addWidget(self.p_path)
        dc.body.addStretch(1)
        bb = QHBoxLayout()
        b1 = button("BUKA", "open")
        b1.clicked.connect(self.open_file)
        b2 = button("LOKASI FILE", "folder")
        b2.clicked.connect(self.open_location)
        b3 = button("HASH SHA-256", "fingerprint", "", "Hitung & salin hash file terpilih")
        b3.clicked.connect(self.hash_selected)
        for w in (b1, b2, b3):
            bb.addWidget(w)
        dc.body.addLayout(bb)
        split.addWidget(dc)
        split.setSizes([860, 420])
        split.setChildrenCollapsible(False)
        root.addWidget(split, 1)

    # ------------------------------------------------------------------
    def _on_evidence(self) -> None:
        if self.engine_holder.get("engine"):
            self.engine_holder["engine"].close()
        self.engine_holder["engine"] = None
        self.grid.clear()
        self.results = []
        self.refresh_index_info()

    def refresh_index_info(self) -> None:
        d = self.index_dir
        if not d:
            self.idx_count.setText("-")
            self.idx_loc.setText("-")
            self.idx_status.setText("Pilih folder bukti terlebih dahulu.")
            self.idx_prog.setValue(0)
            self.res_summary.setText("")
            return
        self.idx_loc.setText(str(d))
        db = d / config.DB_FILENAME
        if db.exists() and (d / config.FAISS_FILENAME).exists():
            import sqlite3
            c = sqlite3.connect(f"file:{db.as_posix()}?mode=ro", uri=True)
            try:
                n = c.execute("SELECT COUNT(*) FROM images WHERE status='ok'").fetchone()[0]
                bad = c.execute("SELECT COUNT(*) FROM images WHERE status='corrupt'").fetchone()[0]
            finally:
                c.close()
            self.idx_count.setText(f"{n:,} FOTO".replace(",", "."))
            self.idx_status.setText(f"Index siap. {bad} file rusak/tidak terbaca." if bad else "Index siap.")
        else:
            self.idx_count.setText("BELUM ADA INDEX")
            self.idx_status.setText("Tekan BUILD PENUH untuk membuat index foto dari folder bukti.")

    def pick_query(self) -> None:
        p, _ = QFileDialog.getOpenFileName(self, "Pilih Foto Referensi", "", IMG_FILTER)
        if p:
            self.set_query(p)

    def set_query(self, p: str) -> None:
        pix = QPixmap(p)
        if pix.isNull():
            QMessageBox.warning(self, "Foto", "File bukan gambar yang bisa dibuka.")
            return
        self.query_path = p
        self.drop.setPixmap(pix.scaled(max(160, self.drop.width() - 6), max(160, self.drop.height() - 6),
                                       Qt.KeepAspectRatio, Qt.SmoothTransformation))
        try:
            sha, _ = hash_file(p)
        except OSError:
            sha = "-"
        short = f"{sha[:20]}…{sha[-8:]}" if len(sha) > 30 else sha
        self.q_info.setText(f"{p}\nSHA-256: {short}")
        self.q_info.setToolTip(f"{p}\nSHA-256: {sha}")

    # -------------------------------------------------------------- index
    def _need(self) -> bool:
        if not self.state.evidence_dir:
            QMessageBox.warning(self, "Folder bukti", "Pilih FOLDER BARANG BUKTI terlebih dahulu.")
            return False
        return True

    def build(self, incremental: bool) -> None:
        if not self._need() or self.idx_runner.busy():
            return
        if not incremental and QMessageBox.question(
                self, "Build penuh", "Hitung ulang index visual SEMUA foto dari awal?") != QMessageBox.Yes:
            return
        ev, idx = self.state.evidence_dir, str(self.index_dir)

        def job(lg, pr, stop):
            from ..indexer import Indexer
            return Indexer(ev, idx).build(incremental=incremental, progress_cb=pr, log_cb=lg, should_stop=stop)
        if self.engine_holder.get("engine"):
            self.engine_holder["engine"].close()
            self.engine_holder["engine"] = None
        if self.state.store:
            self.state.store.audit("INDEX_VISUAL", f"mulai {'update' if incremental else 'build penuh'}")
        self.idx_runner.start(job, self._build_done, lambda m: QMessageBox.critical(self, "Index gagal", m))

    def _build_done(self, st) -> None:
        self.idx_prog.setValue(self.idx_prog.maximum())
        self.refresh_index_info()
        self.idx_status.setText(f"Selesai: OK={st.processed_ok}  rusak={st.processed_error}  "
                                f"tak berubah={st.unchanged_skipped}  waktu={st.elapsed_sec:.0f}s")
        if self.state.store:
            self.state.store.audit("INDEX_VISUAL", f"selesai ok={st.processed_ok} error={st.processed_error}")

    def _idx_busy(self, b: bool) -> None:
        self.btn_full.setEnabled(not b)
        self.btn_upd.setEnabled(not b)
        self.btn_istop.setEnabled(b)

    def _idx_progress(self, d, t, m) -> None:
        self.idx_prog.setMaximum(max(1, t))
        self.idx_prog.setValue(d)
        self.idx_status.setText(f"{d}/{t}  {m}")

    # ------------------------------------------------------------- search
    def search(self) -> None:
        if not self._need() or self.s_runner.busy():
            return
        if not self.query_path:
            QMessageBox.warning(self, "Foto referensi", "Pilih / seret foto referensi dulu.")
            return
        d = self.index_dir
        if not (d / config.DB_FILENAME).exists() or not (d / config.FAISS_FILENAME).exists():
            QMessageBox.warning(self, "Index", "Index visual belum ada. Tekan BUILD PENUH dulu.")
            return
        holder, q, n, rr = self.engine_holder, self.query_path, self.topn.value(), self.rerank.isChecked()

        def job(_lg, pr, _stop):
            from ..search import SearchEngine
            from ..thumbnails import ThumbnailCache
            eng = holder.get("engine")
            if eng is None or eng.index_dir != d:
                pr(0, 0, "memuat model & index…")
                eng = SearchEngine(str(d))
                holder["engine"] = eng
            res = eng.search(q, top_n=n, use_rerank=rr, progress_cb=pr)
            tc = ThumbnailCache(d)
            thumbs = [tc.get_or_create(r.id, r.path) for r in res]
            return res, thumbs
        self.grid.clear()
        self.s_runner.start(job, self._show, lambda m: QMessageBox.critical(self, "Pencarian gagal", m))

    def _s_busy(self, b: bool) -> None:
        self.btn_search.setEnabled(not b)
        self.btn_search.setText("MENCARI…" if b else "CARI FOTO MIRIP")

    def _s_progress(self, d, t, m) -> None:
        self.s_prog.setMaximum(max(1, t))
        self.s_prog.setValue(d)

    def _show(self, res) -> None:
        results, thumbs = res
        self.results = results
        self.s_prog.setValue(self.s_prog.maximum())
        for rank, (r, tp) in enumerate(zip(results, thumbs), 1):
            it = QListWidgetItem(QIcon(tp) if tp else QIcon(),
                                 f"#{rank}  {r.final_score:.3f}\n{Path(r.path).name}")
            it.setData(Qt.UserRole, rank - 1)
            it.setToolTip(r.path)
            self.grid.addItem(it)
        strong = sum(1 for r in results if r.phash_sim >= 0.8 or (r.orb_score or 0) >= 0.5)
        self.res_summary.setText(f"{len(results)} HASIL  •  {strong} kemungkinan foto SAMA (near-duplicate)")
        if self.state.store:
            self.state.store.audit("PENCARIAN_FOTO", f"referensi={self.query_path} hasil={len(results)}")
        if results:
            self.grid.setCurrentRow(0)

    def _sel(self) -> list:
        return [self.results[i.data(Qt.UserRole)] for i in self.grid.selectedItems()]

    def _detail(self) -> None:
        sel = self._sel()
        if not sel:
            return
        r = sel[0]
        pix = QPixmap(r.path)
        if not pix.isNull():
            self.big.setPixmap(pix.scaled(max(200, self.big.width() - 4), 224, Qt.KeepAspectRatio,
                                          Qt.SmoothTransformation))
        for k, v in (("final", r.final_score), ("clip", r.clip_sim), ("phash", r.phash_sim), ("orb", r.orb_score)):
            bar = self.bars[k]
            if v is None:
                bar.setValue(0)
                bar.setFormat("tidak dihitung")
            else:
                bar.setValue(int(max(0.0, min(1.0, v)) * 1000))
                bar.setFormat(f"{v:.3f}")
        if r.phash_sim >= 0.85 or (r.orb_score or 0) >= 0.6:
            v = "◆ SANGAT MUNGKIN FOTO YANG SAMA (diubah/di-crop/dikompres)."
        elif r.clip_sim >= 0.85:
            v = "◇ Isi/scene sangat mirip — periksa visual apakah foto yang sama."
        else:
            v = "○ Mirip secara umum — kandidat untuk diperiksa manual."
        self.verdict.setText(v)
        self.p_path.setText(f"{r.path}\n{r.width}×{r.height}px")

    def open_file(self) -> None:
        sel = self._sel()
        if sel and os.path.exists(sel[0].path):
            os.startfile(sel[0].path)  # type: ignore[attr-defined]

    def open_location(self) -> None:
        sel = self._sel()
        if sel:
            subprocess.run(["explorer", "/select,", str(Path(sel[0].path))])

    def hash_selected(self) -> None:
        sel = self._sel()
        if not sel:
            return
        sha, md5 = hash_file(sel[0].path)
        QGuiApplication.clipboard().setText(f"{sel[0].path}\nSHA-256: {sha}\nMD5: {md5}")
        self.p_path.setText(f"{sel[0].path}\nSHA-256: {sha}\nMD5: {md5}\n(disalin ke clipboard)")

    def secure(self, selected_only: bool) -> None:
        if not self.results or self.sec_runner.busy() or not self.state.workspace:
            return
        items = self._sel() if selected_only else list(self.results)
        if not items:
            return
        ws, q = self.state.workspace, self.query_path

        def job(lg, pr, _stop):
            from ..forensic.report import secure_photo_results
            from ..forensic.store import CaseStore
            store = CaseStore(ws)
            try:
                return secure_photo_results(store, items, q, lg, pr)
            finally:
                store.close()

        def done(out):
            self.state.data_changed.emit()
            QMessageBox.information(self, "Bukti diamankan", f"{len(items)} foto diamankan di:\n{out}")
            try:
                os.startfile(str(out / "laporan.html"))  # type: ignore[attr-defined]
            except OSError:
                pass
        self.sec_runner.start(job, done, lambda m: QMessageBox.critical(self, "Gagal", m))

    def shutdown(self) -> None:
        for r in (self.idx_runner, self.s_runner, self.sec_runner):
            r.shutdown()
        if self.engine_holder.get("engine"):
            self.engine_holder["engine"].close()
