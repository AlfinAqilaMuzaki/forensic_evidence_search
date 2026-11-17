"""Pipeline kasus: scan folder bukti -> hash (SHA-256 + MD5) -> ekstraksi teks
per jenis file -> simpan segmen + salinan teks -> audit log.

Bisa dihentikan dan dilanjutkan kapan saja (file yang sudah selesai tidak
diproses ulang). Bila aplikasi crash di tengah satu file, file itu ditandai
'crash' pada run berikutnya supaya tidak membuat crash berulang.
"""
from __future__ import annotations

import json
import logging
import os
import re
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Optional

from . import AUTHOR, REPO_URL, TOOL_NAME, TOOL_VERSION, fconfig
from .extractors import (
    Engines, StopRequested, extract_document, extract_image, extract_video_frames,
    fmt_ts, hash_file, kind_from_ext, probe_media, sniff_kind, transcribe,
)
from .store import CaseStore, now_text
from .textnorm import normalize

logger = logging.getLogger(__name__)

ProgressCb = Callable[[int, int, str], None]
LogCb = Callable[[str], None]


@dataclass
class ExtractOptions:
    kinds: set = field(default_factory=lambda: {"document", "database", "image", "audio", "video"})
    whisper_model: str = fconfig.WHISPER_DEFAULT_MODEL
    language: Optional[str] = fconfig.WHISPER_LANGUAGE
    frame_interval: float = fconfig.VIDEO_FRAME_INTERVAL
    video_ocr: bool = True
    video_asr: bool = True
    pdf_ocr: bool = True
    retry_failed: bool = False

    def as_json(self) -> str:
        d = dict(self.__dict__)
        d["kinds"] = sorted(self.kinds)
        return json.dumps(d, ensure_ascii=False)


@dataclass
class RunStats:
    scanned: int = 0
    new_files: int = 0
    changed: int = 0
    missing: int = 0
    processed: int = 0
    errors: int = 0
    stopped: bool = False
    elapsed: float = 0.0


def _safe_name(name: str) -> str:
    return re.sub(r"[^\w.\-]+", "_", name)[:80]


class CaseProcessor:
    def __init__(self, store: CaseStore, evidence_dir: str):
        self.store = store
        self.evidence_dir = Path(evidence_dir)

    # ------------------------------------------------------------------ scan
    def scan(self, log: LogCb, progress: ProgressCb, should_stop) -> RunStats:
        st = RunStats()
        known = self.store.known_files()
        seen = set()
        log(f"Scan folder bukti: {self.evidence_dir}")
        batch = 0
        for dirpath, _dirs, names in os.walk(self.evidence_dir):
            for name in names:
                if should_stop():
                    st.stopped = True
                    self.store.commit()
                    return st
                full = str(Path(dirpath) / name)
                seen.add(full)
                st.scanned += 1
                try:
                    s = os.stat(full)
                except OSError as exc:
                    log(f"  [ERROR] tidak bisa membaca {full}: {exc}")
                    continue
                prev = known.get(full)
                if prev is not None:
                    fid, size, mtime, status = prev
                    if size == s.st_size and mtime == s.st_mtime and status != "missing":
                        continue
                    # File berubah sejak terakhir di-hash -> catat & proses ulang
                    self.store.delete_segments(fid)
                    self.store.update_file(fid, size=s.st_size, mtime=s.st_mtime, status="pending",
                                           sha256=None, md5=None, error=None, n_segments=0)
                    self.store.audit("FILE_BERUBAH", f"{full} (ukuran/waktu berubah sejak scan sebelumnya)")
                    st.changed += 1
                    continue
                ext = Path(name).suffix.lower()
                kind = kind_from_ext(ext)
                detected_by = "ekstensi"
                mismatch = 0
                sk, sext = sniff_kind(full)
                if kind is None and sk is not None:
                    # Tanpa ekstensi (umum utk database aplikasi Android) atau ekstensi = tipe
                    # sebenarnya (.js arsip Twitter) BUKAN penyamaran; ekstensi lain = disamarkan.
                    disguised = bool(ext) and ext != sext and not (sk == "database" and ext in fconfig.DB_EXT)
                    kind, detected_by, mismatch = sk, "signature", int(disguised)
                elif kind is not None and sk is not None and sk != kind:
                    # isi file tidak sesuai ekstensinya (indikasi penyamaran)
                    kind, detected_by, mismatch = sk, "signature", 1
                rec = dict(
                    path=full, rel_path=os.path.relpath(full, self.evidence_dir), name=name, ext=ext,
                    kind=kind or "other", detected_by=detected_by, ext_mismatch=mismatch,
                    size=s.st_size, mtime=s.st_mtime, ctime=s.st_ctime,
                    status="pending" if kind else "unsupported",
                )
                self.store.add_file(rec)
                st.new_files += 1
                batch += 1
                if batch % 500 == 0:
                    self.store.commit()
                    progress(0, 0, f"scan: {st.scanned} file...")
        missing = [p for p in known if p not in seen and known[p][3] != "missing"]
        for p in missing:
            self.store.update_file(known[p][0], status="missing")
        st.missing = len(missing)
        self.store.commit()
        log(f"Scan selesai: {st.scanned} file di folder, baru={st.new_files}, berubah={st.changed}, hilang={st.missing}.")
        self.store.audit("SCAN", f"folder={self.evidence_dir} total={st.scanned} baru={st.new_files} "
                                 f"berubah={st.changed} hilang={st.missing}")
        return st

    # ---------------------------------------------------------------- run
    def run(self, opts: ExtractOptions, log: LogCb, progress: ProgressCb, should_stop) -> RunStats:
        t0 = time.time()
        crashed = self.store.reset_crashed()
        if crashed:
            log(f"{crashed} file ditandai 'crash' dari sesi sebelumnya (dilewati).")
        if opts.retry_failed:
            n = self.store.requeue_failed()
            log(f"{n} file error/crash dijadwalkan ulang.")

        st = self.scan(log, progress, should_stop)
        if st.stopped:
            return st

        todo = self.store.files_to_process(opts.kinds)
        self.store.audit("MULAI_EKSTRAKSI", f"{len(todo)} file, opsi={opts.as_json()}")
        log(f"Akan diproses: {len(todo)} file "
            f"({', '.join(fconfig.KIND_LABEL[k] for k in sorted(opts.kinds))}).")

        engines = Engines(opts.whisper_model, opts.language, log=log)
        total = len(todo)
        t_start = time.time()
        for i, rec in enumerate(todo, 1):
            if should_stop():
                st.stopped = True
                break
            fid = rec["id"]
            path = rec["path"]
            label = f"[{fconfig.KIND_LABEL.get(rec['kind'], rec['kind'])}] {rec['name']}"
            done_before = i - 1
            eta = ""
            if done_before:
                per = (time.time() - t_start) / done_before
                eta = f" | sisa ~{fmt_ts(per * (total - done_before))}"

            def sub(msg: str, _i=i, _label=label, _eta=eta):
                progress(_i - 1, total, f"{_label} - {msg}{_eta}")

            sub("hash SHA-256/MD5")
            self.store.update_file(fid, status="processing")
            self.store.commit()
            try:
                if not os.path.exists(path):
                    raise FileNotFoundError("file tidak ada lagi di folder bukti")
                sha, md5 = hash_file(path, should_stop)
                self.store.update_file(fid, sha256=sha, md5=md5, hashed_at=time.time())
                segs, duration = self._extract(rec, opts, engines, should_stop, sub)
                for s in segs:
                    s["norm"] = normalize(s["text"])
                segs = [s for s in segs if s["norm"]]
                self.store.delete_segments(fid)
                self.store.add_segments(fid, segs)
                txt_rel = self._write_extract_txt(rec, sha, md5, segs)
                self.store.update_file(
                    fid, status="done", error=None, n_segments=len(segs),
                    n_chars=sum(len(s["text"]) for s in segs), duration=duration,
                    processed_at=time.time(), extract_txt=txt_rel, options=opts.as_json())
                self.store.commit()
                st.processed += 1
                if segs:
                    log(f"  OK {label}: {len(segs)} segmen teks")
            except StopRequested:
                self.store.update_file(fid, status="pending")
                self.store.commit()
                st.stopped = True
                log(f"  Dihentikan saat memproses {label} (akan diulang saat dilanjutkan).")
                break
            except Exception as exc:  # noqa: BLE001
                logger.exception("Gagal memproses %s", path)
                self.store.update_file(fid, status="error", error=f"{type(exc).__name__}: {exc}"[:1000],
                                       processed_at=time.time())
                self.store.commit()
                st.errors += 1
                log(f"  [ERROR] {label}: {exc}")
            progress(i, total, f"{label} selesai{eta}")

        st.elapsed = time.time() - t0
        self.store.audit("SELESAI_EKSTRAKSI" if not st.stopped else "EKSTRAKSI_DIHENTIKAN",
                         f"diproses={st.processed} error={st.errors} durasi={st.elapsed:.0f}s")
        return st

    def _extract(self, rec: dict, opts: ExtractOptions, engines: Engines, should_stop, sub):
        path, kind = rec["path"], rec["kind"]
        ext = rec["ext"]
        if rec.get("detected_by") == "signature":
            _k, sext = sniff_kind(path)
            ext = sext or ext
        if kind == "document":
            return extract_document(path, ext, engines, opts.pdf_ocr, should_stop, sub), None
        if kind == "database":
            from .chatparse import extract_database

            segs, dbtype = extract_database(path, self.store.case_dir / fconfig.TMP_DIR, should_stop, sub)
            sub(f"{dbtype}: {len(segs)} pesan/baris teks")
            return segs, None
        if kind == "image":
            sub("OCR foto")
            return extract_image(path, engines), None
        if kind in ("audio", "video"):
            info = probe_media(path)
            dur = info["duration"]
            segs: list[dict] = []
            if (kind == "audio" or opts.video_asr) and info["has_audio"] is not False:
                sub("transkripsi suara")
                try:
                    segs.extend(transcribe(path, engines, dur, should_stop, sub))
                except StopRequested:
                    raise
                except Exception as exc:  # noqa: BLE001
                    if kind == "audio":
                        raise
                    logger.warning("Audio video %s tidak bisa ditranskrip: %s", path, exc)
            if kind == "video" and opts.video_ocr and info["has_video"] is not False:
                sub("OCR frame video")
                segs.extend(extract_video_frames(path, rec["id"], self.store.case_dir, engines,
                                                 opts.frame_interval, dur, should_stop, sub))
            segs.sort(key=lambda s: (s.get("t_start") or 0, s["source"]))
            return segs, dur
        return [], None

    def _write_extract_txt(self, rec: dict, sha: str, md5: str, segs: list[dict]) -> str:
        rel = Path(fconfig.EXTRACT_DIR) / f"{rec['id']:06d}_{_safe_name(rec['name'])}.txt"
        lines = [
            "=== HASIL EKSTRAKSI TEKS (FORENSIK DIGITAL) ===",
            f"File sumber : {rec['path']}",
            f"Jenis       : {fconfig.KIND_LABEL.get(rec['kind'], rec['kind'])} (deteksi: {rec.get('detected_by')})",
            f"Ukuran      : {rec['size']} byte",
            f"SHA-256     : {sha}",
            f"MD5         : {md5}",
            f"Diekstrak   : {now_text()}",
            f"Alat        : {TOOL_NAME} v{TOOL_VERSION} - dibuat oleh {AUTHOR} ({REPO_URL})",
            f"Jumlah segmen teks: {len(segs)}",
            "=" * 60, "",
        ]
        for s in segs:
            src = fconfig.SOURCE_LABEL.get(s["source"], s["source"])
            lines.append(f"[{src} | {s.get('label') or '-'}]")
            lines.append(s["text"])
            if s.get("ref"):
                lines.append(f"(file terkait: {s['ref']})")
            lines.append("")
        (self.store.case_dir / rel).write_text("\n".join(lines), encoding="utf-8")
        return str(rel).replace("\\", "/")

    # ---------------------------------------------------------- verifikasi
    def verify_integrity(self, log: LogCb, progress: ProgressCb, should_stop) -> dict:
        rows = self.store.conn.execute(
            "SELECT id, path, sha256 FROM files WHERE sha256 IS NOT NULL").fetchall()
        res = {"ok": 0, "changed": [], "missing": [], "total": len(rows)}
        for i, (fid, path, sha) in enumerate(rows, 1):
            if should_stop():
                break
            progress(i - 1, len(rows), f"verifikasi hash {Path(path).name}")
            if not os.path.exists(path):
                res["missing"].append(path)
                continue
            try:
                now_sha, _ = hash_file(path, should_stop)
            except StopRequested:
                break
            if now_sha == sha:
                res["ok"] += 1
            else:
                res["changed"].append(path)
                log(f"  [PERINGATAN] Hash berubah: {path}")
        progress(len(rows), len(rows), "verifikasi selesai")
        ok_chain, chain_msg = self.store.verify_audit_chain()
        res["audit_chain"] = chain_msg
        self.store.audit("VERIFIKASI_INTEGRITAS",
                         f"cocok={res['ok']} berubah={len(res['changed'])} hilang={len(res['missing'])} "
                         f"dari={res['total']}; {chain_msg}")
        return res
