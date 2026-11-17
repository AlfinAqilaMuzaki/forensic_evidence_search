"""Riwayat analisis (CRUD): buat baru, lihat/buka, ubah nama & catatan, hapus.

Setiap folder bukti punya workspace sendiri di DATA_ANALISIS/<nama>_<hash>.
"Ulang dari awal" memindahkan workspace lama ke DATA_ANALISIS/_ARSIP (bukan menghapus).
"""
from __future__ import annotations

import os
import shutil
import sqlite3
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from PySide6.QtWidgets import (
    QAbstractItemView, QDialog, QDialogButtonBox, QFormLayout, QHBoxLayout, QHeaderView, QLineEdit,
    QMessageBox, QPlainTextEdit, QTableView, QVBoxLayout,
)

from ..forensic import fconfig
from ..workspace import DATA_ROOT
from .widgets import RowsModel, button, label

ARCHIVE_DIR = "_ARSIP"


@dataclass
class WorkspaceInfo:
    path: Path
    evidence_dir: str
    name: str
    note: str
    created: str
    modified: float
    n_files: int
    n_done: int
    n_segments: int
    n_packages: int
    size_mb: float
    archived: bool

    @property
    def evidence_exists(self) -> bool:
        return bool(self.evidence_dir) and os.path.isdir(self.evidence_dir)

    @property
    def display_name(self) -> str:
        return self.name or Path(self.evidence_dir).name or self.path.name


def _dir_size_mb(p: Path) -> float:
    total = 0
    for root, _dirs, files in os.walk(p):
        for f in files:
            try:
                total += os.path.getsize(os.path.join(root, f))
            except OSError:
                pass
    return total / 1024 / 1024


def _read(ws: Path, archived: bool) -> Optional[WorkspaceInfo]:
    db = ws / fconfig.CASE_DB
    if not db.exists():
        return None
    try:
        c = sqlite3.connect(f"file:{db.as_posix()}?mode=ro", uri=True, timeout=10)
        try:
            info = dict(c.execute("SELECT key, value FROM case_info"))
            n_files = c.execute("SELECT COUNT(*) FROM files").fetchone()[0]
            n_done = c.execute("SELECT COUNT(*) FROM files WHERE status='done'").fetchone()[0]
            n_seg = c.execute("SELECT COUNT(*) FROM segments").fetchone()[0]
        finally:
            c.close()
    except sqlite3.DatabaseError:
        return None
    sec = ws / fconfig.SECURED_DIR
    n_pk = len([d for d in sec.iterdir() if d.is_dir()]) if sec.exists() else 0
    return WorkspaceInfo(ws, info.get("evidence_dir", ""), info.get("analysis_name", ""), info.get("analysis_note", ""),
                         info.get("created_at", "-"), db.stat().st_mtime, n_files, n_done, n_seg, n_pk,
                         _dir_size_mb(ws), archived)


def list_workspaces() -> list[WorkspaceInfo]:
    out = []
    if DATA_ROOT.exists():
        for d in DATA_ROOT.iterdir():
            if d.is_dir() and d.name != ARCHIVE_DIR:
                w = _read(d, False)
                if w:
                    out.append(w)
        arc = DATA_ROOT / ARCHIVE_DIR
        if arc.exists():
            for d in arc.iterdir():
                if d.is_dir():
                    w = _read(d, True)
                    if w:
                        out.append(w)
    out.sort(key=lambda w: (w.archived, -w.modified))
    return out


def archive_workspace(ws: Path) -> Path:
    """Pindahkan workspace ke DATA_ANALISIS/_ARSIP/<nama>_<waktu> (tidak menghapus apa pun)."""
    dest_root = DATA_ROOT / ARCHIVE_DIR
    dest_root.mkdir(parents=True, exist_ok=True)
    dest = dest_root / f"{ws.name}_{time.strftime('%Y%m%d_%H%M%S')}"
    shutil.move(str(ws), str(dest))
    return dest


def _make_writable(func, path, _exc):
    # salinan bukti di paket diamankan bersifat read-only -> buka dulu agar bisa dihapus
    os.chmod(path, 0o666)
    func(path)


def delete_workspace(ws: Path) -> None:
    shutil.rmtree(ws, onerror=_make_writable)


def update_workspace_info(ws: Path, name: str, note: str) -> None:
    """Ubah nama & catatan analisis; perubahan dicatat di audit log workspace itu."""
    from ..forensic.store import CaseStore

    st = CaseStore(ws)
    try:
        old = (st.get_info("analysis_name"), st.get_info("analysis_note"))
        st.set_info("analysis_name", name)
        st.set_info("analysis_note", note)
        if old != (name, note):
            st.audit("UBAH_INFO_ANALISIS", f"nama: '{old[0]}' -> '{name}'; catatan diperbarui"
                     if old[1] != note else f"nama: '{old[0]}' -> '{name}'")
    finally:
        st.close()


class EditInfoDialog(QDialog):
    def __init__(self, parent, w: WorkspaceInfo):
        super().__init__(parent)
        self.setWindowTitle("Ubah nama & catatan analisis")
        self.resize(560, 300)
        f = QFormLayout(self)
        self.name = QLineEdit(w.name)
        self.name.setPlaceholderText(f"mis. Kasus penipuan online — {Path(w.evidence_dir).name}")
        self.note = QPlainTextEdit(w.note)
        self.note.setPlaceholderText("Catatan bebas: nomor LP, pemeriksa, status, dsb.")
        f.addRow(label("Folder bukti", "Muted"), label(w.evidence_dir, "PathLabel", wrap=True))
        f.addRow(label("Nama analisis", "Muted"), self.name)
        f.addRow(label("Catatan", "Muted"), self.note)
        bb = QDialogButtonBox(QDialogButtonBox.Save | QDialogButtonBox.Cancel)
        bb.button(QDialogButtonBox.Save).setText("SIMPAN")
        bb.button(QDialogButtonBox.Cancel).setText("BATAL")
        bb.accepted.connect(self.accept)
        bb.rejected.connect(self.reject)
        f.addRow(bb)


class HistoryDialog(QDialog):
    """CRUD analisis: BARU, BUKA, UBAH NAMA/CATATAN, FOLDER DATA, HAPUS (banyak sekaligus), HAPUS SEMUA ARSIP."""

    def __init__(self, parent, current_ws: Optional[Path], busy: bool):
        super().__init__(parent)
        self.setWindowTitle("Riwayat Analisis")
        self.resize(1320, 580)
        self.current_ws = current_ws
        self.busy = busy
        self.chosen: Optional[WorkspaceInfo] = None
        self.want_new = False
        self.deleted_current = False
        v = QVBoxLayout(self)
        v.addWidget(label("RIWAYAT ANALISIS", "PageTitle"))
        v.addWidget(label("Kelola semua analisis: buat BARU, BUKA untuk melanjutkan, UBAH nama/catatan, atau HAPUS "
                          "yang sudah tidak dipakai agar ruang disk lega. Pilih banyak baris dengan Ctrl/Shift. "
                          "Baris ARSIP adalah hasil 'Ulang dari awal'. File bukti asli tidak pernah ikut terhapus.",
                          "CardHint", wrap=True))
        self.model = RowsModel(["Status", "Nama analisis", "Folder bukti", "Dibuat", "Diubah", "File", "Selesai",
                                "Segmen", "Paket", "Ukuran (MB)", "Catatan", "Lokasi data"])
        self.model.colors[0] = lambda r: {"AKTIF": "ok", "ARSIP": "muted", "BUKTI TIDAK ADA": "warn"}.get(r[0])
        self.model.align_right.update({5, 6, 7, 8, 9})
        self.table = QTableView()
        self.table.setModel(self.model)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.ExtendedSelection)
        self.table.verticalHeader().setVisible(False)
        self.table.setAlternatingRowColors(True)
        self.table.setSortingEnabled(True)
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.Interactive)
        self.table.horizontalHeader().setStretchLastSection(True)
        for i, wdt in enumerate((140, 200, 260, 150, 130, 55, 70, 75, 60, 90, 180)):
            self.table.setColumnWidth(i, wdt)
        self.table.doubleClicked.connect(lambda *_: self.open_selected())
        v.addWidget(self.table, 1)
        self.summary = label("", "CardHint")
        v.addWidget(self.summary)

        r1 = QHBoxLayout()
        b_new = button("ANALISIS BARU", "refresh", "Primary", "Tutup analisis sekarang & pilih folder bukti baru")
        b_new.clicked.connect(self.new_analysis)
        b_open = button("BUKA ANALISIS", "play", "", "Lanjutkan analisis terpilih (double-click juga bisa)")
        b_open.clicked.connect(self.open_selected)
        b_edit = button("UBAH NAMA / CATATAN", "text")
        b_edit.clicked.connect(self.edit_selected)
        b_folder = button("BUKA FOLDER DATA", "folder", "", "Laporan, paket bukti diamankan, teks ekstraksi, audit log")
        b_folder.clicked.connect(self.open_folder)
        for b in (b_new, b_open, b_edit, b_folder):
            r1.addWidget(b)
        r1.addStretch(1)
        b_del = button("HAPUS TERPILIH", "stop", "Danger", "Hapus permanen analisis yang dipilih (bisa lebih dari satu)")
        b_del.clicked.connect(self.delete_selected)
        b_del_arc = button("HAPUS SEMUA ARSIP", "stop", "Danger", "Hapus semua analisis berstatus ARSIP")
        b_del_arc.clicked.connect(self.delete_all_archives)
        b_close = button("TUTUP", "", "Ghost")
        b_close.clicked.connect(self.reject)
        for b in (b_del, b_del_arc, b_close):
            r1.addWidget(b)
        v.addLayout(r1)
        self.reload()

    # ------------------------------------------------------------- READ
    def reload(self) -> None:
        rows, pay = [], []
        infos = list_workspaces()
        for w in infos:
            if w.archived:
                st = "ARSIP"
            elif self.current_ws and w.path.resolve() == self.current_ws.resolve():
                st = "AKTIF"
            elif not w.evidence_exists:
                st = "BUKTI TIDAK ADA"
            else:
                st = "TERSIMPAN"
            rows.append([st, w.display_name, w.evidence_dir, w.created[:19],
                         time.strftime("%Y-%m-%d %H:%M", time.localtime(w.modified)), w.n_files, w.n_done,
                         w.n_segments, w.n_packages, round(w.size_mb, 1), w.note.replace("\n", " "), str(w.path)])
            pay.append(w)
        self.model.set_rows(rows, pay)
        total = sum(w.size_mb for w in infos)
        arch = [w for w in infos if w.archived]
        self.summary.setText(
            f"{len(infos)} analisis  •  total data {total:,.1f} MB  •  {len(arch)} arsip "
            f"({sum(w.size_mb for w in arch):,.1f} MB)  •  lokasi: {DATA_ROOT}" if infos else
            "Belum ada analisis tersimpan. Klik ANALISIS BARU untuk memulai.")
        if rows:
            self.table.selectRow(0)

    def _selected(self) -> list[WorkspaceInfo]:
        return [self.model.payload[i.row()] for i in self.table.selectionModel().selectedRows()]

    def _cur(self) -> Optional[WorkspaceInfo]:
        s = self._selected()
        return s[0] if s else None

    def _is_current(self, w: WorkspaceInfo) -> bool:
        return bool(self.current_ws) and w.path.resolve() == self.current_ws.resolve()

    # ----------------------------------------------------------- CREATE
    def new_analysis(self) -> None:
        self.want_new = True
        self.accept()

    def open_selected(self) -> None:
        w = self._cur()
        if not w:
            return
        if w.archived:
            QMessageBox.information(self, "Arsip", "Analisis arsip hanya bisa dilihat isinya lewat BUKA FOLDER DATA "
                                    "(laporan, bukti diamankan, teks hasil ekstraksi, audit log).")
            return
        if not w.evidence_exists:
            QMessageBox.warning(self, "Folder bukti tidak ditemukan",
                                f"Folder bukti tidak ada di komputer ini:\n{w.evidence_dir}\n\n"
                                "Sambungkan dulu drive/flashdisk berisi bukti tersebut, lalu coba lagi.")
            return
        self.chosen = w
        self.accept()

    def open_folder(self) -> None:
        w = self._cur()
        if w:
            os.startfile(str(w.path))  # type: ignore[attr-defined]

    # ----------------------------------------------------------- UPDATE
    def edit_selected(self) -> None:
        w = self._cur()
        if not w:
            return
        dlg = EditInfoDialog(self, w)
        if dlg.exec():
            try:
                update_workspace_info(w.path, dlg.name.text().strip(), dlg.note.toPlainText().strip())
            except Exception as exc:  # noqa: BLE001
                QMessageBox.critical(self, "Gagal menyimpan", str(exc))
            self.reload()

    # ----------------------------------------------------------- DELETE
    def _delete(self, items: list[WorkspaceInfo], title: str) -> None:
        if not items:
            return
        if self.busy and any(self._is_current(w) for w in items):
            QMessageBox.warning(self, "Sedang dipakai", "Analisis yang aktif sedang berjalan. Hentikan prosesnya dulu.")
            return
        size = sum(w.size_mb for w in items)
        pk = sum(w.n_packages for w in items)
        lines = "\n".join(f"  • {w.display_name}  ({w.size_mb:,.1f} MB{', ARSIP' if w.archived else ''})"
                          for w in items[:12])
        more = f"\n  … dan {len(items) - 12} lainnya" if len(items) > 12 else ""
        msg = (f"HAPUS PERMANEN {len(items)} analisis?\n\n{lines}{more}\n\n"
               f"Ruang disk yang dikosongkan: {size:,.1f} MB\n"
               f"Ikut terhapus: teks hasil ekstraksi, index foto, audit log, dan {pk} paket bukti diamankan "
               f"beserta laporannya.\nFile bukti asli TIDAK tersentuh.\n\n"
               f"Pastikan laporan/paket bukti yang masih dibutuhkan sudah diarsip. Lanjutkan?")
        if QMessageBox.warning(self, title, msg, QMessageBox.Yes | QMessageBox.No, QMessageBox.No) != QMessageBox.Yes:
            return
        if any(self._is_current(w) for w in items):
            self.deleted_current = True
            self.parent().close_current_for_delete()
            self.current_ws = None
        failed = []
        for w in items:
            try:
                delete_workspace(w.path)
            except OSError as exc:
                failed.append(f"{w.display_name}: {exc}")
        if failed:
            QMessageBox.critical(self, "Sebagian gagal dihapus",
                                 "\n".join(failed) + "\n\nTutup file/laporan yang sedang terbuka lalu coba lagi.")
        self.reload()

    def delete_selected(self) -> None:
        self._delete(self._selected(), "Hapus analisis terpilih")

    def delete_all_archives(self) -> None:
        arch = [w for w in self.model.payload if w.archived]
        if not arch:
            QMessageBox.information(self, "Arsip", "Tidak ada analisis berstatus ARSIP.")
            return
        self._delete(arch, "Hapus semua arsip")
