"""Pengamanan temuan: salin file bukti asli (hash salinan diverifikasi sama
dengan hash asli, salinan dibuat read-only), cuplikan frame, teks ekstraksi,
manifest hash, dan laporan HTML + CSV siap lampiran berita acara.

Dipakai untuk hasil pencarian TEKS (secure_hits) maupun hasil pencarian
FOTO MIRIP (secure_photo_results).
"""
from __future__ import annotations

import base64
import csv
import hashlib
import html
import os
import re
import shutil
import stat
import subprocess
import time
from pathlib import Path
from typing import Callable, Optional

from . import AUTHOR, REPO_URL, TOOL_NAME, TOOL_VERSION, fconfig
from .extractors import fmt_ts, hash_file
from .search import Hit
from .store import CaseStore, now_text, operator_name

LogCb = Optional[Callable[[str], None]]
ProgCb = Optional[Callable[[int, int, str], None]]

_CSS = """
body{font-family:Segoe UI,Arial,sans-serif;margin:0;color:#111;background:#fff}
.top{background:linear-gradient(90deg,#06122a,#0b2f66);color:#e8f4ff;padding:18px 28px;border-bottom:4px solid #d4a017}
.top h1{margin:0;font-size:20px;letter-spacing:2px}
.top div{font-size:12px;color:#9fc3ea;margin-top:4px;letter-spacing:1px}
.wrap{padding:18px 28px}
h2{font-size:15px;margin-top:26px;border-bottom:2px solid #d4a017;padding-bottom:4px;letter-spacing:1px}
table{border-collapse:collapse;width:100%;font-size:12.5px}
th,td{border:1px solid #bbb;padding:6px;vertical-align:top;text-align:left}
th{background:#0b2f66;color:#fff} tr:nth-child(even) td{background:rgba(240,244,250,.65)}
mark{background:#ffd54a;padding:0 2px;font-weight:600}
.mono{font-family:Consolas,monospace;font-size:11px;word-break:break-all}
.meta td{border:none;padding:3px 12px 3px 0;background:none!important}
img{max-width:240px;border:1px solid #999}
.ok{color:#0a7a2f;font-weight:700} .bad{color:#b00020;font-weight:700}
.note{font-size:12px;color:#555;border-left:4px solid #d4a017;padding:8px 12px;background:#fffaf0}
.wm-logo{position:fixed;top:50%;left:50%;width:460px;height:460px;transform:translate(-50%,-50%);
  opacity:.07;z-index:49;pointer-events:none}
.foot{display:flex;justify-content:space-between;gap:20px;margin-top:22px;padding-top:10px;
  border-top:2px solid #d4a017;font-size:11px;color:#333}
.foot .r{text-align:right}
@page{size:A4;margin:12mm 10mm 18mm 10mm}
@media print{*{-webkit-print-color-adjust:exact;print-color-adjust:exact}
  body{font-size:11px} table{font-size:10.5px} img{max-width:150px} .wrap{padding:10px 4px}
  tr{page-break-inside:avoid}}
"""


def _slug(s: str, n: int = 40) -> str:
    return re.sub(r"[^\w\-]+", "_", s).strip("_")[:n] or "pencarian"


def _new_package(workspace: Path, label: str) -> Path:
    stamp = time.strftime("%Y%m%d_%H%M%S")
    base = workspace / fconfig.SECURED_DIR / f"{stamp}_{_slug(label)}"
    out, k = base, 1
    while out.exists():  # paket lama tidak pernah ditimpa
        k += 1
        out = base.with_name(f"{base.name}_{k}")
    for sub in ("file_bukti", "frame", "teks"):
        (out / sub).mkdir(parents=True, exist_ok=True)
    return out


def _copy_verified(src: str, dst: Path, expected_sha: Optional[str]) -> tuple[str, str, bool]:
    """Salin file (pertahankan timestamp), hitung hash salinan, set read-only."""
    if not expected_sha:
        expected_sha, _ = hash_file(src)
    shutil.copy2(src, dst)
    csha, cmd5 = hash_file(str(dst))
    try:
        os.chmod(dst, stat.S_IREAD)
    except OSError:
        pass
    return csha, cmd5, csha == expected_sha


def _location(h: Hit) -> str:
    if h.t_start is not None:
        return f"{fmt_ts(h.t_start)} - {fmt_ts(h.t_end)}"
    return h.label or "-"


def _highlight_html(h: Hit, ctx: int = 220) -> str:
    t = h.text
    if h.match_span:
        s, e = h.match_span
        a = max(0, s - ctx)
        b = min(len(t), e + ctx)
        return ("…" if a else "") + html.escape(t[a:s]) + "<mark>" + html.escape(t[s:e]) + "</mark>" + \
            html.escape(t[e:b]) + ("…" if b < len(t) else "")
    return html.escape(t[: ctx * 2])


def _meta_rows(info: dict, extra: list[tuple[str, str]]) -> str:
    e = html.escape
    rows = [("Folder bukti", info.get("evidence_dir", "")),
            ("Operator", info.get("operator") or operator_name()),
            ("Komputer", info.get("host", "")),
            *extra,
            ("Waktu laporan", now_text()),
            ("Alat", f"{TOOL_NAME} v{TOOL_VERSION}"),
            ("Pembuat alat", AUTHOR),
            ("*Sumber resmi", f"<a href='{REPO_URL}'>{html.escape(REPO_URL)}</a>")]
    # kunci berawalan '*' = nilai sudah berupa HTML aman
    return "".join(f"<tr><td>{e(k.lstrip('*'))}</td><td>: {v if k.startswith('*') else e(v)}</td></tr>"
                   for k, v in rows)


def _write_package_hashes(out: Path) -> None:
    lines = []
    for p in sorted(out.rglob("*")):
        if p.is_file() and p.name != "manifest_paket.sha256":
            h = hashlib.sha256()
            with open(p, "rb") as fh:
                for block in iter(lambda: fh.read(1 << 20), b""):
                    h.update(block)
            lines.append(f"{h.hexdigest()}  {p.relative_to(out).as_posix()}")
    (out / "manifest_paket.sha256").write_text("\n".join(lines) + "\n", encoding="utf-8")


# ===========================================================================
# Hasil pencarian TEKS
# ===========================================================================
def secure_hits(store: CaseStore, hits: list[Hit], query: str, mode: str, copy_files: bool = True,
                log: LogCb = None, progress: ProgCb = None) -> Path:
    log = log or (lambda m: None)
    progress = progress or (lambda a, b, c: None)
    out = _new_package(store.case_dir, query)
    info = store.all_info()

    copied: dict[int, dict] = {}
    file_ids = list(dict.fromkeys(h.file_id for h in hits))
    for n, fid in enumerate(file_ids, 1):
        rec = store.get_file(fid)
        progress(n - 1, len(file_ids), f"mengamankan {rec['name']}")
        entry = {"no": n, "rec": rec, "copy": None, "copy_sha": None, "verified": None}
        prefix = f"{n:03d}_"
        if copy_files and os.path.exists(rec["path"]):
            dst = out / "file_bukti" / (prefix + rec["name"])
            csha, _m, ok = _copy_verified(rec["path"], dst, rec["sha256"])
            entry.update(copy=dst, copy_sha=csha, verified=ok)
            if not ok:
                log(f"  [PERINGATAN] hash salinan TIDAK cocok: {rec['path']}")
        if rec.get("extract_txt"):
            src_txt = store.case_dir / rec["extract_txt"]
            if src_txt.exists():
                shutil.copy2(src_txt, out / "teks" / (prefix + Path(rec["extract_txt"]).name))
        copied[fid] = entry

    rows = []
    for i, h in enumerate(hits, 1):
        ent = copied[h.file_id]
        frame_rel = ""
        if h.frame_path:
            src = store.case_dir / h.frame_path
            if src.exists():
                dst = out / "frame" / f"{i:04d}_{Path(h.frame_path).parent.name}_{Path(h.frame_path).name}"
                shutil.copy2(src, dst)
                frame_rel = f"frame/{dst.name}"
        elif h.kind == "image" and ent["copy"] is not None:
            frame_rel = f"file_bukti/{ent['copy'].name}"
        rows.append((i, h, ent, frame_rel))

    with open(out / "hasil_pencarian.csv", "w", newline="", encoding="utf-8-sig") as fh:
        w = csv.writer(fh)
        w.writerow(["No", "Skor", "Jenis File", "Sumber Teks", "Lokasi (halaman/waktu)", "Kutipan Teks",
                    "Path Asli", "SHA-256", "MD5", "Salinan Bukti", "Hash Salinan Cocok", "Cuplikan Frame"])
        for i, h, ent, frame_rel in rows:
            w.writerow([i, f"{h.score:.1f}", h.kind_label, h.source_label, _location(h), h.text,
                        h.path, h.sha256, h.md5, ent["copy"].name if ent["copy"] else "",
                        {True: "YA", False: "TIDAK", None: "-"}[ent["verified"]], frame_rel])

    _write_manifest(out, info, f"Pencarian teks: \"{query}\" (mode {mode})",
                    [(ent["no"], ent["rec"]["path"], ent["rec"]["size"], ent["rec"]["sha256"],
                      ent["rec"]["md5"], ent["copy"], ent["copy_sha"], ent["verified"]) for ent in copied.values()])

    mode_txt = {"frasa": "Frasa persis", "semua": "Semua kata", "fuzzy": "Fuzzy (toleran salah OCR/transkrip)"}
    e = html.escape
    body = [f"<h2>DAFTAR TEMUAN</h2><table><tr><th>No</th><th>Skor</th><th>File / Jenis</th>"
            f"<th>Lokasi</th><th>Kutipan teks</th><th>Cuplikan</th></tr>"]
    for i, h, ent, frame_rel in rows:
        img = f'<img src="{e(frame_rel)}">' if frame_rel else ""
        body.append(
            f"<tr><td>{i}</td><td>{h.score:.0f}</td>"
            f"<td><b>{e(h.name)}</b><br>{e(h.kind_label)} - {e(h.source_label)}"
            f"<div class=mono>{e(h.path)}<br>SHA-256: {e(h.sha256)}</div></td>"
            f"<td>{e(_location(h))}</td><td>{_highlight_html(h)}</td><td>{img}</td></tr>")
    body.append("</table>")
    _write_html(out, "LAPORAN TEMUAN PENCARIAN TEKS", info,
                [("*Kalimat dicari", f"<b>\"{e(query)}\"</b> ({e(mode_txt.get(mode, mode))})"),
                 ("Jumlah temuan", f"{len(rows)} lokasi di {len(copied)} file")],
                "".join(body), list(copied.values()))
    pdf = write_pdf(out, log)
    _write_package_hashes(out)
    store.audit("AMANKAN_BUKTI_TEKS", f"pencarian=\"{query}\" mode={mode} temuan={len(hits)} "
                                      f"file={len(copied)} folder={out} pdf={'ya' if pdf else 'tidak'}")
    progress(len(file_ids), len(file_ids), "selesai")
    log(f"Bukti diamankan di: {out}")
    return out


# ===========================================================================
# Hasil pencarian FOTO MIRIP
# ===========================================================================
def secure_photo_results(store: CaseStore, results: list, query_path: str,
                         log: LogCb = None, progress: ProgCb = None) -> Path:
    """`results`: list SearchResult (app.search) - id, path, final_score, clip_sim, phash_sim, orb_score."""
    log = log or (lambda m: None)
    progress = progress or (lambda a, b, c: None)
    out = _new_package(store.case_dir, "foto_mirip_" + Path(query_path).stem)
    info = store.all_info()

    q_sha, q_md5 = hash_file(query_path)
    q_dst = out / "frame" / ("REFERENSI_" + Path(query_path).name)
    shutil.copy2(query_path, q_dst)

    entries = []
    for n, r in enumerate(results, 1):
        progress(n - 1, len(results), f"mengamankan {Path(r.path).name}")
        ent = {"no": n, "r": r, "copy": None, "copy_sha": None, "verified": None, "sha": None, "md5": None,
               "size": None}
        if os.path.exists(r.path):
            sha, md5 = hash_file(r.path)
            ent.update(sha=sha, md5=md5, size=os.path.getsize(r.path))
            dst = out / "file_bukti" / f"{n:03d}_{Path(r.path).name}"
            csha, _m, ok = _copy_verified(r.path, dst, sha)
            ent.update(copy=dst, copy_sha=csha, verified=ok)
        entries.append(ent)

    with open(out / "hasil_pencarian.csv", "w", newline="", encoding="utf-8-sig") as fh:
        w = csv.writer(fh)
        w.writerow(["No", "Skor Akhir", "CLIP (semantik)", "pHash", "ORB (fitur lokal)", "Path Asli",
                    "SHA-256", "MD5", "Salinan", "Hash Salinan Cocok"])
        for ent in entries:
            r = ent["r"]
            w.writerow([ent["no"], f"{r.final_score:.4f}", f"{r.clip_sim:.4f}", f"{r.phash_sim:.4f}",
                        "" if r.orb_score is None else f"{r.orb_score:.4f}", r.path, ent["sha"], ent["md5"],
                        ent["copy"].name if ent["copy"] else "",
                        {True: "YA", False: "TIDAK", None: "-"}[ent["verified"]]])

    _write_manifest(out, info, f"Pencarian foto mirip. Referensi: {query_path} SHA-256={q_sha} MD5={q_md5}",
                    [(ent["no"], ent["r"].path, ent["size"], ent["sha"], ent["md5"], ent["copy"],
                      ent["copy_sha"], ent["verified"]) for ent in entries])

    e = html.escape
    body = [f"<h2>FOTO REFERENSI</h2><p><img src='frame/{e(q_dst.name)}'><br>"
            f"<span class=mono>{e(query_path)}<br>SHA-256: {q_sha}</span></p>"
            "<h2>DAFTAR FOTO MIRIP</h2><table><tr><th>No</th><th>Skor</th><th>Rincian skor</th>"
            "<th>File</th><th>Foto</th></tr>"]
    for ent in entries:
        r = ent["r"]
        orb = "-" if r.orb_score is None else f"{r.orb_score:.2f}"
        img = f"<img src='file_bukti/{e(ent['copy'].name)}'>" if ent["copy"] else ""
        body.append(f"<tr><td>{ent['no']}</td><td><b>{r.final_score:.3f}</b></td>"
                    f"<td>CLIP {r.clip_sim:.2f}<br>pHash {r.phash_sim:.2f}<br>ORB {orb}</td>"
                    f"<td class=mono>{e(r.path)}<br>SHA-256: {e(ent['sha'] or '')}</td><td>{img}</td></tr>")
    body.append("</table>")
    copied = [{"no": ent["no"], "rec": {"path": ent["r"].path, "size": ent["size"], "sha256": ent["sha"],
                                        "md5": ent["md5"]},
               "copy": ent["copy"], "verified": ent["verified"]} for ent in entries]
    _write_html(out, "LAPORAN TEMUAN PENCARIAN FOTO MIRIP", info,
                [("Foto referensi", query_path), ("Jumlah hasil", str(len(entries)))],
                "".join(body), copied,
                note="Skor kemiripan hanya untuk mengurutkan kandidat, BUKAN bukti dua foto identik. "
                     "Skor pHash/ORB tinggi menandakan near-duplicate (foto sama yang diubah/di-crop); "
                     "CLIP tinggi saja menandakan kemiripan isi/scene.")
    pdf = write_pdf(out, log)
    _write_package_hashes(out)
    store.audit("AMANKAN_BUKTI_FOTO", f"referensi={query_path} sha256={q_sha} hasil={len(entries)} folder={out} pdf={'ya' if pdf else 'tidak'}")
    progress(len(results), len(results), "selesai")
    log(f"Bukti diamankan di: {out}")
    return out


# ===========================================================================
def _write_manifest(out: Path, info: dict, title: str, items) -> None:
    with open(out / "manifest_hash.txt", "w", encoding="utf-8") as fh:
        fh.write(f"MANIFEST BUKTI DIGITAL - {now_text()}\n")
        fh.write(f"Operator: {info.get('operator') or operator_name()} | Folder bukti: {info.get('evidence_dir', '')}\n")
        fh.write(f"Alat: {TOOL_NAME} v{TOOL_VERSION} - dibuat oleh {AUTHOR} ({REPO_URL})\n")
        fh.write(f"{title}\n\n")
        for no, path, size, sha, md5, copy, copy_sha, ok in items:
            fh.write(f"[{no:03d}] {path}\n      ukuran={size} SHA-256={sha} MD5={md5}\n")
            if copy:
                fh.write(f"      salinan={copy.name} SHA-256 salinan={copy_sha} COCOK={'YA' if ok else 'TIDAK'}\n")


def _logo_data_uri() -> str:
    """Logo watermark: `logo.png` di folder aplikasi bila ada, selain itu lambang perisai bawaan."""
    try:
        from ..workspace import app_dir

        lp = app_dir() / "logo.png"
        if lp.exists():
            return "data:image/png;base64," + base64.b64encode(lp.read_bytes()).decode()
    except Exception:  # noqa: BLE001
        pass
    svg = (
        "<svg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 200 200'>"
        "<polygon points='100,6 181,53 181,147 100,194 19,147 19,53' fill='#0b2f66' stroke='#d4a017' stroke-width='8'/>"
        "<polygon points='100,30 160,65 160,135 100,170 40,135 40,65' fill='none' stroke='#00b4e0' stroke-width='4'/>"
        "<circle cx='92' cy='92' r='30' fill='none' stroke='#ffffff' stroke-width='10'/>"
        "<line x1='114' y1='114' x2='142' y2='142' stroke='#ffffff' stroke-width='12' stroke-linecap='round'/>"
        "<line x1='76' y1='92' x2='108' y2='92' stroke='#d4a017' stroke-width='6'/></svg>"
    )
    return "data:image/svg+xml;base64," + base64.b64encode(svg.encode()).decode()


def _tile_data_uri(line1: str, line2: str) -> str:
    """Pola teks transparan miring berulang (watermark teks)."""
    e = html.escape
    svg = (
        "<svg xmlns='http://www.w3.org/2000/svg' width='600' height='340'>"
        "<g transform='rotate(-28 300 170)' font-family='Consolas, monospace' fill='#0b2f66' fill-opacity='0.10' "
        "text-anchor='middle'>"
        f"<text x='300' y='165' font-size='14' font-weight='bold' letter-spacing='2'>{e(line1)}</text>"
        f"<text x='300' y='185' font-size='10.5' letter-spacing='1'>{e(line2)}</text></g></svg>"
    )
    return "data:image/svg+xml;base64," + base64.b64encode(svg.encode("utf-8")).decode()


def _write_html(out: Path, title: str, info: dict, extra_meta, body: str, copied: list,
                note: str = "") -> None:
    e = html.escape
    integ = ["<h2>INTEGRITAS FILE BUKTI</h2><table><tr><th>No</th><th>File asli</th>"
             "<th>SHA-256 / MD5 asli</th><th>Salinan</th><th>Verifikasi salinan</th></tr>"]
    for ent in copied:
        r = ent["rec"]
        ver = {True: '<span class="ok">COCOK</span>', False: '<span class="bad">TIDAK COCOK</span>',
               None: "-"}[ent["verified"]]
        cp = f'<a href="file_bukti/{e(ent["copy"].name)}">{e(ent["copy"].name)}</a>' if ent["copy"] else "-"
        integ.append(f"<tr><td>{ent['no']}</td><td class=mono>{e(r['path'])}<br>{r['size']} byte</td>"
                     f"<td class=mono>{e(r['sha256'] or '')}<br>{e(r['md5'] or '')}</td><td>{cp}</td><td>{ver}</td></tr>")
    integ.append("</table>")
    default_note = ("Teks hasil OCR/transkripsi otomatis dapat mengandung kesalahan pengenalan; setiap temuan "
                    "wajib diverifikasi dengan membuka/memutar file aslinya pada lokasi yang tercantum. ")
    # Kode verifikasi = SHA-256 dari manifest_hash.txt (daftar hash semua file bukti dalam paket)
    man = out / "manifest_hash.txt"
    verif = hashlib.sha256(man.read_bytes()).hexdigest() if man.exists() else "-"
    stamp = time.strftime("%d-%m-%Y %H:%M")
    tile = _tile_data_uri(f"{TOOL_NAME.upper()} • BUKTI DIGITAL",
                          f"{stamp} • {info.get('operator') or operator_name()} • {AUTHOR}")
    doc = f"""<!doctype html><html lang="id"><head><meta charset="utf-8"><title>{e(title)}</title>
<meta name="author" content="{e(AUTHOR)}"><meta name="generator" content="{e(TOOL_NAME)} v{TOOL_VERSION}">
<style>{_CSS}
.wm-tile{{position:fixed;inset:0;background-image:url("{tile}");background-repeat:repeat;z-index:50;pointer-events:none}}
</style></head><body>
<div class="wm-tile"></div>
<img class="wm-logo" src="{_logo_data_uri()}" alt="">
<div class="top"><h1>{e(title)}</h1>
<div>{e(TOOL_NAME.upper())} v{TOOL_VERSION} &middot; BUKTI DIGITAL &middot; ALAT KARYA {e(AUTHOR.upper())}</div></div>
<div class="wrap"><table class="meta">{_meta_rows(info, extra_meta)}</table>
{body}{''.join(integ)}
<p class="note">{e(note or default_note)} File asli dibuka read-only dan tidak diubah oleh alat ini;
keaslian salinan dibuktikan dengan kecocokan hash SHA-256. Hash seluruh isi paket ada di
<code>manifest_paket.sha256</code>.</p>
<div class="foot"><div><b>KODE VERIFIKASI (SHA-256 manifest_hash.txt)</b><br><span class="mono">{verif}</span></div>
<div class="r">Dibuat dengan <b>{e(TOOL_NAME)} v{TOOL_VERSION}</b><br>Pembuat alat: <b>{e(AUTHOR)}</b><br>
<a href="{REPO_URL}">{e(REPO_URL)}</a></div></div>
</div></body></html>"""
    (out / "laporan.html").write_text(doc, encoding="utf-8")


# ===========================================================================
# PDF (dicetak dari laporan.html via Microsoft Edge / Chrome headless)
# ===========================================================================
_NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)


def _find_browser() -> Optional[str]:
    cands = [
        os.path.expandvars(r"%ProgramFiles(x86)%\Microsoft\Edge\Application\msedge.exe"),
        os.path.expandvars(r"%ProgramFiles%\Microsoft\Edge\Application\msedge.exe"),
        os.path.expandvars(r"%ProgramFiles%\Google\Chrome\Application\chrome.exe"),
        os.path.expandvars(r"%ProgramFiles(x86)%\Google\Chrome\Application\chrome.exe"),
        os.path.expandvars(r"%LocalAppData%\Google\Chrome\Application\chrome.exe"),
    ]
    for c in cands:
        if c and "%" not in c and os.path.exists(c):
            return c
    return shutil.which("msedge") or shutil.which("chrome")


def write_pdf(out: Path, log: LogCb = None) -> Optional[Path]:
    """Cetak laporan.html -> laporan.pdf (watermark ikut tercetak), lalu tambahkan
    nomor halaman, kode verifikasi, dan identitas pembuat alat di setiap halaman."""
    log = log or (lambda m: None)
    html_path = out / "laporan.html"
    pdf_path = out / "laporan.pdf"
    browser = _find_browser()
    if not browser:
        log("  [INFO] Edge/Chrome tidak ditemukan - laporan.pdf dilewati (laporan.html tetap tersedia).")
        return None
    profile = out.parent.parent / fconfig.TMP_DIR / "pdf_profile"
    profile.mkdir(parents=True, exist_ok=True)
    try:
        subprocess.run([browser, "--headless=new", "--disable-gpu", "--no-first-run", "--no-default-browser-check",
                        f"--user-data-dir={profile}", "--no-pdf-header-footer",
                        "--run-all-compositor-stages-before-draw", "--virtual-time-budget=8000",
                        f"--print-to-pdf={pdf_path}", html_path.as_uri()],
                       capture_output=True, timeout=240, creationflags=_NO_WINDOW)
    except Exception as exc:  # noqa: BLE001
        log(f"  [INFO] Gagal membuat PDF: {exc}")
        return None
    if not pdf_path.exists():
        log("  [INFO] PDF tidak terbentuk - laporan.html tetap tersedia.")
        return None
    try:
        import fitz

        man = out / "manifest_hash.txt"
        verif = hashlib.sha256(man.read_bytes()).hexdigest() if man.exists() else "-"
        doc = fitz.open(str(pdf_path))
        n = doc.page_count
        for i, page in enumerate(doc, 1):
            r = page.rect
            y = r.height - 22
            page.draw_line(fitz.Point(28, y - 8), fitz.Point(r.width - 28, y - 8), color=(0.83, 0.63, 0.09), width=0.8)
            page.insert_text(fitz.Point(28, y + 2), f"KODE VERIFIKASI (SHA-256): {verif}", fontsize=6.5,
                             fontname="cour", color=(0.25, 0.25, 0.3))
            page.insert_text(fitz.Point(28, y + 11), f"{TOOL_NAME} v{TOOL_VERSION} - pembuat alat: {AUTHOR} - {REPO_URL}",
                             fontsize=6.5, fontname="helv", color=(0.35, 0.35, 0.4))
            txt = f"Halaman {i} dari {n}"
            w = fitz.get_text_length(txt, fontname="helv", fontsize=8)
            page.insert_text(fitz.Point(r.width - 28 - w, y + 6), txt, fontsize=8, fontname="helv",
                             color=(0.1, 0.18, 0.4))
        doc.set_metadata({"title": out.name, "author": AUTHOR, "creator": f"{TOOL_NAME} v{TOOL_VERSION}",
                          "producer": f"{TOOL_NAME} v{TOOL_VERSION} ({REPO_URL})",
                          "subject": "Laporan bukti digital", "keywords": f"verifikasi {verif}"})
        tmp = pdf_path.with_suffix(".tmp.pdf")
        doc.save(str(tmp), garbage=3, deflate=True)
        doc.close()
        os.replace(tmp, pdf_path)
    except Exception as exc:  # noqa: BLE001
        log(f"  [INFO] Penomoran halaman PDF gagal ({exc}); PDF tanpa nomor halaman tetap disimpan.")
    return pdf_path
