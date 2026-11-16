"""Unduh SEMUA bobot model ke folder `models/` project (sekali saja, butuh internet).

Setelah ini aplikasi berjalan 100% OFFLINE dan model ikut dibundel saat build EXE.

    python scripts\\download_model.py            # semua model
    python scripts\\download_model.py --no-small # lewati Whisper small (hemat ~480 MB)

Model yang diunduh:
  models/hf_home/   CLIP ViT-B-32 (openai)          - pencarian foto mirip   (~580 MB)
  models/whisper/   faster-whisper base & small     - transkrip suara        (~145 + ~480 MB)
  models/easyocr/   CRAFT + latin_g2 + english_g2   - OCR teks foto/video    (~115 MB)

Model TIDAK disimpan di GitHub (ukurannya melebihi batas 100 MB per file).
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
MODELS = PROJECT_ROOT / "models"


def clip() -> None:
    target = MODELS / "hf_home"
    target.mkdir(parents=True, exist_ok=True)
    os.environ["HF_HOME"] = str(target)
    os.environ.pop("HF_HUB_OFFLINE", None)
    sys.path.insert(0, str(PROJECT_ROOT))
    from app import config  # noqa: E402
    import open_clip  # noqa: E402

    print(f"[1/3] CLIP {config.CLIP_MODEL_NAME} ({config.CLIP_PRETRAINED}) -> {target}")
    open_clip.create_model_and_transforms(config.CLIP_MODEL_NAME, pretrained=config.CLIP_PRETRAINED)


def whisper(sizes: list[str]) -> None:
    from huggingface_hub import snapshot_download

    target = MODELS / "whisper"
    target.mkdir(parents=True, exist_ok=True)
    for s in sizes:
        print(f"[2/3] Whisper '{s}' -> {target}")
        snapshot_download(f"Systran/faster-whisper-{s}", cache_dir=str(target))


def easyocr_models() -> None:
    import easyocr

    target = MODELS / "easyocr"
    target.mkdir(parents=True, exist_ok=True)
    print(f"[3/3] EasyOCR (deteksi CRAFT + latin/Indonesia + Inggris) -> {target}")
    for langs in (["id", "en"], ["en"]):
        easyocr.Reader(langs, gpu=False, model_storage_directory=str(target),
                       user_network_directory=str(target / "user"), download_enabled=True, verbose=False)


def main() -> None:
    sizes = ["base"] if "--no-small" in sys.argv else ["base", "small"]
    clip()
    whisper(sizes)
    easyocr_models()
    print("\nSELESAI. Semua model tersimpan di folder models/ - aplikasi siap dipakai offline.")


if __name__ == "__main__":
    main()
