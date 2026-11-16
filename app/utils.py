"""Fungsi bantu umum: scanning file, pembukaan gambar yang aman, popcount, dsb."""
from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Iterator

import numpy as np
from PIL import Image, ImageFile, UnidentifiedImageError

from . import config

# Beberapa file hasil ekstraksi forensik kadang terpotong/tidak lengkap.
# Izinkan PIL memuat gambar yang truncated alih-alih langsung error keras,
# tetap akan tertangkap oleh try/except di safe_open_image.
ImageFile.LOAD_TRUNCATED_IMAGES = True


@dataclass
class FileRecord:
    path: str
    size: int
    mtime: float


def iter_image_files(root: str | Path) -> Iterator[FileRecord]:
    """Scan rekursif folder dataset, hanya mengembalikan file gambar didukung.

    Tidak membaca isi file di sini (hanya metadata filesystem murah: size &
    mtime) supaya scanning 200.000 file tetap cepat.
    """
    root = Path(root)
    for dirpath, _dirnames, filenames in os.walk(root):
        for name in filenames:
            ext = Path(name).suffix.lower()
            if ext not in config.SUPPORTED_EXTENSIONS:
                continue
            full = Path(dirpath) / name
            try:
                st = full.stat()
            except OSError:
                continue
            yield FileRecord(path=str(full), size=st.st_size, mtime=st.st_mtime)


def safe_open_image(path: str) -> Image.Image | None:
    """Buka gambar dan pastikan datanya valid & bisa didekode penuh.

    Mengembalikan None (bukan raise) untuk file corrupt/tidak didukung,
    supaya proses indexing 200.000 file tidak berhenti karena satu file rusak.
    """
    try:
        img = Image.open(path)
        img.load()  # paksa decode penuh, bukan cuma header
        if img.mode not in ("RGB", "L"):
            img = img.convert("RGB")
        elif img.mode == "L":
            img = img.convert("RGB")
        return img
    except (UnidentifiedImageError, OSError, ValueError, Image.DecompressionBombError) as exc:
        return None


# --- popcount cepat untuk Hamming distance perceptual hash --------------------
_POPCOUNT_TABLE = np.array([bin(i).count("1") for i in range(256)], dtype=np.uint8)


def hamming_distance_batch(query_bits: np.ndarray, db_bits: np.ndarray) -> np.ndarray:
    """Hamming distance antara satu hash query dan array hash database.

    Hash direpresentasikan sebagai array uint8 (byte-packed), shape (n_bytes,)
    untuk query dan (N, n_bytes) untuk database. Vektor-isasi penuh via numpy,
    cukup cepat untuk N=200.000 (<1 detik).
    """
    xor = np.bitwise_xor(db_bits, query_bits[None, :])
    return _POPCOUNT_TABLE[xor].sum(axis=1)


def open_file_location(path: str) -> None:
    """Buka Windows Explorer dan pilih file tersebut."""
    import subprocess

    norm = str(Path(path).resolve())
    subprocess.run(["explorer", "/select,", norm])


def open_file_default(path: str) -> None:
    """Buka file dengan aplikasi default OS (tidak mengubah file)."""
    os.startfile(path)  # type: ignore[attr-defined]  # Windows only
