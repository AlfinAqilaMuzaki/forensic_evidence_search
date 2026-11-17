"""Ekstraksi teks dari dokumen, foto (OCR), audio (transkripsi) dan video
(transkripsi suara + OCR frame).

Semua file bukti dibuka READ-ONLY. Tidak ada yang ditulis ke folder bukti;
file sementara (frame video) dibuat di folder `_tmp` milik kasus lalu dihapus.
Setiap fungsi mengembalikan list segmen:
    {source, text, t_start, t_end, page, label, conf, frame_path}
"""
from __future__ import annotations

import email
import email.policy
import hashlib
import html
import json
import logging
import os
import re
import shutil
import subprocess
import tempfile
import zipfile
from pathlib import Path
from typing import Callable, Optional

import numpy as np

from . import fconfig

logger = logging.getLogger(__name__)

StopCheck = Callable[[], bool]
SubProgress = Callable[[str], None]

_NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)


class StopRequested(Exception):
    pass


# ---------------------------------------------------------------------------
# Hash & deteksi tipe
# ---------------------------------------------------------------------------
def hash_file(path: str, should_stop: Optional[StopCheck] = None) -> tuple[str, str]:
    sha = hashlib.sha256()
    md5 = hashlib.md5()
    with open(path, "rb") as fh:
        while True:
            block = fh.read(fconfig.HASH_BLOCK)
            if not block:
                break
            sha.update(block)
            md5.update(block)
            if should_stop and should_stop():
                raise StopRequested()
    return sha.hexdigest(), md5.hexdigest()


def kind_from_ext(ext: str) -> Optional[str]:
    if ext in fconfig.IMAGE_EXT:
        return "image"
    if ext in fconfig.AUDIO_EXT:
        return "audio"
    if ext in fconfig.VIDEO_EXT:
        return "video"
    if ext in fconfig.DOC_EXT:
        return "document"
    if ext in fconfig.DB_EXT or ext in fconfig.ENCRYPTED_DB_EXT:
        return "database"
    return None


def sniff_kind(path: str) -> tuple[Optional[str], Optional[str]]:
    """Deteksi tipe dari signature (magic bytes), tanpa melihat ekstensi.
    Mengembalikan (kind, ekstensi_sebenarnya)."""
    try:
        with open(path, "rb") as fh:
            h = fh.read(64)
    except OSError:
        return None, None
    if h.startswith(b"\xff\xd8\xff"):
        return "image", ".jpg"
    if h.startswith(b"\x89PNG"):
        return "image", ".png"
    if h[:6] in (b"GIF87a", b"GIF89a"):
        return "image", ".gif"
    if h.startswith(b"BM"):
        return "image", ".bmp"
    if h[:4] in (b"II*\x00", b"MM\x00*"):
        return "image", ".tif"
    if h.startswith(b"RIFF") and h[8:12] == b"WEBP":
        return "image", ".webp"
    if h.startswith(b"SQLite format 3\x00"):
        return "database", ".db"
    if h.startswith(b"%PDF"):
        return "document", ".pdf"
    if h.startswith(b"PK\x03\x04"):
        try:
            with zipfile.ZipFile(path) as z:
                names = set(z.namelist())
            if "word/document.xml" in names:
                return "document", ".docx"
            if "ppt/presentation.xml" in names:
                return "document", ".pptx"
            if "xl/workbook.xml" in names:
                return "document", ".xlsx"
            if "content.xml" in names:
                return "document", ".odt"
        except Exception:  # noqa: BLE001
            pass
        return None, ".zip"
    if h.startswith(b"\xd0\xcf\x11\xe0"):
        return "document", ".doc"
    if h.startswith(b"{\\rtf"):
        return "document", ".rtf"
    if h.startswith(b"RIFF") and h[8:12] == b"WAVE":
        return "audio", ".wav"
    if h.startswith(b"RIFF") and h[8:12] == b"AVI ":
        return "video", ".avi"
    if h.startswith(b"ID3") or h[:2] in (b"\xff\xfb", b"\xff\xf3", b"\xff\xf2"):
        return "audio", ".mp3"
    if h.startswith(b"OggS"):
        return "audio", ".ogg"
    if h.startswith(b"fLaC"):
        return "audio", ".flac"
    if h.startswith(b"#!AMR"):
        return "audio", ".amr"
    if h[4:8] == b"ftyp":
        brand = h[8:12]
        if brand.startswith(b"M4A") or brand.startswith(b"M4B"):
            return "audio", ".m4a"
        if brand.startswith(b"3g"):
            return "video", ".3gp"
        if brand.startswith(b"qt"):
            return "video", ".mov"
        return "video", ".mp4"
    if h.startswith(b"\x1a\x45\xdf\xa3"):
        return "video", ".mkv"
    if h.startswith(b"\x30\x26\xb2\x75"):
        return "video", ".wmv"
    return None, None


# ---------------------------------------------------------------------------
# Util teks
# ---------------------------------------------------------------------------
def chunk_text(text: str, size: int = fconfig.TEXT_CHUNK, overlap: int = fconfig.TEXT_OVERLAP) -> list[str]:
    text = text.strip()
    if len(text) <= size:
        return [text] if text else []
    out = []
    start = 0
    while start < len(text):
        end = min(len(text), start + size)
        if end < len(text):
            sp = text.rfind(" ", start + size // 2, end)
            if sp > 0:
                end = sp
        out.append(text[start:end].strip())
        if end >= len(text):
            break
        start = max(end - overlap, start + 1)
    return [c for c in out if c]


def read_text_file(path: str) -> str:
    with open(path, "rb") as fh:
        raw = fh.read()
    if raw.startswith(b"\xef\xbb\xbf"):
        return raw[3:].decode("utf-8", errors="replace")
    if raw.startswith(b"\xff\xfe") or raw.startswith(b"\xfe\xff"):
        return raw.decode("utf-16", errors="replace")
    # tebakan UTF-16 tanpa BOM (banyak byte nol)
    if len(raw) > 4 and raw[1:200:2].count(0) > 50:
        return raw.decode("utf-16-le", errors="replace")
    try:
        return raw.decode("utf-8")
    except UnicodeDecodeError:
        return raw.decode("cp1252", errors="replace")


_TAG_RE = re.compile(r"<[^>]+>")
_SCRIPT_RE = re.compile(r"<(script|style)[^>]*>.*?</\1>", re.S | re.I)


def strip_markup(s: str) -> str:
    s = _SCRIPT_RE.sub(" ", s)
    s = re.sub(r"<br\s*/?>|</p>|</div>|</tr>|</text:p>", "\n", s, flags=re.I)
    s = _TAG_RE.sub(" ", s)
    s = html.unescape(s)
    return re.sub(r"[ \t\r\f\v]+", " ", s)


def strip_rtf(s: str) -> str:
    s = re.sub(r"\\'([0-9a-fA-F]{2})", lambda m: bytes.fromhex(m.group(1)).decode("cp1252", "replace"), s)
    s = re.sub(r"\\u(-?\d+)\??", lambda m: chr(int(m.group(1)) % 65536), s)
    s = re.sub(r"\\par[d]?\b", "\n", s)
    s = re.sub(r"\{\\\*[^{}]*\}", " ", s)
    s = re.sub(r"\\[a-zA-Z]+-?\d* ?", " ", s)
    s = s.replace("{", " ").replace("}", " ")
    return re.sub(r"[ \t]+", " ", s)


def binary_strings(path: str, min_len: int = 5) -> str:
    """Ambil string terbaca dari file biner lama (.doc/.xls/.ppt) - ASCII & UTF-16LE."""
    with open(path, "rb") as fh:
        data = fh.read(200 * 1024 * 1024)
    parts = []
    for m in re.finditer(rb"(?:[\x20-\x7e\xa0-\xff]\x00){%d,}" % min_len, data):
        parts.append(m.group().decode("utf-16-le", errors="ignore"))
    for m in re.finditer(rb"[\x20-\x7e\xa0-\xff]{%d,}" % min_len, data):
        parts.append(m.group().decode("cp1252", errors="ignore"))
    return "\n".join(parts)


def fmt_ts(sec: float | None) -> str:
    if sec is None:
        return "-"
    sec = max(0.0, float(sec))
    h = int(sec // 3600)
    m = int(sec % 3600 // 60)
    s = sec % 60
    return f"{h:02d}:{m:02d}:{s:04.1f}"


def _seg(source: str, text: str, **kw) -> dict:
    d = {"source": source, "text": text.strip()}
    d.update(kw)
    return d


# ---------------------------------------------------------------------------
# Model (dimuat sekali, lazy)
# ---------------------------------------------------------------------------
class Engines:
    def __init__(self, whisper_model: str = fconfig.WHISPER_DEFAULT_MODEL,
                 language: Optional[str] = fconfig.WHISPER_LANGUAGE,
                 log: Optional[Callable[[str], None]] = None):
        self.whisper_model = whisper_model
        self.language = language
        self._ocr = None
        self._asr = None
        self._log = log or (lambda m: None)

    # -- OCR -------------------------------------------------------------
    def ocr_reader(self):
        if self._ocr is None:
            import easyocr

            mdir = str(fconfig.EASYOCR_MODEL_DIR)
            udir = str(fconfig.EASYOCR_MODEL_DIR / "user")
            gpu = False
            try:
                import torch

                gpu = torch.cuda.is_available()
            except Exception:  # noqa: BLE001
                pass
            for langs in (fconfig.OCR_LANGS, ["en"]):
                try:
                    self._ocr = easyocr.Reader(langs, gpu=gpu, model_storage_directory=mdir,
                                               user_network_directory=udir, download_enabled=False,
                                               verbose=False)
                    self._log(f"Model OCR dimuat (bahasa={langs}, gpu={gpu}).")
                    break
                except Exception as exc:  # noqa: BLE001
                    self._log(f"Model OCR {langs} tidak tersedia offline: {exc}")
            if self._ocr is None:
                raise RuntimeError("Model OCR EasyOCR tidak ditemukan di folder models/easyocr")
        return self._ocr

    def ocr_array(self, rgb: np.ndarray) -> tuple[str, float]:
        """OCR satu gambar (array RGB) -> (teks urutan baca, rata-rata confidence)."""
        h, w = rgb.shape[:2]
        scale = 1.0
        if max(h, w) > fconfig.OCR_MAX_SIDE:
            scale = fconfig.OCR_MAX_SIDE / max(h, w)
        elif max(h, w) < fconfig.OCR_MIN_SIDE:
            scale = min(3.0, fconfig.OCR_MIN_SIDE / max(1, max(h, w)))
        if scale != 1.0:
            import cv2

            rgb = cv2.resize(rgb, (max(1, int(w * scale)), max(1, int(h * scale))),
                             interpolation=cv2.INTER_AREA if scale < 1 else cv2.INTER_CUBIC)
        res = self.ocr_reader().readtext(rgb, detail=1, paragraph=False)
        items = []
        for bbox, text, conf in res:
            if conf < fconfig.OCR_MIN_CONF or not text.strip():
                continue
            ys = [p[1] for p in bbox]
            xs = [p[0] for p in bbox]
            items.append((min(ys), max(ys), min(xs), text.strip(), float(conf)))
        if not items:
            return "", 0.0
        # Kelompokkan per baris (urutan baca atas->bawah, kiri->kanan)
        items.sort(key=lambda t: (t[0] + t[1]) / 2)
        lines: list[list[tuple]] = []
        for it in items:
            cy = (it[0] + it[1]) / 2
            if lines:
                last = lines[-1]
                ly0 = min(t[0] for t in last)
                ly1 = max(t[1] for t in last)
                if ly0 <= cy <= ly1:
                    last.append(it)
                    continue
            lines.append([it])
        text = "\n".join(" ".join(t[3] for t in sorted(line, key=lambda t: t[2])) for line in lines)
        conf = float(np.mean([t[4] for t in items]))
        return text, conf

    # -- ASR -------------------------------------------------------------
    def asr_model(self):
        if self._asr is None:
            from faster_whisper import WhisperModel

            threads = max(1, (os.cpu_count() or 4))
            kwargs = dict(download_root=str(fconfig.WHISPER_MODEL_DIR), cpu_threads=threads)
            try:
                self._asr = WhisperModel(self.whisper_model, device="cpu", compute_type="int8",
                                         local_files_only=True, **kwargs)
            except Exception as exc:  # noqa: BLE001
                self._log(f"Model Whisper '{self.whisper_model}' tidak ada offline ({exc}); mencoba unduh...")
                self._asr = WhisperModel(self.whisper_model, device="cpu", compute_type="int8", **kwargs)
            self._log(f"Model transkripsi Whisper '{self.whisper_model}' dimuat (CPU, {threads} thread).")
        return self._asr


# ---------------------------------------------------------------------------
# Dokumen
# ---------------------------------------------------------------------------
def extract_document(path: str, ext: str, engines: Engines, ocr_scanned: bool,
                     should_stop: StopCheck, sub: SubProgress) -> list[dict]:
    segs: list[dict] = []

    def add_chunks(text: str, label_prefix: str, page: Optional[int] = None):
        chunks = chunk_text(text)
        for ci, c in enumerate(chunks, 1):
            lbl = label_prefix if len(chunks) == 1 else f"{label_prefix} (bagian {ci})"
            segs.append(_seg("doc", c, page=page, label=lbl))

    if ext == ".pdf":
        import fitz  # PyMuPDF

        doc = fitz.open(path)
        try:
            n = doc.page_count
            for i in range(n):
                if should_stop():
                    raise StopRequested()
                page = doc.load_page(i)
                text = page.get_text("text") or ""
                if text.strip():
                    add_chunks(text, f"Halaman {i + 1}", page=i + 1)
                if ocr_scanned and len(text.strip()) < fconfig.PDF_OCR_MIN_CHARS and page.get_images():
                    sub(f"OCR halaman scan {i + 1}/{n}")
                    pix = page.get_pixmap(dpi=fconfig.PDF_OCR_DPI)
                    arr = np.frombuffer(pix.samples, dtype=np.uint8).reshape(pix.height, pix.width, pix.n)
                    if pix.n == 4:
                        arr = arr[:, :, :3]
                    elif pix.n == 1:
                        arr = np.repeat(arr, 3, axis=2)
                    otext, conf = engines.ocr_array(np.ascontiguousarray(arr))
                    if otext.strip():
                        segs.append(_seg("doc_ocr", otext, page=i + 1, label=f"Halaman {i + 1} (OCR scan)", conf=conf))
        finally:
            doc.close()
        return segs

    if ext in (".docx", ".docm"):
        import docx

        d = docx.Document(path)
        parts = [p.text for p in d.paragraphs]
        for t in d.tables:
            for row in t.rows:
                parts.append(" | ".join(c.text for c in row.cells))
        for s in d.sections:
            for hf in (s.header, s.footer):
                try:
                    parts.extend(p.text for p in hf.paragraphs)
                except Exception:  # noqa: BLE001
                    pass
        add_chunks("\n".join(p for p in parts if p.strip()), "Isi dokumen")
        return segs

    if ext == ".pptx":
        from pptx import Presentation

        prs = Presentation(path)
        for i, slide in enumerate(prs.slides, 1):
            parts = []
            for shape in slide.shapes:
                if getattr(shape, "has_text_frame", False) and shape.has_text_frame:
                    parts.append(shape.text_frame.text)
                if getattr(shape, "has_table", False) and shape.has_table:
                    for row in shape.table.rows:
                        parts.append(" | ".join(c.text for c in row.cells))
            if slide.has_notes_slide:
                parts.append("[Catatan] " + slide.notes_slide.notes_text_frame.text)
            txt = "\n".join(p for p in parts if p.strip())
            if txt:
                add_chunks(txt, f"Slide {i}", page=i)
        return segs

    if ext in (".xlsx", ".xlsm"):
        import openpyxl

        wb = openpyxl.load_workbook(path, read_only=True, data_only=True)
        try:
            for ws in wb.worksheets:
                rows = []
                for r_i, row in enumerate(ws.iter_rows(values_only=True), 1):
                    vals = [str(v) for v in row if v is not None and str(v).strip()]
                    if vals:
                        rows.append(f"[baris {r_i}] " + " | ".join(vals))
                    if should_stop():
                        raise StopRequested()
                if rows:
                    add_chunks("\n".join(rows), f"Sheet '{ws.title}'")
        finally:
            wb.close()
        return segs

    if ext in (".odt", ".ods", ".odp"):
        with zipfile.ZipFile(path) as z:
            xml = z.read("content.xml").decode("utf-8", errors="replace")
        add_chunks(strip_markup(xml), "Isi dokumen")
        return segs

    if ext == ".eml":
        with open(path, "rb") as fh:
            msg = email.message_from_binary_file(fh, policy=email.policy.default)
        header = "\n".join(f"{k}: {msg.get(k, '')}" for k in ("From", "To", "Cc", "Date", "Subject"))
        bodies = []
        for part in msg.walk():
            ctype = part.get_content_type()
            if ctype in ("text/plain", "text/html") and not part.is_attachment():
                try:
                    content = part.get_content()
                except Exception:  # noqa: BLE001
                    content = (part.get_payload(decode=True) or b"").decode("utf-8", "replace")
                bodies.append(strip_markup(content) if ctype == "text/html" else content)
            elif part.is_attachment():
                bodies.append(f"[Lampiran: {part.get_filename()}]")
        add_chunks(header + "\n\n" + "\n".join(bodies), "Email")
        return segs

    if ext in (".doc", ".xls", ".ppt"):
        add_chunks(binary_strings(path), "Teks terbaca (format lama)")
        return segs

    text = read_text_file(path)
    if ext == ".txt":
        from .chatparse import parse_chat_export

        chat = parse_chat_export(text)
        if chat:
            sub(f"export chat WhatsApp: {len(chat)} pesan")
            return chat
    if ext in (".html", ".htm", ".xml"):
        text = strip_markup(text)
    elif ext == ".rtf":
        text = strip_rtf(text)
    elif ext == ".json":
        try:
            text = json.dumps(json.loads(text), ensure_ascii=False, indent=1)
        except Exception:  # noqa: BLE001
            pass
    add_chunks(text, "Isi file")
    return segs


# ---------------------------------------------------------------------------
# Foto
# ---------------------------------------------------------------------------
def load_rgb(path: str) -> Optional[np.ndarray]:
    from PIL import Image, ImageFile, ImageOps

    ImageFile.LOAD_TRUNCATED_IMAGES = True
    with Image.open(path) as im:
        try:
            im.seek(0)
        except Exception:  # noqa: BLE001
            pass
        im = ImageOps.exif_transpose(im)
        return np.array(im.convert("RGB"))


def extract_image(path: str, engines: Engines) -> list[dict]:
    rgb = load_rgb(path)
    if rgb is None:
        return []
    text, conf = engines.ocr_array(rgb)
    if not text.strip():
        return []
    return [_seg("img_ocr", text, label="Teks dalam foto", conf=conf)]


# ---------------------------------------------------------------------------
# Audio / suara di video
# ---------------------------------------------------------------------------
def probe_media(path: str) -> dict:
    ffprobe = fconfig.find_tool("ffprobe")
    info = {"duration": None, "has_audio": None, "has_video": None}
    if not ffprobe:
        return info
    try:
        out = subprocess.run(
            [ffprobe, "-v", "error", "-show_entries", "format=duration:stream=codec_type",
             "-of", "json", path], capture_output=True, timeout=120, creationflags=_NO_WINDOW)
        data = json.loads(out.stdout.decode("utf-8", "replace") or "{}")
        dur = data.get("format", {}).get("duration")
        info["duration"] = float(dur) if dur not in (None, "N/A") else None
        types = [s.get("codec_type") for s in data.get("streams", [])]
        info["has_audio"] = "audio" in types
        info["has_video"] = "video" in types
    except Exception as exc:  # noqa: BLE001
        logger.warning("ffprobe gagal untuk %s: %s", path, exc)
    return info


def transcribe(path: str, engines: Engines, duration: Optional[float],
               should_stop: StopCheck, sub: SubProgress) -> list[dict]:
    model = engines.asr_model()
    segments, info = model.transcribe(
        path,
        language=engines.language,
        beam_size=fconfig.WHISPER_BEAM,
        vad_filter=True,
        vad_parameters={"min_silence_duration_ms": 700},
        condition_on_previous_text=False,
    )
    out = []
    for s in segments:
        if should_stop():
            raise StopRequested()
        txt = (s.text or "").strip()
        if txt:
            conf = float(np.exp(s.avg_logprob)) if s.avg_logprob is not None else None
            out.append(_seg("asr", txt, t_start=float(s.start), t_end=float(s.end),
                            label=f"{fmt_ts(s.start)} - {fmt_ts(s.end)}", conf=conf))
        if duration:
            sub(f"transkripsi {fmt_ts(s.end)} / {fmt_ts(duration)}")
    if out and info is not None:
        out[0]["lang"] = getattr(info, "language", None)
    return out


# ---------------------------------------------------------------------------
# Video: OCR frame
# ---------------------------------------------------------------------------
def _block_signature(rgb: np.ndarray) -> np.ndarray:
    import cv2

    g = cv2.cvtColor(rgb, cv2.COLOR_RGB2GRAY)
    return cv2.resize(g, (32, 18), interpolation=cv2.INTER_AREA).astype(np.float32)


def _changed(a: Optional[np.ndarray], b: np.ndarray) -> bool:
    if a is None:
        return True
    diff = np.abs(a - b)
    # rata-rata per blok 4x3 -> sensitif terhadap perubahan lokal (mis. subtitle)
    blocks = diff.reshape(6, 3, 8, 4).mean(axis=(1, 3))
    return float(blocks.max()) >= fconfig.VIDEO_SCENE_DIFF


def extract_video_frames(path: str, file_id: int, case_dir: Path, engines: Engines,
                         interval: float, duration: Optional[float],
                         should_stop: StopCheck, sub: SubProgress) -> list[dict]:
    import cv2
    from rapidfuzz import fuzz

    from .textnorm import normalize

    ffmpeg = fconfig.find_tool("ffmpeg")
    if not ffmpeg:
        raise RuntimeError("ffmpeg tidak ditemukan (taruh ffmpeg.exe di folder bin/ atau PATH)")
    tmp = Path(tempfile.mkdtemp(prefix=f"f{file_id}_", dir=case_dir / fconfig.TMP_DIR))
    frame_dir_rel = Path(fconfig.FRAME_DIR) / f"{file_id:06d}"
    segs: list[dict] = []
    proc = None
    try:
        vf = f"fps=1/{interval},scale='min({fconfig.VIDEO_FRAME_WIDTH},iw)':-2"
        proc = subprocess.Popen(
            [ffmpeg, "-nostdin", "-v", "error", "-i", path, "-vf", vf, "-q:v", "3",
             str(tmp / "f_%07d.jpg")],
            stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, creationflags=_NO_WINDOW)

        processed = 0
        last_sig = None
        last_seg: Optional[dict] = None
        last_norm = ""

        def handle(fp: Path, idx: int):
            nonlocal last_sig, last_seg, last_norm
            t = (idx - 1) * interval
            img = cv2.imread(str(fp))
            if img is None:
                return
            rgb = cv2.cvtColor(img, cv2.COLOR_BGR2RGB)
            sig = _block_signature(rgb)
            if not _changed(last_sig, sig):
                if last_seg is not None:
                    last_seg["t_end"] = t + interval
                    last_seg["label"] = f"{fmt_ts(last_seg['t_start'])} - {fmt_ts(last_seg['t_end'])}"
                return
            last_sig = sig
            text, conf = engines.ocr_array(rgb)
            norm = normalize(text)
            if not norm:
                last_seg, last_norm = None, ""
                return
            if last_seg is not None and fuzz.ratio(norm, last_norm) >= 90:
                last_seg["t_end"] = t + interval
                last_seg["label"] = f"{fmt_ts(last_seg['t_start'])} - {fmt_ts(last_seg['t_end'])}"
                return
            out_dir = case_dir / frame_dir_rel
            out_dir.mkdir(parents=True, exist_ok=True)
            rel = frame_dir_rel / f"t{int(t * 1000):010d}.jpg"
            small = img
            if img.shape[1] > 640:
                s = 640 / img.shape[1]
                small = cv2.resize(img, (640, int(img.shape[0] * s)), interpolation=cv2.INTER_AREA)
            cv2.imencode(".jpg", small, [cv2.IMWRITE_JPEG_QUALITY, 85])[1].tofile(str(case_dir / rel))
            last_seg = _seg("vid_ocr", text, t_start=t, t_end=t + interval,
                            label=f"{fmt_ts(t)} - {fmt_ts(t + interval)}", conf=conf,
                            frame_path=str(rel).replace("\\", "/"))
            last_norm = norm
            segs.append(last_seg)

        def drain(final: bool):
            nonlocal processed
            files = sorted(tmp.glob("f_*.jpg"))
            # Saat ffmpeg masih jalan, file terakhir mungkin belum selesai ditulis.
            ready = files if final else files[:-1]
            for fp in ready:
                if should_stop():
                    raise StopRequested()
                idx = int(fp.stem.split("_")[1])
                handle(fp, idx)
                fp.unlink(missing_ok=True)
                processed += 1
                total = int(duration / interval) + 1 if duration else None
                sub(f"OCR frame {processed}" + (f"/{total}" if total else ""))

        import time as _t

        while proc.poll() is None:
            drain(final=False)
            if should_stop():
                proc.kill()
                raise StopRequested()
            _t.sleep(0.3)
        drain(final=True)
        if proc.returncode not in (0, None) and not segs and processed == 0:
            err = (proc.stderr.read() if proc.stderr else b"").decode("utf-8", "replace")[-400:]
            raise RuntimeError(f"ffmpeg gagal membaca video: {err.strip()}")
    finally:
        if proc is not None and proc.poll() is None:
            proc.kill()
            proc.wait(timeout=30)
        shutil.rmtree(tmp, ignore_errors=True)
    return segs
