"""Perceptual hashing (pHash/dHash) untuk deteksi near-duplicate.

Perceptual hash menangkap struktur low-frequency dari sebuah gambar sehingga
tahan terhadap resize, kompresi ulang, dan perubahan format -- tetapi TIDAK
tahan terhadap crop besar atau rotasi. Untuk itu perceptual hash dipakai
sebagai salah satu sinyal candidate-generation & scoring, dikombinasikan
dengan CLIP embedding (semantic) dan ORB feature matching (tahan crop) saat
reranking. Lihat README bagian "Bagaimana sistem menangani crop, screenshot,
resize, dan compression".
"""
from __future__ import annotations

import numpy as np
from PIL import Image
import imagehash

from . import config


def compute_hashes(img: Image.Image) -> tuple[str, str]:
    """Hitung pHash dan dHash dari gambar PIL yang sudah dibuka.

    Dikembalikan sebagai hex string agar mudah disimpan di SQLite.
    """
    phash = imagehash.phash(img, hash_size=config.PHASH_SIZE)
    dhash = imagehash.dhash(img, hash_size=config.DHASH_SIZE)
    return str(phash), str(dhash)


def hex_to_bytes(hexstr: str) -> np.ndarray:
    """Konversi hex string hash menjadi array uint8 byte-packed untuk Hamming distance cepat."""
    return np.frombuffer(bytes.fromhex(hexstr), dtype=np.uint8)


def hex_to_bits_len(hexstr: str) -> int:
    return len(hexstr) * 4  # setiap hex char = 4 bit
