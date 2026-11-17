"""Buat PDF Panduan Penggunaan dari README.md (tanpa bagian instalasi/developer).

    python scripts\\make_manual_pdf.py
    -> dokumentasi\\Panduan_Cyber_Forensic_Evidence_Search_v<versi>.pdf

Butuh: pip install markdown, PyMuPDF (sudah ada), Microsoft Edge/Chrome.
"""
from __future__ import annotations

import html
import re
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import markdown  # noqa: E402

from app.forensic import AUTHOR, REPO_URL, TOOL_NAME, TOOL_VERSION  # noqa: E402
from app.forensic.report import _find_browser, _logo_data_uri, _tile_data_uri  # noqa: E402

# Bagian README yang TIDAK dimasukkan ke panduan (instalasi & khusus developer)
SKIP_SECTIONS = ("Download & Instal", "Daftar Isi", "Instalasi dari GitHub", "Membuat versi EXE",
                 "Pengujian", "Struktur project")
# Pertanyaan FAQ yang berkaitan dengan instalasi
SKIP_FAQ = ("ffmpeg tidak ditemukan", "Model OCR", "PUTAR DI DETIK INI hanya membuka",
            "Konflik versi library")


def split_sections(md: str) -> tuple[str, list[tuple[str, str]]]:
    parts = re.split(r"(?m)^## ", md)
    head = parts[0]
    secs = []
    for p in parts[1:]:
        title, _, body = p.partition("\n")
        secs.append((title.strip(), body))
    return head, secs


def clean_requirements(body: str) -> str:
    keep = []
    for ln in body.splitlines():
        if re.search(r"Python|Lainnya|Git|Internet hanya|offline\.$|setelah itu aplikasi", ln):
            continue
        keep.append(ln)
    return "\n".join(keep).replace("± 8 GB (library + model)", "± 3 GB (aplikasi)") + \
        "\n\n> Aplikasi berjalan 100% offline. Laporan PDF memakai Microsoft Edge (bawaan Windows 10/11).\n"


def clean_faq(body: str) -> str:
    blocks = re.split(r"\n(?=\*\*)", body)
    out = [b for b in blocks if not any(k in b.split("\n", 1)[0] for k in SKIP_FAQ)]
    # "**Pertanyaan**\njawaban" -> judul kecil + paragraf terpisah (agar daftar bernomor terbaca)
    out = [re.sub(r"^\*\*(.+?)\*\*\s*\n", r"#### \1\n\n", b.strip()) for b in out]
    return "\n\n".join(out)


def build_markdown() -> tuple[str, list[str]]:
    md = (ROOT / "README.md").read_text(encoding="utf-8")
    _head, secs = split_sections(md)
    chosen = []
    n = 0
    for title, body in secs:
        bare = re.sub(r"^\d+\.\s*", "", title)
        if any(k in bare for k in SKIP_SECTIONS):
            continue
        if bare.startswith("Persyaratan sistem"):
            body = clean_requirements(body)
        if bare.startswith("Pemecahan masalah"):
            body = clean_faq(body)
        n += 1
        old_num = re.match(r"^(\d+)\.", title)
        if old_num:  # nomor ulang sub-bagian ### 8.3 -> ### 5.3
            body = re.sub(rf"(?m)^### {old_num.group(1)}\.(\d+)", rf"### {n}.\1", body)
        chosen.append((f"{n}. {bare}", body))
    text = "\n".join(f"## {t}\n{b}" for t, b in chosen)
    # link internal (#...) -> teks biasa; pemisah --- dibuang (diganti page-break)
    text = re.sub(r"\[([^\]]+)\]\(#[^)]*\)", r"\1", text)
    text = re.sub(r"(?m)^---\s*$", "", text)
    # kalimat yang merujuk instalasi/developer
    text = re.sub(r"(?m)^> Ingin menjalankan dari source.*\n(> .*\n)*", "", text)
    text = text.replace("(dokumentasi/", "(")
    # Python-Markdown butuh indentasi 4 spasi untuk isi bertingkat (README memakai 3)
    text = re.sub(r"(?m)^ {3}(?=\S)", "    ", text)
    text = re.sub(r"(?m)^ {5}(?=\S)", "      ", text)
    return text, [t for t, _ in chosen]


CSS = """
@page { size: A4; margin: 16mm 14mm 20mm 14mm; }
@page :first { margin: 0; }
* { -webkit-print-color-adjust: exact; print-color-adjust: exact; }
body { font-family: 'Segoe UI', Arial, sans-serif; color: #15202e; font-size: 10.6pt; line-height: 1.5; margin: 0; }
.cover { height: 297mm; width: 210mm; box-sizing: border-box; padding: 34mm 22mm 18mm;
  background: linear-gradient(160deg, #030814 0%, #0a2350 55%, #06122a 100%); color: #e8f4ff;
  position: relative; overflow: hidden; page-break-after: always; }
.cover .grid { position: absolute; inset: 0; opacity: .18;
  background-image: linear-gradient(#0d3a6e 1px, transparent 1px), linear-gradient(90deg, #0d3a6e 1px, transparent 1px);
  background-size: 26px 26px; }
.cover .stripe { position: absolute; right: -40mm; top: 0; width: 70mm; height: 100%;
  background: repeating-linear-gradient(115deg, rgba(212,160,23,.55) 0 12px, transparent 12px 40px); opacity: .35; }
.cover .in { position: relative; }
.cover img.logo { width: 46mm; height: 46mm; border: none; margin: 0; }
.cover h1 { font-family: Bahnschrift, 'Segoe UI', sans-serif; letter-spacing: 4px; font-size: 30pt; margin: 14mm 0 2mm; color: #fff; }
.cover .kind { font-family: Bahnschrift, sans-serif; letter-spacing: 6px; color: #d4a017; font-size: 15pt; }
.cover .tag { margin-top: 8mm; font-size: 12pt; color: #9fc3ea; max-width: 150mm; }
.cover .line { height: 3px; width: 70mm; background: linear-gradient(90deg, #d4a017, #00d4ff); margin: 10mm 0; }
.cover .meta { font-size: 11pt; line-height: 1.9; }
.cover .meta b { color: #fff; }
.cover .foot { position: absolute; bottom: 18mm; left: 22mm; right: 22mm; font-size: 9pt; color: #6f8fb3;
  border-top: 1px solid #17406e; padding-top: 4mm; }
.toc { page-break-after: always; }
.toc h2 { border: none; }
.toc ol { font-size: 12pt; line-height: 2.1; padding-left: 8mm; }
.toc li::marker { color: #d4a017; font-weight: 700; }
h2 { font-family: Bahnschrift, 'Segoe UI', sans-serif; letter-spacing: 1.5px; color: #0b2f66; font-size: 17pt;
  border-bottom: 3px solid #d4a017; padding-bottom: 3px; margin-top: 0; page-break-before: always; }
.toc + .content h2:first-child { page-break-before: avoid; }
h3 { font-family: Bahnschrift, 'Segoe UI', sans-serif; color: #0b2f66; font-size: 12.5pt; margin: 16px 0 6px;
  border-left: 4px solid #00a8d6; padding-left: 8px; page-break-after: avoid; }
h4 { color: #0b2f66; margin: 12px 0 4px; }
table { border-collapse: collapse; width: 100%; margin: 8px 0 12px; font-size: 9.4pt; page-break-inside: auto; }
th { background: #0b2f66; color: #fff; text-align: left; padding: 6px; }
td { border: 1px solid #c9d3e0; padding: 5px 6px; vertical-align: top; }
tr { page-break-inside: avoid; }
tr:nth-child(even) td { background: rgba(240,244,250,.7); }
code { font-family: Consolas, monospace; font-size: 9pt; background: #eef2f8; padding: 0 3px; border-radius: 2px; }
pre { background: #0b1626; color: #cfe8ff; padding: 10px 12px; border-left: 4px solid #d4a017; font-size: 8.6pt;
  white-space: pre-wrap; page-break-inside: avoid; }
pre code { background: none; color: inherit; padding: 0; }
blockquote { margin: 10px 0; padding: 8px 12px; background: #fff8e6; border-left: 4px solid #d4a017; color: #4a3a12; }
img { max-width: 100%; border: 1px solid #b8c4d6; display: block; margin: 8px auto; page-break-inside: avoid; }
a { color: #0b5cad; text-decoration: none; }
.wm-tile { position: fixed; inset: 0; z-index: 50; pointer-events: none; background-repeat: repeat; }
.wm-logo { position: fixed; top: 50%; left: 50%; width: 120mm; height: 120mm; transform: translate(-50%,-50%);
  opacity: .05; z-index: 49; pointer-events: none; }
.endnote { margin-top: 18px; padding: 10px 12px; border-top: 3px solid #d4a017; font-size: 9.5pt; color: #334; }
"""


def build_html(md_text: str, titles: list[str]) -> str:
    body = markdown.markdown(md_text, extensions=["tables", "fenced_code", "sane_lists"])
    logo = _logo_data_uri()
    tile = _tile_data_uri(f"{TOOL_NAME.upper()} • PANDUAN PENGGUNAAN", f"v{TOOL_VERSION} • {AUTHOR}")
    e = html.escape
    names = [re.sub(r"^\d+\.\s*", "", t) for t in titles]
    toc = "".join(f"<li>{e(nm)}</li>" for nm in names)
    today = time.strftime("%d-%m-%Y")
    return f"""<!doctype html><html lang="id"><head><meta charset="utf-8">
<title>Panduan Penggunaan {e(TOOL_NAME)} v{TOOL_VERSION}</title>
<meta name="author" content="{e(AUTHOR)}"><style>{CSS}
.wm-tile{{background-image:url("{tile}")}}</style></head><body>
<section class="cover"><div class="grid"></div><div class="stripe"></div><div class="in">
<img class="logo" src="{logo}" alt="">
<h1>CYBER FORENSIC<br>EVIDENCE SEARCH</h1>
<div class="kind">PANDUAN PENGGUNAAN</div>
<div class="tag">Ekstraksi, pencarian, dan pengamanan bukti digital: menemukan kalimat di ribuan video,
audio, foto, dan dokumen, serta mencari foto mirip, secara offline, read-only, dan teraudit.</div>
<div class="line"></div>
<div class="meta">Versi <b>{TOOL_VERSION}</b><br>Dibuat oleh <b>{e(AUTHOR)}</b><br>
Sumber resmi: <b>{e(REPO_URL.replace("https://", ""))}</b><br>Tanggal dokumen: {today}</div></div>
<div class="foot">{e(TOOL_NAME)} &middot; alat bantu forensik digital &middot; hasil pengenalan otomatis wajib
diverifikasi oleh pemeriksa.</div></section>
<div class="wm-tile"></div><img class="wm-logo" src="{logo}" alt="">
<section class="toc"><h2>DAFTAR ISI</h2><ol>{toc}</ol></section>
<section class="content">{body}
<div class="endnote">Dokumen ini adalah panduan penggunaan resmi <b>{e(TOOL_NAME)} v{TOOL_VERSION}</b>,
dibuat oleh <b>{e(AUTHOR)}</b>. Sumber resmi aplikasi: <a href="{REPO_URL}">{e(REPO_URL)}</a></div>
</section></body></html>"""


def main() -> None:
    md_text, titles = build_markdown()
    out_dir = ROOT / "dokumentasi"
    html_path = out_dir / "_panduan_tmp.html"
    pdf_path = out_dir / f"Panduan_Cyber_Forensic_Evidence_Search_v{TOOL_VERSION}.pdf"
    html_path.write_text(build_html(md_text, titles), encoding="utf-8")
    browser = _find_browser()
    if not browser:
        sys.exit("Edge/Chrome tidak ditemukan.")
    profile = ROOT / "_tmp_build" / "pdf_profile"
    profile.mkdir(parents=True, exist_ok=True)
    raw = pdf_path.with_suffix(".raw.pdf")
    subprocess.run([browser, "--headless=new", "--disable-gpu", "--no-first-run", f"--user-data-dir={profile}",
                    "--no-pdf-header-footer", "--generate-pdf-document-outline", "--virtual-time-budget=10000",
                    f"--print-to-pdf={raw}", html_path.as_uri()], capture_output=True, timeout=300)
    html_path.unlink(missing_ok=True)

    import fitz

    doc = fitz.open(str(raw))
    n = doc.page_count
    for i, page in enumerate(doc, 1):
        if i == 1:
            continue  # sampul tanpa footer
        r = page.rect
        y = r.height - 26
        page.draw_line(fitz.Point(40, y - 6), fitz.Point(r.width - 40, y - 6), color=(0.83, 0.63, 0.09), width=0.8)
        page.insert_text(fitz.Point(40, y + 6), f"Panduan Penggunaan {TOOL_NAME} v{TOOL_VERSION}  -  {AUTHOR}",
                         fontsize=7.5, fontname="helv", color=(0.25, 0.3, 0.4))
        page.insert_text(fitz.Point(40, y + 15), REPO_URL, fontsize=6.8, fontname="helv", color=(0.35, 0.4, 0.5))
        t = f"Halaman {i} dari {n}"
        w = fitz.get_text_length(t, fontname="helv", fontsize=8.5)
        page.insert_text(fitz.Point(r.width - 40 - w, y + 9), t, fontsize=8.5, fontname="helv", color=(0.04, 0.18, 0.4))
    # bookmark/outline dari judul bagian
    toc = []
    for i, page in enumerate(doc, 1):
        for b in page.get_text("dict")["blocks"]:
            for line in b.get("lines", []):
                txt = "".join(s["text"] for s in line["spans"]).strip()
                size = max((s["size"] for s in line["spans"]), default=0)
                if re.match(r"^\d+\.\d+\s", txt) and 11.5 <= size < 15:
                    toc.append([2, txt, i])
                elif re.match(r"^\d+\.\s", txt) and size >= 15:
                    toc.append([1, txt, i])
    if toc:
        if toc[0][0] != 1:
            toc.insert(0, [1, "Panduan", 2])
        doc.set_toc(toc)
    doc.set_metadata({"title": f"Panduan Penggunaan {TOOL_NAME} v{TOOL_VERSION}", "author": AUTHOR,
                      "subject": "Panduan penggunaan alat forensik digital", "creator": f"{TOOL_NAME} v{TOOL_VERSION}",
                      "producer": REPO_URL, "keywords": "forensik digital, OCR, transkripsi, bukti digital"})
    doc.save(str(pdf_path), garbage=3, deflate=True)
    doc.close()
    raw.unlink(missing_ok=True)
    print(f"OK {pdf_path} ({n} halaman, {len(toc)} bookmark)")


if __name__ == "__main__":
    main()
