"""Orkestrasi pencarian: 1 foto referensi -> Top-N gambar paling mirip secara visual.

Alur (lihat juga README):
    foto referensi
    -> preprocessing yang sama seperti saat indexing
    -> hitung pHash/dHash + embedding CLIP
    -> cari kandidat via FAISS (semantic/visual, tahan resize/compress/watermark)
    -> cari kandidat via Hamming distance pHash (near-duplicate cepat)
    -> gabungkan kandidat, hitung skor awal
    -> rerank kandidat teratas dengan ORB+RANSAC (tahan crop)
    -> gabungkan jadi skor akhir, urutkan, kembalikan Top-N

Similarity score BUKAN bukti identik -- hanya ukuran kemiripan untuk
mengurutkan kandidat. Verifikasi visual akhir tetap oleh pengguna (lihat
README bagian "Bagaimana menghindari false positive").
"""
from __future__ import annotations

import logging
import os
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Optional

import numpy as np

from . import config
from .db import Catalog
from .embedding import ClipEmbedder
from .hashing import compute_hashes, hex_to_bytes
from .rerank import load_query_gray, orb_match_score
from .utils import hamming_distance_batch, safe_open_image
from .vector_index import VectorIndex

logger = logging.getLogger(__name__)

ProgressCb = Callable[[int, int, str], None]


@dataclass
class SearchResult:
    id: int
    path: str
    final_score: float
    clip_sim: float
    phash_sim: float
    orb_score: Optional[float]
    width: int
    height: int


class SearchEngine:
    """Muat index sekali, lalu bisa dipakai berkali-kali untuk banyak query."""

    def __init__(self, index_dir: str, embedder: Optional[ClipEmbedder] = None):
        self.index_dir = Path(index_dir)
        self.db_path = self.index_dir / config.DB_FILENAME
        self.faiss_path = self.index_dir / config.FAISS_FILENAME
        if not self.db_path.exists() or not self.faiss_path.exists():
            raise FileNotFoundError(
                f"Index belum ada di {self.index_dir}. Jalankan 'Build Index' terlebih dahulu."
            )

        self.db = Catalog(self.db_path)
        self.vindex = VectorIndex.load(self.faiss_path)
        self.embedder = embedder or ClipEmbedder()

        rows = self.db.fetch_all_hashes()  # [(id, phash_hex, dhash_hex), ...]
        self._hash_ids = np.array([r[0] for r in rows], dtype=np.int64)
        if rows:
            self._phash_bytes = np.stack([hex_to_bytes(r[1]) for r in rows])
        else:
            self._phash_bytes = np.zeros((0, 0), dtype=np.uint8)
        self._phash_bits = len(rows[0][1]) * 4 if rows else 1
        logger.info("SearchEngine siap: %d gambar ter-index.", len(rows))

    def close(self) -> None:
        self.db.close()

    def search(
        self,
        query_path: str,
        top_n: int = 50,
        use_rerank: bool = True,
        progress_cb: Optional[ProgressCb] = None,
    ) -> list[SearchResult]:
        t0 = time.time()
        query_img = safe_open_image(query_path)
        if query_img is None:
            raise ValueError(f"Foto referensi tidak bisa dibuka/rusak: {query_path}")

        q_phash, q_dhash = compute_hashes(query_img)
        q_embedding = self.embedder.embed_single(query_img)
        query_img.close()

        # --- 1. kandidat dari CLIP ANN search -----------------------------------
        clip_ids, clip_sims = self.vindex.search(q_embedding, config.CLIP_CANDIDATE_K)
        clip_sim_map = {int(i): float(s) for i, s in zip(clip_ids, clip_sims)}

        # --- 2. kandidat dari perceptual-hash Hamming search --------------------
        hash_id_pool: list[int] = []
        if len(self._hash_ids):
            q_bytes = hex_to_bytes(q_phash)
            dists = hamming_distance_batch(q_bytes, self._phash_bytes)
            k = min(config.HASH_CANDIDATE_K, len(dists))
            nearest_idx = np.argpartition(dists, k - 1)[:k]
            hash_id_pool = self._hash_ids[nearest_idx].tolist()

        merged_ids = set(clip_sim_map.keys()) | set(hash_id_pool)
        if not merged_ids:
            return []

        rows = self.db.fetch_rows(list(merged_ids))

        # --- 3. skor awal (clip exact via reconstruct + phash exact) -----------
        prelim: dict[int, dict] = {}
        for image_id in merged_ids:
            row = rows.get(image_id)
            if row is None or row["status"] != "ok" or not os.path.exists(row["path"]):
                continue
            clip_sim = clip_sim_map.get(image_id)
            if clip_sim is None:
                vec = self.vindex.reconstruct(image_id)
                clip_sim = float(np.dot(vec, q_embedding)) if vec is not None else 0.0
            cand_phash_bytes = hex_to_bytes(row["phash"])
            dist = int(hamming_distance_batch(hex_to_bytes(q_phash), cand_phash_bytes[None, :])[0])
            phash_sim = 1.0 - (dist / self._phash_bits)
            prelim[image_id] = {
                "row": row,
                "clip_sim": max(0.0, clip_sim),
                "phash_sim": max(0.0, phash_sim),
            }

        if not prelim:
            return []

        # urutkan berdasarkan skor awal (tanpa ORB) untuk memilih pool rerank
        def prelim_score(v: dict) -> float:
            return 0.6 * v["clip_sim"] + 0.4 * v["phash_sim"]

        ranked_prelim = sorted(prelim.items(), key=lambda kv: prelim_score(kv[1]), reverse=True)
        pool = ranked_prelim[: config.RERANK_POOL_SIZE]

        # --- 4. rerank dengan ORB+RANSAC (tahan crop) ---------------------------
        results: list[SearchResult] = []
        query_gray = load_query_gray(query_path) if use_rerank else None
        total = len(pool)
        for i, (image_id, v) in enumerate(pool):
            row = v["row"]
            orb_score = None
            if use_rerank and query_gray is not None:
                try:
                    orb_score = orb_match_score(query_gray, row["path"])
                except Exception as exc:  # noqa: BLE001
                    logger.warning("ORB rerank gagal untuk %s: %s", row["path"], exc)
                    orb_score = 0.0
            final = config.WEIGHT_CLIP * v["clip_sim"] + config.WEIGHT_PHASH * v["phash_sim"]
            if orb_score is not None:
                final += config.WEIGHT_ORB * orb_score
            else:
                # normalisasi ulang bobot bila ORB tidak dijalankan
                denom = config.WEIGHT_CLIP + config.WEIGHT_PHASH
                final = final / denom if denom > 0 else final
            results.append(
                SearchResult(
                    id=image_id,
                    path=row["path"],
                    final_score=float(final),
                    clip_sim=v["clip_sim"],
                    phash_sim=v["phash_sim"],
                    orb_score=orb_score,
                    width=row["width"] or 0,
                    height=row["height"] or 0,
                )
            )
            if progress_cb and (i % 10 == 0 or i == total - 1):
                progress_cb(i + 1, total, Path(row["path"]).name)

        results.sort(key=lambda r: r.final_score, reverse=True)
        logger.info("Search selesai dalam %.2fs, %d kandidat di-rerank.", time.time() - t0, len(pool))
        return results[:top_n]
