"""Wrapper FAISS untuk approximate nearest neighbor search pada embedding CLIP.

Kenapa HNSW?
- Untuk ~200.000 vector berdimensi 512, HNSW (Hierarchical Navigable Small
  World) memberi kombinasi terbaik antara kecepatan query (sub-linear,
  jauh lebih cepat dari brute-force di skala ini) dan recall tinggi, tanpa
  perlu proses "training" seperti IVF/PQ (yang butuh data representatif
  sebelum index bisa dipakai). Ukuran index untuk 200k x 512 float32 masih
  sangat wajar (~400 MB), jadi kompresi PQ tidak diperlukan.
- Vector di-index dengan metric INNER_PRODUCT; karena semua embedding sudah
  di-L2-normalize saat diekstrak, inner product == cosine similarity.
- IndexIDMap2 dipakai agar id FAISS = id baris SQLite secara langsung
  (tidak perlu tabel mapping index-row -> path terpisah).
"""
from __future__ import annotations

import logging
from pathlib import Path

import faiss
import numpy as np

from . import config

logger = logging.getLogger(__name__)


class VectorIndex:
    def __init__(self, dim: int = config.EMBEDDING_DIM):
        self.dim = dim
        base = faiss.IndexHNSWFlat(dim, config.HNSW_M, faiss.METRIC_INNER_PRODUCT)
        base.hnsw.efConstruction = config.HNSW_EF_CONSTRUCTION
        base.hnsw.efSearch = config.HNSW_EF_SEARCH
        self.index = faiss.IndexIDMap2(base)

    @property
    def ntotal(self) -> int:
        return self.index.ntotal

    def add(self, ids: np.ndarray, vectors: np.ndarray) -> None:
        assert vectors.dtype == np.float32
        assert vectors.shape[1] == self.dim
        self.index.add_with_ids(vectors, ids.astype(np.int64))

    def search(self, query_vector: np.ndarray, k: int) -> tuple[np.ndarray, np.ndarray]:
        """Kembalikan (ids, similarities) top-k, similarities dalam [-1, 1] (cosine)."""
        q = query_vector.reshape(1, -1).astype(np.float32)
        k = min(k, max(self.index.ntotal, 1))
        sims, ids = self.index.search(q, k)
        sims, ids = sims[0], ids[0]
        mask = ids != -1
        return ids[mask], sims[mask]

    def reconstruct(self, image_id: int) -> np.ndarray | None:
        """Ambil kembali vector embedding yang tersimpan untuk satu id, tanpa re-embedding.

        Dipakai saat reranking untuk kandidat yang masuk pool lewat jalur
        perceptual-hash (bukan lewat CLIP ANN top-K), supaya tetap dapat
        clip_sim yang eksak tanpa membuka & memproses ulang gambarnya.
        """
        try:
            return np.array(self.index.reconstruct(int(image_id)), dtype=np.float32)
        except RuntimeError:
            return None

    def save(self, path: str | Path) -> None:
        faiss.write_index(self.index, str(path))

    @classmethod
    def load(cls, path: str | Path, dim: int = config.EMBEDDING_DIM) -> "VectorIndex":
        obj = cls.__new__(cls)
        obj.dim = dim
        obj.index = faiss.read_index(str(path))
        return obj

    @classmethod
    def load_or_create(cls, path: str | Path, dim: int = config.EMBEDDING_DIM) -> "VectorIndex":
        path = Path(path)
        if path.exists():
            logger.info("Loading existing FAISS index from %s", path)
            return cls.load(path, dim)
        logger.info("Creating new FAISS index (dim=%d)", dim)
        return cls(dim)
