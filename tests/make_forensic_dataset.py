"""Buat dataset uji forensik kecil berisi kalimat target di berbagai jenis file.

    python tests/make_forensic_dataset.py <folder_output>

Kalimat target: "hay tolong lakukan penyerangan itu"
- dokumen: DOCX, PDF teks, PDF hasil scan (gambar), TXT, XLSX
- foto: PNG tangkapan layar chat, JPG disamarkan berekstensi .dat
- audio: WAV & MP3 hasil text-to-speech Windows
- video: MP4 dengan teks di layar (detik 4-8) + suara TTS
- distraktor tanpa kalimat target
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

TARGET = "hay tolong lakukan penyerangan itu"


def font(size: int):
    for f in ("C:/Windows/Fonts/arial.ttf", "C:/Windows/Fonts/segoeui.ttf"):
        if Path(f).exists():
            return ImageFont.truetype(f, size)
    return ImageFont.load_default()


def text_image(lines: list[str], size=(1080, 720), bg=(240, 240, 235), fg=(20, 20, 20), fs=46) -> Image.Image:
    im = Image.new("RGB", size, bg)
    d = ImageDraw.Draw(im)
    y = 60
    for ln in lines:
        d.text((60, y), ln, font=font(fs), fill=fg)
        y += int(fs * 1.6)
    return im


def tts(text: str, out_wav: Path) -> bool:
    ps = (
        "Add-Type -AssemblyName System.Speech; "
        "$s = New-Object System.Speech.Synthesis.SpeechSynthesizer; "
        "$s.Rate = -2; "
        f"$s.SetOutputToWaveFile('{out_wav}'); "
        f"$s.Speak('{text}'); $s.Dispose()"
    )
    r = subprocess.run(["powershell", "-NoProfile", "-Command", ps], capture_output=True)
    return r.returncode == 0 and out_wav.exists()


def main(out: Path) -> None:
    out.mkdir(parents=True, exist_ok=True)
    (out / "dokumen").mkdir(exist_ok=True)
    (out / "foto").mkdir(exist_ok=True)
    (out / "media").mkdir(exist_ok=True)

    # --- dokumen
    import docx

    d = docx.Document()
    d.add_paragraph("Notulen rapat tanggal 3 Maret.")
    d.add_paragraph(f"Pesan dari koordinator: {TARGET.capitalize()}, besok jam 9 malam.")
    d.save(out / "dokumen" / "notulen.docx")

    import fitz

    pdf = fitz.open()
    pg = pdf.new_page()
    pg.insert_text((72, 100), "Laporan keuangan triwulan.", fontsize=12)
    pg2 = pdf.new_page()
    pg2.insert_text((72, 100), "Catatan lain:", fontsize=12)
    pg2.insert_text((72, 130), f"Hay, tolong lakukan penyerangan itu secepatnya.", fontsize=12)
    pdf.save(out / "dokumen" / "laporan.pdf")

    scan = text_image(["SURAT EDARAN", "", "Hay tolong lakukan", "penyerangan itu!"], size=(1240, 1754), bg=(255, 255, 255), fs=60)
    scan_path = out / "_scan.png"
    scan.save(scan_path)
    pdf2 = fitz.open()
    p = pdf2.new_page(width=595, height=842)
    p.insert_image(p.rect, filename=str(scan_path))
    pdf2.save(out / "dokumen" / "scan_surat.pdf")
    scan_path.unlink()

    (out / "dokumen" / "chat_export.txt").write_text(
        "[12/03/26 21:01] Budi: sudah siap?\n[12/03/26 21:02] Andi: HAY!! tolong lakukan penyerangan itu.\n",
        encoding="utf-8")
    (out / "dokumen" / "resep.txt").write_text("Resep nasi goreng: bawang, kecap, telur.", encoding="utf-8")

    import openpyxl

    wb = openpyxl.Workbook()
    ws = wb.active
    ws.append(["Tanggal", "Pesan"])
    ws.append(["2026-03-12", "hay tolong lakukan penyerangan itu"])
    wb.save(out / "dokumen" / "rekap.xlsx")

    # --- foto
    text_image(["Andi:", "Hay tolong lakukan penyerangan itu", "", "Budi: siap bos"]).save(out / "foto" / "screenshot_chat.png")
    text_image(["Selamat ulang tahun!", "Semoga sehat selalu"]).save(out / "foto" / "kartu.png")
    text_image(["hay tolong lakukan", "penyerangan itu"], bg=(30, 30, 60), fg=(255, 255, 255)).save(
        out / "foto" / "IMG_0001.dat", "JPEG")  # disamarkan: JPEG berekstensi .dat
    Image.new("RGB", (800, 600), (90, 160, 90)).save(out / "foto" / "pemandangan.jpg")

    # --- audio
    wav = out / "media" / "voice_note.wav"
    if tts("Hay, tolong lakukan penyerangan itu. Jangan sampai ketahuan.", wav):
        subprocess.run(["ffmpeg", "-y", "-v", "error", "-i", str(wav), str(out / "media" / "PTT-20260312.mp3")])
        wav.unlink()
    else:
        print("TTS gagal - audio dilewati")
    tts("Good morning, the weather is nice today.", out / "media" / "salam.wav")

    # --- video: 4 dtk kosong, 4 dtk teks target, 4 dtk kosong + suara
    frames = out / "_v"
    frames.mkdir(exist_ok=True)
    text_image(["Video kegiatan"], bg=(10, 10, 10), fg=(200, 200, 200)).save(frames / "a.png")
    text_image(["Video kegiatan", "", "HAY TOLONG LAKUKAN PENYERANGAN ITU"], bg=(10, 10, 10), fg=(255, 255, 0)).save(frames / "b.png")
    lst = frames / "list.txt"
    lst.write_text("file 'a.png'\nduration 4\nfile 'b.png'\nduration 4\nfile 'a.png'\nduration 4\nfile 'a.png'\n")
    vwav = frames / "v.wav"
    has_audio = tts("Ini rekaman kegiatan sore hari. Hay tolong lakukan penyerangan itu.", vwav)
    cmd = ["ffmpeg", "-y", "-v", "error", "-f", "concat", "-safe", "0", "-i", str(lst)]
    if has_audio:
        cmd += ["-i", str(vwav), "-c:a", "aac"]
    cmd += ["-vf", "fps=25,format=yuv420p", "-c:v", "libx264", "-t", "12", str(out / "media" / "VID_20260312.mp4")]
    subprocess.run(cmd, check=True)
    subprocess.run(["ffmpeg", "-y", "-v", "error", "-f", "lavfi", "-i", "testsrc=duration=5:size=640x360:rate=25",
                    "-pix_fmt", "yuv420p", str(out / "media" / "distraktor.mp4")], check=True)
    for f in frames.iterdir():
        f.unlink()
    frames.rmdir()
    print(f"Dataset uji dibuat di {out}")


if __name__ == "__main__":
    main(Path(sys.argv[1] if len(sys.argv) > 1 else "tests/_forensic_dataset"))
