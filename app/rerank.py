"""Reranking kandidat dengan local feature matching (ORB + RANSAC homography).

CLIP embedding dan perceptual hash bagus untuk candidate generation cepat,
tapi keduanya bisa kecolongan pada kasus CROP signifikan (bagian gambar yang
dipotong cukup besar) karena representasi global gambar berubah banyak.

ORB (Oriented FAST and Rotated BRIEF) mencari titik-titik fitur lokal yang
tahan terhadap crop, rotasi, dan perubahan skala. Dengan mencocokkan fitur
lokal antara foto referensi dan kandidat, lalu memverifikasi kecocokan itu
dengan homography RANSAC, kita bisa mengonfirmasi "apakah sebagian struktur
visual kandidat ini memang berasal dari gambar yang sama", bukan sekadar
"temanya mirip". Ini dipakai HANYA pada kandidat teratas (bukan semua
200.000 gambar) karena biayanya jauh lebih mahal daripada ANN search.
"""
from __future__ import annotations

import cv2
import numpy as np

from . import config


def _to_gray_cv(path: str, max_dim: int = 800) -> np.ndarray | None:
    from .utils import safe_open_image

    img = safe_open_image(path)
    if img is None:
        return None
    try:
        img.thumbnail((max_dim, max_dim))
        arr = np.array(img.convert("L"))
        return arr
    finally:
        img.close()


def orb_match_score(query_gray: np.ndarray, candidate_path: str) -> float:
    """Skor kemiripan struktural [0, 1] antara query dan satu kandidat.

    0 berarti tidak ada bukti kecocokan struktural (bisa saja tetap mirip
    secara semantik menurut CLIP, tapi ORB tidak menemukan cukup fitur lokal
    yang cocok -- umum terjadi pada gambar low-detail/flat).
    """
    cand_gray = _to_gray_cv(candidate_path)
    if cand_gray is None:
        return 0.0

    orb = cv2.ORB_create(nfeatures=config.ORB_MAX_FEATURES)
    kp1, des1 = orb.detectAndCompute(query_gray, None)
    kp2, des2 = orb.detectAndCompute(cand_gray, None)
    if des1 is None or des2 is None or len(kp1) < 4 or len(kp2) < 4:
        return 0.0

    bf = cv2.BFMatcher(cv2.NORM_HAMMING)
    try:
        matches = bf.knnMatch(des1, des2, k=2)
    except cv2.error:
        return 0.0

    good = [m for pair in matches if len(pair) == 2 for m, n in [pair] if m.distance < config.ORB_GOOD_MATCH_RATIO * n.distance]
    if len(good) < 4:
        return 0.0

    src_pts = np.float32([kp1[m.queryIdx].pt for m in good]).reshape(-1, 1, 2)
    dst_pts = np.float32([kp2[m.trainIdx].pt for m in good]).reshape(-1, 1, 2)
    homography, mask = cv2.findHomography(src_pts, dst_pts, cv2.RANSAC, 5.0)
    if mask is None:
        return 0.0

    inliers = int(mask.sum())
    score = min(1.0, inliers / config.ORB_INLIER_NORMALIZER)
    return float(score)


def load_query_gray(query_path: str) -> np.ndarray | None:
    return _to_gray_cv(query_path)
