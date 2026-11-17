"""Buat dataset uji yang meniru hasil ekstraksi WhatsApp dari ponsel.

    python tests/make_whatsapp_dataset.py <folder_output>

Kalimat target: "tolong lakukan penyerangan itu"
"""
from __future__ import annotations

import shutil
import sqlite3
import subprocess
import sys
import tempfile
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

TARGET = "tolong lakukan penyerangan itu"


def font(sz):
    try:
        return ImageFont.truetype("C:/Windows/Fonts/arial.ttf", sz)
    except OSError:
        return ImageFont.load_default()


def tts_opus(text: str, out: Path) -> bool:
    wav = out.with_suffix(".wav")
    ps = ("Add-Type -AssemblyName System.Speech; $s=New-Object System.Speech.Synthesis.SpeechSynthesizer; $s.Rate=-2; "
          f"$s.SetOutputToWaveFile('{wav}'); $s.Speak('{text}'); $s.Dispose()")
    if subprocess.run(["powershell", "-NoProfile", "-Command", ps], capture_output=True).returncode != 0:
        return False
    subprocess.run(["ffmpeg", "-y", "-v", "error", "-i", str(wav), "-ac", "1", "-ar", "16000",
                    "-c:a", "libopus", "-b:a", "16k", str(out)], check=True)
    wav.unlink()
    return True


def android_new(path: Path) -> None:
    db = sqlite3.connect(path)
    db.executescript("""
    CREATE TABLE jid (_id INTEGER PRIMARY KEY, user TEXT, server TEXT, raw_string TEXT);
    CREATE TABLE chat (_id INTEGER PRIMARY KEY, jid_row_id INTEGER, subject TEXT);
    CREATE TABLE message (_id INTEGER PRIMARY KEY, chat_row_id INTEGER, from_me INTEGER, key_id TEXT,
      sender_jid_row_id INTEGER, timestamp INTEGER, message_type INTEGER, text_data TEXT);
    CREATE TABLE message_media (message_row_id INTEGER PRIMARY KEY, file_path TEXT, media_caption TEXT, mime_type TEXT);
    INSERT INTO jid VALUES (1,'6281200000001','s.whatsapp.net','6281200000001@s.whatsapp.net'),
                           (2,'6281200000002','s.whatsapp.net','6281200000002@s.whatsapp.net'),
                           (3,'120363000000001','g.us','120363000000001@g.us');
    INSERT INTO chat VALUES (1,1,NULL),(2,3,'Grup Rencana');
    INSERT INTO message VALUES
      (1,1,0,'A1',0,1794500000000,0,'bro udah siap belum'),
      (2,1,1,'A2',0,1794500060000,0,'Tolong lakukan penyerangan itu malam ini'),
      (3,1,0,'A3',0,1794500100000,2,NULL),
      (4,2,0,'A4',2,1794500200000,0,'semua sudah kumpul di lokasi'),
      (5,2,0,'A5',2,1794500300000,1,NULL);
    INSERT INTO message_media VALUES
      (3,'Media/WhatsApp Voice Notes/202611/PTT-20261112-WA0003.opus',NULL,'audio/ogg'),
      (5,'Media/WhatsApp Images/IMG-20261112-WA0007.jpg','foto lokasi target','image/jpeg');
    """)
    db.commit()
    db.close()


def wa_contacts(path: Path) -> None:
    db = sqlite3.connect(path)
    db.executescript("""
    CREATE TABLE wa_contacts (_id INTEGER PRIMARY KEY, jid TEXT, display_name TEXT, wa_name TEXT);
    INSERT INTO wa_contacts VALUES (1,'6281200000001@s.whatsapp.net','Budi Kontak',NULL),
                                   (2,'6281200000002@s.whatsapp.net','Andi Kontak',NULL);
    """)
    db.commit()
    db.close()


def android_legacy(path: Path) -> None:
    db = sqlite3.connect(path)
    db.executescript("""
    CREATE TABLE messages (_id INTEGER PRIMARY KEY, key_remote_jid TEXT, key_from_me INTEGER, key_id TEXT,
      data TEXT, timestamp INTEGER, media_caption TEXT, remote_resource TEXT, media_name TEXT);
    INSERT INTO messages VALUES (1,'-1',0,'x',NULL,0,NULL,NULL,NULL),
      (2,'6281300000009@s.whatsapp.net',0,'L2','tolong lakukan penyerangan itu (arsip lama)',1600000000000,NULL,NULL,NULL);
    """)
    db.commit()
    db.close()


def ios(path: Path) -> None:
    db = sqlite3.connect(path)
    db.executescript("""
    CREATE TABLE ZWACHATSESSION (Z_PK INTEGER PRIMARY KEY, ZPARTNERNAME TEXT, ZCONTACTJID TEXT);
    CREATE TABLE ZWAMEDIAITEM (Z_PK INTEGER PRIMARY KEY, ZMEDIALOCALPATH TEXT, ZTITLE TEXT);
    CREATE TABLE ZWAMESSAGE (Z_PK INTEGER PRIMARY KEY, ZCHATSESSION INTEGER, ZISFROMME INTEGER, ZFROMJID TEXT,
      ZPUSHNAME TEXT, ZMESSAGEDATE REAL, ZTEXT TEXT, ZMEDIAITEM INTEGER);
    INSERT INTO ZWACHATSESSION VALUES (1,'Rudi iPhone','6281400000001@s.whatsapp.net');
    INSERT INTO ZWAMESSAGE VALUES (1,1,0,'6281400000001@s.whatsapp.net','Rudi',815000000,
      'hay, tolong lakukan penyerangan itu sesuai rencana',NULL);
    """)
    db.commit()
    db.close()


def generic(path: Path) -> None:
    db = sqlite3.connect(path)
    db.executescript("""
    CREATE TABLE notes (id INTEGER PRIMARY KEY, title TEXT, body TEXT, created INTEGER);
    INSERT INTO notes VALUES (1,'belanja','beras, gula, minyak',0),
                             (2,'catatan','ingat: tolong lakukan penyerangan itu hari jumat',0);
    """)
    db.commit()
    db.close()


def wal_db(dest: Path) -> None:
    """Database mode WAL; pesan terakhir hanya ada di file -wal (belum di-checkpoint)."""
    tmp = Path(tempfile.mkdtemp())
    src = tmp / dest.name
    db = sqlite3.connect(src)
    db.execute("PRAGMA journal_mode=WAL")
    db.execute("PRAGMA wal_autocheckpoint=0")
    db.execute("CREATE TABLE notes (id INTEGER PRIMARY KEY, body TEXT)")
    db.commit()
    db.execute("INSERT INTO notes VALUES (1, 'pesan di WAL: tolong lakukan penyerangan itu sekarang')")
    db.commit()
    shutil.copy2(src, dest)
    shutil.copy2(str(src) + "-wal", str(dest) + "-wal")  # salin saat koneksi masih terbuka
    db.close()
    shutil.rmtree(tmp, ignore_errors=True)


def main(out: Path) -> None:
    wa = out / "WhatsApp"
    media = wa / "Media"
    for d in ("WhatsApp Images", "WhatsApp Voice Notes/202611", "WhatsApp Documents"):
        (media / d).mkdir(parents=True, exist_ok=True)
    (wa / "Databases").mkdir(parents=True, exist_ok=True)
    (out / "lama").mkdir(exist_ok=True)
    (out / "iphone").mkdir(exist_ok=True)
    (out / "aplikasi_lain").mkdir(exist_ok=True)

    (out / "WhatsApp Chat dengan Budi.txt").write_text(
        "12/11/26 21.00 - Pesan dan panggilan dienkripsi secara end-to-end.\n"
        "12/11/26 21.01 - Budi: bro udah siap belum\n"
        "12/11/26 21.02 - Andi: Hay tolong lakukan penyerangan itu\n"
        "besok malam ya, jangan telat\n"
        "12/11/26 21.03 - Budi: IMG-20261112-WA0007.jpg (file terlampir)\n", encoding="utf-8")
    (out / "_chat.txt").write_text(
        "[12/11/26 21.05.10] Rudi: oke nanti kabari\n"
        "[12/11/26 21.06.44] Andi: hay, tolong lakukan penyerangan itu sesuai rencana\n", encoding="utf-8")

    im = Image.new("RGB", (720, 1000), (11, 20, 26))
    d = ImageDraw.Draw(im)
    d.rounded_rectangle([40, 300, 690, 420], 18, fill=(0, 92, 75))
    d.text((65, 320), "lokasi target", font=font(34), fill="white")
    im.save(media / "WhatsApp Images" / "IMG-20261112-WA0007.jpg", quality=85)
    tts_opus("Hay, tolong lakukan penyerangan itu. Jangan sampai ketahuan.",
             media / "WhatsApp Voice Notes/202611/PTT-20261112-WA0003.opus")

    android_new(wa / "Databases" / "msgstore.db")
    wa_contacts(wa / "Databases" / "wa.db")
    (wa / "Databases" / "msgstore-2026-11-12.1.db.crypt15").write_bytes(bytes(range(256)) * 64)
    android_legacy(out / "lama" / "msgstore_lama.db")
    ios(out / "iphone" / "ChatStorage.sqlite")
    generic(out / "aplikasi_lain" / "catatan.sqlite")
    wal_db(out / "aplikasi_lain" / "catatan_wal.db")
    print(f"Dataset WhatsApp dibuat di {out}")


if __name__ == "__main__":
    main(Path(sys.argv[1] if len(sys.argv) > 1 else "tests/_whatsapp_dataset"))
