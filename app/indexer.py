"""Pipeline indexing: folder gambar -> hash + embedding -> SQLite + FAISS.

    Folder dataset (~200.000 gambar)
        -> scan file (path, size, mtime -- HANYA untuk incremental indexing)
        -> baca gambar (utils.safe_open_image, skip file corrupt)
        -> preprocessing (resize sesuai input CLIP)
        -> ekstraksi pHash/dHash (hashing.py) + embedding visual (embedding.py)
        -> simpan phash/dhash + path asli ke SQLite (db.py)
        -> simpan embedding ke FAISS HNSW index (vector_index.py), id = id SQLite

File sumber TIDAK PERNAH ditulis/dipindah/dihapus. Index (SQLite + FAISS)
disimpan di app-data folder terpisah (lihat config.index_dir_for_dataset).
"""
from __future__ import annotations

import logging
import shutil
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Optional

import numpy as np

from . import config
from .db import Catalog
from .embedding import ClipEmbedder
from .utils import iter_image_files
from .vector_index import VectorIndex

logger = logging.getLogger(__name__)

ProgressCb = Callable[[int, int, str], None]  # (done, total, message)
LogCb = Callable[[str], None]
StopCheck = Callable[[], bool]


@dataclass
class IndexStats:
    total_found: int = 0
    to_process: int = 0
    processed_ok: int = 0
    processed_error: int = 0
    unchanged_skipped: int = 0
    missing_marked: int = 0
    elapsed_sec: float = 0.0
    stopped_early: bool = False
    errors: list[tuple[str, str]] = field(default_factory=list)


class Indexer:
    def __init__(self, dataset_dir: str, index_dir: Optional[str] = None):
        self.dataset_dir = Path(dataset_dir)
        self.index_dir = Path(index_dir) if index_dir else config.index_dir_for_dataset(dataset_dir)
        self.index_dir.mkdir(parents=True, exist_ok=True)
        self.db_path = self.index_dir / config.DB_FILENAME
        self.faiss_path = self.index_dir / config.FAISS_FILENAME

    def wipe(self) -> None:
        """Hapus index yang ada (bukan file dataset!) untuk full rebuild bersih."""
        for p in (self.db_path, self.faiss_path):
            if p.exists():
                p.unlink()
        wal = self.db_path.with_suffix(".db-wal")
        shm = self.db_path.with_suffix(".db-shm")
        for p in (wal, shm):
            if p.exists():
                p.unlink()

    def build(
        self,
        incremental: bool = True,
        progress_cb: Optional[ProgressCb] = None,
        log_cb: Optional[LogCb] = None,
        should_stop: Optional[StopCheck] = None,
    ) -> IndexStats:
        t0 = time.time()
        stats = IndexStats()

        def log(msg: str) -> None:
            logger.info(msg)
            if log_cb:
                log_cb(msg)

        if not incremental:
            log("Full rebuild: menghapus index lama...")
            self.wipe()

        db = Catalog(self.db_path)
        vindex = VectorIndex.load_or_create(self.faiss_path)

        log(f"Scanning folder dataset: {self.dataset_dir}")
        files = list(iter_image_files(self.dataset_dir))
        stats.total_found = len(files)
        log(f"Ditemukan {stats.total_found} file gambar (format didukung).")

        found_paths = {f.path for f in files}
        known = db.get_known_files() if incremental else {}

        missing_paths = [p for p in known if p not in found_paths]
        if missing_paths:
            db.mark_missing(missing_paths)
            stats.missing_marked = len(missing_paths)
            log(f"{len(missing_paths)} file yang sebelumnya ter-index sudah tidak ada di folder, ditandai 'missing'.")

        to_process = []
        for f in files:
            prev = known.get(f.path)
            if prev is not None and prev == (f.size, f.mtime):
                stats.unchanged_skipped += 1
                continue
            to_process.append(f)
        stats.to_process = len(to_process)
        log(f"Perlu diproses (baru/berubah): {stats.to_process} file. Dilewati (tidak berubah): {stats.unchanged_skipped}.")

        if not to_process:
            db.commit()
            db.close()
            stats.elapsed_sec = time.time() - t0
            log("Tidak ada file baru untuk di-index.")
            return stats

        ids: list[int] = []
        paths: list[str] = []
        for f in to_process:
            image_id = db.upsert_pending(f.path, f.size, f.mtime)
            ids.append(image_id)
            paths.append(f.path)
        db.commit()

        log("Memuat model CLIP (sekali di awal, dipakai untuk seluruh batch)...")
        embedder = ClipEmbedder()
        log(f"Model dijalankan di: {embedder.device}")

        pending_ids: list[int] = []
        pending_vecs: list[np.ndarray] = []
        done = 0
        since_commit = 0
        since_save = 0

        for batch in embedder.process_paths_batched(paths):
            for record, emb in batch:
                image_id = ids[record.idx]
                if emb is None:
                    db.set_error(image_id, record.error or "unknown error")
                    stats.processed_error += 1
                    if len(stats.errors) < 200:  # jangan biarkan daftar error membengkak tanpa batas
                        stats.errors.append((paths[record.idx], record.error))
                else:
                    db.set_success(image_id, record.width, record.height, record.phash, record.dhash)
                    pending_ids.append(image_id)
                    pending_vecs.append(emb)
                    stats.processed_ok += 1
                done += 1
                since_commit += 1
                since_save += 1

            if since_commit >= config.DB_COMMIT_EVERY:
                db.commit()
                since_commit = 0

            if pending_vecs and len(pending_vecs) >= config.DB_COMMIT_EVERY:
                vindex.add(np.array(pending_ids, dtype=np.int64), np.stack(pending_vecs))
                pending_ids, pending_vecs = [], []

            if since_save >= 5000:
                vindex.save(self.faiss_path)
                since_save = 0
                log(f"Checkpoint: {done}/{stats.to_process} diproses, index sementara disimpan.")

            if progress_cb:
                progress_cb(done, stats.to_process, Path(paths[record.idx]).name)

            if should_stop and should_stop():
                stats.stopped_early = True
                log("Dihentikan oleh pengguna, menyimpan progres yang sudah ada...")
                break

        if pending_vecs:
            vindex.add(np.array(pending_ids, dtype=np.int64), np.stack(pending_vecs))

        db.commit()
        vindex.save(self.faiss_path)
        db.set_meta("dataset_dir", str(self.dataset_dir))
        db.set_meta("last_build_time", str(time.time()))
        db.set_meta("embedding_model", f"{config.CLIP_MODEL_NAME}/{config.CLIP_PRETRAINED}")
        db.close()

        stats.elapsed_sec = time.time() - t0
        log(
            f"Selesai. OK={stats.processed_ok} Error={stats.processed_error} "
            f"dalam {stats.elapsed_sec:.1f}s."
        )
        return stats
