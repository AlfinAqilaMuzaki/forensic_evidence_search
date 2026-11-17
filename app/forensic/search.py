"""Pencarian kalimat di seluruh teks hasil ekstraksi (dokumen, OCR, transkrip).

Mode:
- "frasa"  : frasa persis (setelah normalisasi huruf kecil/tanpa tanda baca)
- "semua"  : semua kata ada di segmen yang sama (urutan bebas)
- "fuzzy"  : toleran salah OCR/transkripsi (mis. "hay" vs "hai"), skor 0-100

Untuk transkrip suara & OCR video, kalimat bisa terpotong di dua segmen
berurutan, jadi pencarian juga mengecek gabungan segmen i + i+1.
"""
from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

import numpy as np
from rapidfuzz import fuzz, process

from . import fconfig
from .textnorm import normalize, normalize_with_map

_TIMED = {"asr", "vid_ocr"}


@dataclass
class Hit:
    file_id: int
    seg_ids: list[int]
    score: float
    path: str
    name: str
    kind: str
    source: str
    label: str
    t_start: Optional[float]
    t_end: Optional[float]
    page: Optional[int]
    text: str
    sha256: str
    md5: str
    frame_path: Optional[str]
    match_span: Optional[tuple[int, int]]  # posisi kecocokan di `text`
    ref: Optional[str] = None        # file media yang dirujuk pesan chat (mis. voice note)
    ref_path: Optional[str] = None   # path file media tsb di folder bukti (bila ditemukan)
    context: Optional[str] = None    # untuk file media: pesan chat tempat file ini dikirim

    @property
    def source_label(self) -> str:
        return fconfig.SOURCE_LABEL.get(self.source, self.source)

    @property
    def kind_label(self) -> str:
        return fconfig.KIND_LABEL.get(self.kind, self.kind)


class TextSearcher:
    def __init__(self, case_dir: str | Path):
        self.case_dir = Path(case_dir)
        self.conn = sqlite3.connect(str(self.case_dir / fconfig.CASE_DB), check_same_thread=False, timeout=30)
        self._version = None
        self._win_text: list[str] = []
        self._win_ids: list[tuple[int, ...]] = []
        self._win_file: list[int] = []
        self._win_nospace: Optional[list[str]] = None
        self._kinds: dict[int, str] = {}

    def close(self) -> None:
        self.conn.close()

    def _load(self) -> None:
        ver = self.conn.execute("SELECT COUNT(*), COALESCE(MAX(id),0) FROM segments").fetchone()
        if ver == self._version:
            return
        rows = self.conn.execute(
            "SELECT s.id, s.file_id, s.source, s.norm FROM segments s ORDER BY s.file_id, s.seq").fetchall()
        self._kinds = dict(self.conn.execute("SELECT id, kind FROM files").fetchall())
        texts, ids, files = [], [], []
        prev = None
        for sid, fid, src, norm in rows:
            texts.append(norm)
            ids.append((sid,))
            files.append(fid)
            if prev and prev[1] == fid and prev[2] == src and src in _TIMED:
                texts.append(prev[3] + " " + norm)
                ids.append((prev[0], sid))
                files.append(fid)
            prev = (sid, fid, src, norm)
        self._win_text, self._win_ids, self._win_file = texts, ids, files
        self._win_nospace = None
        self._version = ver

    def search(self, query: str, mode: str = "fuzzy", threshold: float = 80,
               kinds: Optional[set] = None, limit: int = 5000) -> list[Hit]:
        q = normalize(query)
        if not q:
            return []
        self._load()
        cand: list[tuple[int, float]] = []  # (window index, score)
        if mode == "frasa":
            pat = f" {q} "
            for i, t in enumerate(self._win_text):
                if pat in f" {t} ":
                    cand.append((i, 100.0))
        elif mode == "semua":
            words = set(q.split())
            for i, t in enumerate(self._win_text):
                tw = set(t.split())
                if words <= tw:
                    cand.append((i, 100.0))
        else:
            qlen = len(q)
            if not self._win_text:
                return []
            if self._win_nospace is None:
                self._win_nospace = [t.replace(" ", "") for t in self._win_text]
            qn = q.replace(" ", "")
            # skor 1: per kata; skor 2: tanpa spasi (transkrip suara sering
            # memecah/menggabung kata, mis. "to long" = "tolong")
            s1 = process.cdist([q], self._win_text, scorer=fuzz.partial_ratio,
                               score_cutoff=threshold, workers=-1, dtype=np.float32)[0]
            s2 = process.cdist([qn], self._win_nospace, scorer=fuzz.partial_ratio,
                               score_cutoff=threshold, workers=-1, dtype=np.float32)[0]
            scores = np.maximum(s1, s2)
            for i in np.nonzero(scores >= threshold)[0].tolist():
                score = float(scores[i])
                t = self._win_text[i]
                if len(t) < qlen * 0.8:
                    # segmen lebih pendek dari kalimat yg dicari: partial_ratio
                    # akan "memaafkan" -> pakai ratio penuh supaya tidak false positive
                    score = max(fuzz.ratio(q, t), fuzz.ratio(qn, self._win_nospace[i]))
                    if score < threshold:
                        continue
                cand.append((i, float(score)))

        if kinds:
            cand = [c for c in cand if self._kinds.get(self._win_file[c[0]]) in kinds]

        # urut skor tertinggi, buang hasil yang tumpang tindih (segmen sama)
        cand.sort(key=lambda c: (-c[1], len(self._win_ids[c[0]])))
        used: set[int] = set()
        picked: list[tuple[tuple[int, ...], float]] = []
        for i, score in cand:
            sids = self._win_ids[i]
            if any(s in used for s in sids):
                continue
            used.update(sids)
            picked.append((sids, score))
            if len(picked) >= limit:
                break
        return self._materialize(picked, q, mode)

    def _materialize(self, picked, q: str, mode: str) -> list[Hit]:
        if not picked:
            return []
        all_ids = sorted({s for sids, _ in picked for s in sids})
        segs = {}
        for chunk_start in range(0, len(all_ids), 900):
            chunk = all_ids[chunk_start:chunk_start + 900]
            qs = ",".join("?" * len(chunk))
            for r in self.conn.execute(
                    f"SELECT id, file_id, source, t_start, t_end, page, label, text, frame_path, ref "
                    f"FROM segments WHERE id IN ({qs})", chunk):
                segs[r[0]] = r
        fids = sorted({segs[sids[0]][1] for sids, _ in picked})
        files = {}
        for chunk_start in range(0, len(fids), 900):
            chunk = fids[chunk_start:chunk_start + 900]
            qs = ",".join("?" * len(chunk))
            for r in self.conn.execute(
                    f"SELECT id, path, name, kind, sha256, md5 FROM files WHERE id IN ({qs})", chunk):
                files[r[0]] = r
        hits = []
        for sids, score in picked:
            rows = [segs[s] for s in sids]
            first, last = rows[0], rows[-1]
            f = files[first[1]]
            text = " ".join(r[7] for r in rows)
            t_start, t_end = first[3], last[4]
            label = first[6] if len(rows) == 1 else f"{first[6].split(' - ')[0]} - {last[6].split(' - ')[-1]}"
            hits.append(Hit(
                file_id=f[0], seg_ids=list(sids), score=score, path=f[1], name=f[2], kind=f[3],
                source=first[2], label=label or "-", t_start=t_start, t_end=t_end, page=first[5],
                text=text, sha256=f[4] or "", md5=f[5] or "",
                frame_path=next((r[8] for r in rows if r[8]), None),
                ref=next((r[9] for r in rows if r[9]), None),
                match_span=locate(q, text, mode),
            ))
        self._link_chat_media(hits)
        hits.sort(key=lambda h: (-h.score, h.path, h.t_start or 0, h.page or 0))
        return hits

    def _link_chat_media(self, hits: list[Hit]) -> None:
        """Hubungkan pesan chat <-> file media (voice note/foto/video) yang dikirim di chat itu."""
        refs = {Path(h.ref.replace("\\", "/")).name.lower() for h in hits if h.ref}
        media_names = {h.name.lower() for h in hits if h.kind in ("audio", "image", "video")}
        if not refs and not media_names:
            return
        by_name: dict[str, str] = {}
        if refs:
            for path, name in self.conn.execute("SELECT path, name FROM files"):
                if name and name.lower() in refs:
                    by_name.setdefault(name.lower(), path)
        ctx: dict[str, str] = {}
        if media_names:
            for label, text, ref in self.conn.execute(
                    "SELECT label, text, ref FROM segments WHERE ref IS NOT NULL "
                    "AND source IN ('wa_db','chat_export')"):
                nm = Path(ref.replace("\\", "/")).name.lower()
                if nm in media_names and nm not in ctx:
                    ctx[nm] = f"Dikirim di chat: {label}"
        for h in hits:
            if h.ref:
                h.ref_path = by_name.get(Path(h.ref.replace("\\", "/")).name.lower())
            if h.kind in ("audio", "image", "video"):
                h.context = ctx.get(h.name.lower())


def locate(q_norm: str, text: str, mode: str) -> Optional[tuple[int, int]]:
    """Posisi (awal, akhir) kecocokan dalam teks asli, untuk highlight."""
    norm, mp = normalize_with_map(text)
    if not norm or not mp:
        return None
    if mode == "semua":
        w = q_norm.split()[0]
        k = f" {norm} ".find(f" {w} ")
        if k < 0:
            return None
        s, e = k, k + len(w)
    else:
        k = norm.find(q_norm)
        if k >= 0:
            s, e = k, k + len(q_norm)
        else:
            al = fuzz.partial_ratio_alignment(q_norm, norm)
            if al is None:
                return None
            s, e = (al.dest_start, al.dest_end) if len(norm) >= len(q_norm) else (0, len(norm))
    s = max(0, min(s, len(mp) - 1))
    e = max(s + 1, min(e, len(mp)))
    return mp[s], mp[e - 1] + 1
