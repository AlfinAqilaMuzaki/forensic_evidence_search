"""
Konfigurasi terpusat untuk Photo Similarity Search.

Semua nilai di sini boleh diubah tanpa menyentuh logika inti di modul lain.
"""
from __future__ import annotations

import hashlib
import os
import sys
from pathlib import Path

# ---------------------------------------------------------------------------
# Bobot model CLIP di-bundle offline (lihat scripts/download_model.py dan
# build_exe.bat) supaya aplikasi hasil build EXE bisa jalan tanpa Python dan
# tanpa koneksi internet di komputer pengguna akhir. Kalau folder bundel ini
# ada, dipakai sebagai HF cache utama & mode offline dipaksa aktif. Kalau
# tidak ada (mis. dijalankan langsung dari source tanpa pernah men-download
# model), open_clip akan jatuh ke perilaku default (unduh sekali lalu cache
# di ~/.cache/huggingface seperti biasa).
# ---------------------------------------------------------------------------
def _configure_bundled_model_cache() -> None:
    if getattr(sys, "frozen", False):
        base = Path(sys._MEIPASS)  # type: ignore[attr-defined]
    else:
        base = Path(__file__).resolve().parent.parent
    bundled = base / "models" / "hf_home"
    if bundled.exists():
        os.environ.setdefault("HF_HOME", str(bundled))
        os.environ.setdefault("HF_HUB_OFFLINE", "1")


_configure_bundled_model_cache()

# ---------------------------------------------------------------------------
# Lokasi penyimpanan index.
#
# PENTING: index TIDAK PERNAH disimpan di dalam folder dataset (folder hasil
# ekstraksi/bukti). Ini menjaga agar folder sumber tidak pernah ditulis oleh
# aplikasi ini (integritas barang bukti). Index disimpan di app-data lokal,
# dikelompokkan per folder dataset (berdasarkan hash path dataset).
# ---------------------------------------------------------------------------
THUMB_DIRNAME = "thumbnails"
DB_FILENAME = "catalog.db"
FAISS_FILENAME = "vectors.hnsw"
LOG_FILENAME = "index.log"


def index_dir_for_dataset(dataset_path: str | Path) -> Path:
    """Index visual disimpan di workspace otomatis milik folder bukti
    (DATA_ANALISIS/<nama>_<hash>/index_visual), bukan di folder bukti."""
    from .workspace import workspace_for

    return workspace_for(dataset_path) / "index_visual"


# ---------------------------------------------------------------------------
# Format gambar yang didukung
# ---------------------------------------------------------------------------
SUPPORTED_EXTENSIONS = {
    ".jpg", ".jpeg", ".png", ".webp", ".bmp", ".gif", ".tif", ".tiff", ".heic", ".heif",
}

# ---------------------------------------------------------------------------
# Model embedding visual (CLIP via open_clip)
#
# ViT-B-32 dipilih sebagai default karena rasio kecepatan/akurasi paling baik
# untuk dataset besar (~200.000 gambar) yang berjalan di CPU. Bisa diganti ke
# model yang lebih besar (mis. "ViT-L-14") bila tersedia GPU dan akurasi
# semantik lebih diprioritaskan daripada kecepatan indexing.
# ---------------------------------------------------------------------------
CLIP_MODEL_NAME = "ViT-B-32"
CLIP_PRETRAINED = "openai"
EMBEDDING_DIM = 512
EMBED_BATCH_SIZE = 64
# 0 = load di main process (paling aman di Windows, tidak butuh objek
# picklable). Naikkan (mis. 2-4) di Linux/Mac untuk mempercepat I/O jika
# semua fungsi preprocessing terbukti picklable di environment Anda.
EMBED_NUM_WORKERS = 0

# ---------------------------------------------------------------------------
# Perceptual hash
# ---------------------------------------------------------------------------
PHASH_SIZE = 16          # -> hash 256-bit, lebih diskriminatif dari default 64-bit
DHASH_SIZE = 16

# ---------------------------------------------------------------------------
# FAISS / ANN
# ---------------------------------------------------------------------------
HNSW_M = 32
HNSW_EF_CONSTRUCTION = 200
HNSW_EF_SEARCH = 128

# ---------------------------------------------------------------------------
# Pencarian & reranking
# ---------------------------------------------------------------------------
CLIP_CANDIDATE_K = 300          # kandidat awal dari CLIP ANN search
HASH_CANDIDATE_K = 300          # kandidat awal dari perceptual-hash search
RERANK_POOL_SIZE = 400          # jumlah kandidat gabungan yang di-rerank dengan ORB
ORB_MAX_FEATURES = 500
ORB_GOOD_MATCH_RATIO = 0.75     # Lowe's ratio test
ORB_INLIER_NORMALIZER = 40.0    # dipakai untuk menormalkan jumlah inlier -> [0,1]

# Bobot skor gabungan akhir (harus valid walau salah satu sinyal tidak ada)
WEIGHT_CLIP = 0.5
WEIGHT_PHASH = 0.2
WEIGHT_ORB = 0.3

# Thumbnail untuk grid hasil pencarian di GUI
THUMB_SIZE = (220, 220)

# Commit ke SQLite setiap N gambar saat indexing (trade-off durability vs speed)
DB_COMMIT_EVERY = 200
