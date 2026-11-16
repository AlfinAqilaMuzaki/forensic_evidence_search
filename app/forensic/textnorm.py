"""Normalisasi teks untuk pencarian (huruf kecil, tanpa aksen/tanda baca)
dengan peta offset kembali ke teks asli (untuk highlight cuplikan)."""
from __future__ import annotations

import unicodedata


def _fold_char(ch: str) -> str:
    if ch.isalnum():
        base = unicodedata.normalize("NFKD", ch)
        base = "".join(c for c in base if not unicodedata.combining(c)) or ch
        return base.lower()
    return " "


def normalize_with_map(text: str) -> tuple[str, list[int]]:
    """Kembalikan (teks_normal, peta) di mana peta[i] = indeks karakter asli
    untuk karakter ke-i teks normal. Spasi berurutan dipadatkan jadi satu."""
    out: list[str] = []
    mapping: list[int] = []
    prev_space = True
    for i, ch in enumerate(text):
        folded = _fold_char(ch)
        for f in folded:
            if f == " ":
                if prev_space:
                    continue
                prev_space = True
            else:
                prev_space = False
            out.append(f)
            mapping.append(i)
    if out and out[-1] == " ":
        out.pop()
        mapping.pop()
    return "".join(out), mapping


def normalize(text: str) -> str:
    return normalize_with_map(text)[0]
