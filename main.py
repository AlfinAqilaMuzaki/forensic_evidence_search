"""Entry point aplikasi Photo Similarity Search.

Jalankan GUI:      python main.py
Diagnostik cepat:  python main.py --selftest
                    (memverifikasi model CLIP bisa dimuat -- termasuk dari
                    bundel offline pada build EXE -- tanpa perlu membuka GUI)
"""
import sys


def run_selftest() -> int:
    print("=== Self-test: memuat model CLIP ===")
    try:
        from app.embedding import ClipEmbedder
        import os

        embedder = ClipEmbedder()
        print(f"OK - model dimuat, device={embedder.device}")
        print(f"HF_HOME  = {os.environ.get('HF_HOME', '(default)')}")
        print(f"HF_HUB_OFFLINE = {os.environ.get('HF_HUB_OFFLINE', '(tidak diset)')}")

        from PIL import Image

        dummy = Image.new("RGB", (64, 64), color=(120, 200, 80))
        vec = embedder.embed_single(dummy)
        print(f"OK - embedding dummy image berhasil, shape={vec.shape}")
        print("SELFTEST PASSED")
        return 0
    except Exception as exc:  # noqa: BLE001
        import traceback

        traceback.print_exc()
        print(f"SELFTEST FAILED: {exc}")
        return 1


if __name__ == "__main__":
    if "--selftest" in sys.argv:
        sys.exit(run_selftest())
    from app.gui import main

    main()
