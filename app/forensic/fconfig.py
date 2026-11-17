"""Konfigurasi modul forensik teks (semua nilai boleh diubah)."""
from __future__ import annotations

import shutil
import sys
from pathlib import Path


def _base_dir() -> Path:
    """Folder bundel (EXE) atau root project (source)."""
    if getattr(sys, "frozen", False):
        return Path(sys._MEIPASS)  # type: ignore[attr-defined]
    return Path(__file__).resolve().parent.parent.parent


def _app_dir() -> Path:
    """Folder tempat EXE / main.py berada (untuk folder kasus default)."""
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent.parent.parent


BASE_DIR = _base_dir()
APP_DIR = _app_dir()
MODELS_DIR = BASE_DIR / "models"
WHISPER_MODEL_DIR = MODELS_DIR / "whisper"     # cache HF berisi Systran/faster-whisper-*
EASYOCR_MODEL_DIR = MODELS_DIR / "easyocr"     # craft_mlt_25k.pth, latin_g2.pth, english_g2.pth

# Folder kasus default (sengaja di samping aplikasi, BUKAN di folder bukti
# dan bukan di drive C: yang sering penuh). Bisa diganti dari GUI.
DEFAULT_CASES_ROOT = APP_DIR / "KASUS"

CASE_DB = "case.db"
AUDIT_TXT = "audit_log.txt"
EXTRACT_DIR = "hasil_ekstraksi"   # teks hasil ekstraksi per file (.txt)
FRAME_DIR = "frame_bukti"          # cuplikan frame video tempat teks ditemukan
SECURED_DIR = "bukti_diamankan"    # salinan bukti + laporan hasil pencarian
TMP_DIR = "_tmp"

# ---------------------------------------------------------------------------
# Jenis file
# ---------------------------------------------------------------------------
IMAGE_EXT = {".jpg", ".jpeg", ".jfif", ".png", ".bmp", ".gif", ".tif", ".tiff", ".webp"}
AUDIO_EXT = {".mp3", ".wav", ".m4a", ".aac", ".ogg", ".opus", ".oga", ".flac", ".wma",
             ".amr", ".aiff", ".aif", ".mka"}
VIDEO_EXT = {".mp4", ".mkv", ".avi", ".mov", ".wmv", ".flv", ".webm", ".3gp", ".3g2",
             ".m4v", ".mpg", ".mpeg", ".ts", ".mts", ".m2ts", ".vob", ".ogv"}
DOC_EXT = {".pdf", ".docx", ".docm", ".doc", ".pptx", ".ppt", ".xlsx", ".xlsm", ".xls",
           ".odt", ".ods", ".odp", ".rtf", ".txt", ".log", ".csv", ".tsv", ".json",
           ".xml", ".html", ".htm", ".md", ".eml", ".srt", ".vtt", ".ini"}
# Database (SQLite): WhatsApp msgstore.db / ChatStorage.sqlite / database aplikasi lain
DB_EXT = {".db", ".sqlite", ".sqlite3", ".db3", ".sqlitedb"}
# Database WhatsApp terenkripsi (butuh kunci; harus didekripsi dulu dengan tool forensik)
ENCRYPTED_DB_EXT = {".crypt12", ".crypt14", ".crypt15"}
# Batas pembacaan database umum (non-WhatsApp)
DB_MAX_ROWS_PER_TABLE = 200_000
DB_MAX_TOTAL_CHARS = 60_000_000

KIND_LABEL = {"document": "Dokumen", "database": "Database/Chat", "image": "Foto", "audio": "Audio",
              "video": "Video", "other": "Lainnya"}
# Urutan proses: yang cepat dulu supaya hasil bisa dicari secepatnya.
KIND_ORDER = {"document": 0, "database": 1, "image": 2, "audio": 3, "video": 4, "other": 9}

SOURCE_LABEL = {
    "doc": "Teks dokumen",
    "doc_ocr": "OCR halaman scan",
    "img_ocr": "OCR foto",
    "asr": "Transkrip suara",
    "vid_ocr": "OCR frame video",
    "chat_export": "Pesan chat (export)",
    "wa_db": "Pesan WhatsApp (database)",
    "db_text": "Teks database",
}
# Sumber per platform media sosial / aplikasi pesan (lihat social.PLATFORM_LABEL)
_PLATFORMS = {"facebook": "Facebook", "messenger": "Messenger", "instagram": "Instagram", "threads": "Threads",
              "telegram": "Telegram", "twitter": "Twitter/X", "discord": "Discord", "tiktok": "TikTok",
              "snapchat": "Snapchat", "skype": "Skype", "gchat": "Google Chat", "linkedin": "LinkedIn",
              "sms": "SMS/Telepon", "line": "LINE", "imessage": "iMessage/SMS", "signal": "Signal",
              "wechat": "WeChat", "social": "Media sosial (umum)"}
SOURCE_LABEL.update(_PLATFORMS)
# Sumber yang berupa pesan chat (dipakai untuk menghubungkan media <-> pesan)
CHAT_SOURCES = {"wa_db", "chat_export", *_PLATFORMS}

# ---------------------------------------------------------------------------
# Parameter ekstraksi
# ---------------------------------------------------------------------------
OCR_LANGS = ["id", "en"]          # id = model latin (bahasa Indonesia)
OCR_MIN_CONF = 0.20
OCR_MAX_SIDE = 2400               # gambar besar diperkecil dulu (kecepatan)
OCR_MIN_SIDE = 500                # gambar kecil diperbesar (akurasi)

WHISPER_DEFAULT_MODEL = "small"   # "base" = cepat, "small" = lebih akurat
WHISPER_LANGUAGE = "id"           # None = deteksi otomatis
WHISPER_BEAM = 5

VIDEO_FRAME_INTERVAL = 2.0        # detik antar frame yang di-OCR
VIDEO_FRAME_WIDTH = 1280
VIDEO_SCENE_DIFF = 3.0            # beda blok minimal supaya frame di-OCR ulang

PDF_OCR_MIN_CHARS = 25            # halaman PDF dg teks < ini dianggap hasil scan -> OCR
PDF_OCR_DPI = 200
TEXT_CHUNK = 2000                 # panjang potongan teks dokumen panjang
TEXT_OVERLAP = 300

HASH_BLOCK = 4 * 1024 * 1024


def find_tool(name: str) -> str | None:
    """Cari ffmpeg/ffprobe/ffplay: folder bin/ di samping app dulu, lalu PATH."""
    for d in (APP_DIR / "bin", BASE_DIR / "bin"):
        p = d / f"{name}.exe"
        if p.exists():
            return str(p)
    return shutil.which(name)
