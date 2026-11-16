"""Validasi end-to-end: pastikan pencarian benar-benar berbasis KONTEN VISUAL,
bukan nama file/metadata.

Cara pakai:
    python tests/validate.py

Langkah:
1. Membuat dataset sintetis kecil (lihat make_test_dataset.py) berisi:
   - satu gambar referensi asli + 8 varian (rename, resize, compress, crop,
     screenshot, watermark, brightness, format beda),
   - satu gambar "scene mirip tapi beda gambar" (kontrol negatif lemah),
   - N gambar distractor acak (kontrol negatif kuat),
   - satu file corrupt (uji robustness).
2. Build index penuh atas dataset tsb.
3. Search menggunakan reference_original.png sebagai query.
4. Cek: semua varian reference_* muncul di hasil dan skornya lebih tinggi
   daripada seluruh distractor. Laporkan PASS/FAIL per kasus.
"""
from __future__ import annotations

import shutil
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from tests.make_test_dataset import build as build_test_dataset  # noqa: E402
from app.indexer import Indexer  # noqa: E402
from app.search import SearchEngine  # noqa: E402

DATASET_DIR = PROJECT_ROOT / "tests" / "_dataset"
INDEX_DIR = PROJECT_ROOT / "tests" / "_index"

EXPECTED_VARIANTS = [
    "reference_renamed_copy.jpg",
    "reference_resized.jpg",
    "reference_recompressed.jpg",
    "reference_cropped.jpg",
    "reference_screenshot.png",
    "reference_watermarked.jpg",
    "reference_brightness.jpg",
    "reference_webp.webp",
]


def main() -> int:
    print("=== 1. Menyiapkan dataset uji sintetis ===")
    if DATASET_DIR.exists():
        shutil.rmtree(DATASET_DIR)
    if INDEX_DIR.exists():
        shutil.rmtree(INDEX_DIR)
    build_test_dataset(str(DATASET_DIR), n_distractors=40)

    print("\n=== 2. Building index ===")
    indexer = Indexer(str(DATASET_DIR), str(INDEX_DIR))
    stats = indexer.build(incremental=False, log_cb=print)
    print(
        f"Index selesai: ditemukan={stats.total_found} ok={stats.processed_ok} "
        f"error={stats.processed_error} waktu={stats.elapsed_sec:.1f}s"
    )
    if stats.processed_error < 1:
        print("[WARN] File corrupt seharusnya tercatat error tapi tidak terdeteksi.")

    print("\n=== 3. Searching dengan reference_original.png sebagai query ===")
    engine = SearchEngine(str(INDEX_DIR))
    query_path = str(DATASET_DIR / "reference_original.png")
    results = engine.search(query_path, top_n=60, use_rerank=True)
    engine.close()

    by_name = {Path(r.path).name: r for r in results}

    print(f"\n{'rank':<5}{'file':<40}{'final':<8}{'clip':<8}{'phash':<8}{'orb':<8}")
    for i, r in enumerate(results[:20], start=1):
        orb_str = f"{r.orb_score:.3f}" if r.orb_score is not None else "-"
        print(f"{i:<5}{Path(r.path).name:<40}{r.final_score:<8.3f}{r.clip_sim:<8.3f}{r.phash_sim:<8.3f}{orb_str:<8}")

    print("\n=== 4. Hasil validasi ===")
    all_pass = True
    distractor_scores = [r.final_score for r in results if Path(r.path).parent.name == "distractors"]
    min_distractor = min(distractor_scores) if distractor_scores else 0.0
    max_distractor = max(distractor_scores) if distractor_scores else 0.0

    for name in EXPECTED_VARIANTS:
        r = by_name.get(name)
        if r is None:
            print(f"[FAIL] {name}: TIDAK ditemukan dalam top-60 hasil pencarian.")
            all_pass = False
            continue
        ok_vs_distractor = (not distractor_scores) or (r.final_score > max_distractor)
        status = "PASS" if ok_vs_distractor else "FAIL"
        if status == "FAIL":
            all_pass = False
        print(
            f"[{status}] {name}: score={r.final_score:.3f} "
            f"(distractor tertinggi={max_distractor:.3f})"
        )

    scene_similar = by_name.get("scene_similar_but_different.jpg")
    if scene_similar:
        print(
            f"[INFO] scene_similar_but_different.jpg (kontrol, BUKAN gambar sama): "
            f"score={scene_similar.final_score:.3f} -- boleh muncul, tapi semestinya "
            f"di bawah varian near-duplicate asli."
        )

    print(f"\n=== Ringkasan distractor: min={min_distractor:.3f} max={max_distractor:.3f} "
          f"(n={len(distractor_scores)} dari {len(results)} hasil) ===")

    print("\n" + ("SEMUA VALIDASI LULUS" if all_pass else "ADA VALIDASI YANG GAGAL — lihat detail di atas."))
    return 0 if all_pass else 1


if __name__ == "__main__":
    raise SystemExit(main())
