"""Entry point Cyber Forensic Evidence Search.

Jalankan GUI:      python main.py   (atau ForensicEvidenceSearch.exe)
Diagnostik:        python main.py --selftest
                   Memeriksa semua mesin (CLIP, EasyOCR, Whisper, FFmpeg, PDF,
                   folder data) tanpa membuka GUI. Hasil juga ditulis ke
                   selftest_log.txt di folder data (DATA_ANALISIS).
"""
import os
import sys

# Pada EXE mode jendela (tanpa konsol) sys.stdout/stderr = None; library yang
# menulis progress (tqdm, huggingface, easyocr) akan crash tanpa pengaman ini.
if sys.stdout is None:
    sys.stdout = open(os.devnull, "w", encoding="utf-8")
if sys.stderr is None:
    sys.stderr = open(os.devnull, "w", encoding="utf-8")


def _install_error_handler() -> None:
    """Tanpa jendela konsol (EXE / pythonw), error tak terduga tidak boleh hilang diam-diam:
    dicatat ke DATA_ANALISIS/app_error.log dan ditampilkan sebagai pesan."""
    import time
    import traceback

    def hook(exc_type, exc, tb):
        text = "".join(traceback.format_exception(exc_type, exc, tb))
        log_path = None
        try:
            from app.workspace import DATA_ROOT

            DATA_ROOT.mkdir(parents=True, exist_ok=True)
            log_path = DATA_ROOT / "app_error.log"
            with open(log_path, "a", encoding="utf-8") as fh:
                fh.write(f"\n=== {time.strftime('%Y-%m-%d %H:%M:%S')} ===\n{text}")
        except Exception:  # noqa: BLE001
            pass
        try:
            from PySide6.QtWidgets import QApplication, QMessageBox

            if QApplication.instance() is not None:
                QMessageBox.critical(None, "Terjadi kesalahan",
                                     f"{exc_type.__name__}: {exc}\n\nDetail dicatat di:\n{log_path or '-'}")
        except Exception:  # noqa: BLE001
            pass
    sys.excepthook = hook


def run_selftest() -> int:
    import time
    import traceback

    lines: list[str] = []

    def out(msg: str) -> None:
        lines.append(msg)
        try:
            print(msg, flush=True)
        except Exception:  # noqa: BLE001
            pass

    ok_all = True

    def check(name, fn):
        nonlocal ok_all
        t0 = time.time()
        try:
            detail = fn()
            out(f"[OK]    {name} ({time.time() - t0:.1f}s) {detail or ''}")
        except Exception as exc:  # noqa: BLE001
            ok_all = False
            out(f"[GAGAL] {name}: {type(exc).__name__}: {exc}")
            out(traceback.format_exc())

    from app.forensic import AUTHOR, TOOL_NAME, TOOL_VERSION
    from app.forensic import fconfig
    from app.workspace import DATA_ROOT

    out(f"=== SELFTEST {TOOL_NAME} v{TOOL_VERSION} (oleh {AUTHOR}) ===")
    out(f"frozen={getattr(sys, 'frozen', False)}  base={fconfig.BASE_DIR}  app={fconfig.APP_DIR}")
    out(f"data={DATA_ROOT}")

    def clip():
        from PIL import Image

        from app.embedding import ClipEmbedder

        e = ClipEmbedder()
        v = e.embed_single(Image.new("RGB", (64, 64), (120, 200, 80)))
        return f"device={e.device} dim={v.shape}"

    def ocr():
        import numpy as np
        from PIL import Image, ImageDraw, ImageFont

        from app.forensic.extractors import Engines

        im = Image.new("RGB", (900, 160), "white")
        try:
            f = ImageFont.truetype("C:/Windows/Fonts/arial.ttf", 56)
        except OSError:
            f = ImageFont.load_default()
        ImageDraw.Draw(im).text((20, 40), "tolong lakukan itu", font=f, fill="black")
        text, conf = Engines().ocr_array(np.array(im))
        if "tolong" not in text.lower():
            raise RuntimeError(f"hasil OCR tidak sesuai: {text!r}")
        return f"teks={text!r} conf={conf:.2f}"

    def whisper():
        import numpy as np

        from app.forensic.extractors import Engines

        eng = Engines(whisper_model="base")
        model = eng.asr_model()
        segs, info = model.transcribe(np.zeros(16000, dtype=np.float32), language="id", vad_filter=True)
        list(segs)
        return f"model=base bahasa={info.language}"

    def tools():
        found = {t: fconfig.find_tool(t) for t in ("ffmpeg", "ffprobe", "ffplay")}
        missing = [t for t, p in found.items() if not p]
        if missing:
            raise RuntimeError(f"tidak ditemukan: {missing}")
        return " ".join(f"{t}={p}" for t, p in found.items())

    def pdf_browser():
        from app.forensic.report import _find_browser

        b = _find_browser()
        if not b:
            raise RuntimeError("Edge/Chrome tidak ditemukan (laporan PDF dilewati, HTML tetap ada)")
        return b

    def data_dir():
        p = DATA_ROOT / ".selftest"
        p.write_text("ok", encoding="utf-8")
        p.unlink()
        return str(DATA_ROOT)

    check("Folder data bisa ditulis", data_dir)
    check("FFmpeg / FFprobe / FFplay", tools)
    check("Browser untuk laporan PDF", pdf_browser)
    check("Model CLIP (foto mirip)", clip)
    check("Model EasyOCR (OCR)", ocr)
    check("Model Whisper (transkrip)", whisper)
    out("SELFTEST PASSED" if ok_all else "SELFTEST FAILED")
    try:
        (DATA_ROOT / "selftest_log.txt").write_text("\n".join(lines), encoding="utf-8")
    except OSError:
        pass
    return 0 if ok_all else 1


if __name__ == "__main__":
    if "--selftest" in sys.argv:
        sys.exit(run_selftest())
    _install_error_handler()
    from app.gui import main

    main()
