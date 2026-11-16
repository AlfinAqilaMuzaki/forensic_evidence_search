"""Penyimpanan kasus forensik (SQLite) + audit log berantai hash.

Semua yang ditulis aplikasi ada di FOLDER KASUS, tidak pernah di folder
barang bukti. Audit log ditulis ke DB dan ke `audit_log.txt`; setiap entri
memuat SHA-256(entri sebelumnya + entri ini) sehingga penghapusan/perubahan
satu baris log akan terdeteksi (tamper-evident).
"""
from __future__ import annotations

import getpass
import hashlib
import json
import platform
import sqlite3
import threading
import time
from pathlib import Path

from . import TOOL_NAME, TOOL_VERSION, fconfig

SCHEMA = """
CREATE TABLE IF NOT EXISTS case_info (key TEXT PRIMARY KEY, value TEXT);

CREATE TABLE IF NOT EXISTS files (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    path TEXT UNIQUE NOT NULL,
    rel_path TEXT,
    name TEXT,
    ext TEXT,
    kind TEXT,                 -- document / image / audio / video / other
    detected_by TEXT,          -- 'ekstensi' atau 'signature'
    ext_mismatch INTEGER DEFAULT 0,
    size INTEGER,
    mtime REAL,
    ctime REAL,
    sha256 TEXT,
    md5 TEXT,
    hashed_at REAL,
    status TEXT DEFAULT 'pending',   -- pending/processing/done/error/crash/unsupported/missing
    error TEXT,
    n_segments INTEGER DEFAULT 0,
    n_chars INTEGER DEFAULT 0,
    duration REAL,
    processed_at REAL,
    extract_txt TEXT,
    options TEXT
);
CREATE INDEX IF NOT EXISTS idx_files_status ON files(status);
CREATE INDEX IF NOT EXISTS idx_files_kind ON files(kind);

CREATE TABLE IF NOT EXISTS segments (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    file_id INTEGER NOT NULL,
    seq INTEGER NOT NULL,
    source TEXT NOT NULL,      -- doc / doc_ocr / img_ocr / asr / vid_ocr
    t_start REAL,              -- detik (audio/video)
    t_end REAL,
    page INTEGER,              -- halaman / slide / potongan
    label TEXT,                -- keterangan lokasi yg mudah dibaca
    text TEXT NOT NULL,
    norm TEXT NOT NULL,
    conf REAL,
    frame_path TEXT            -- cuplikan frame (video) relatif thd folder kasus
);
CREATE INDEX IF NOT EXISTS idx_seg_file ON segments(file_id, seq);

CREATE TABLE IF NOT EXISTS audit (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ts REAL,
    ts_text TEXT,
    examiner TEXT,
    action TEXT,
    detail TEXT,
    prev_hash TEXT,
    entry_hash TEXT
);
"""


def operator_name() -> str:
    try:
        return f"{getpass.getuser()}@{platform.node()}"
    except Exception:  # noqa: BLE001
        return "unknown"


def now_text(ts: float | None = None) -> str:
    return time.strftime("%Y-%m-%d %H:%M:%S %z", time.localtime(ts or time.time()))


class CaseStore:
    def __init__(self, case_dir: str | Path):
        self.case_dir = Path(case_dir)
        self.case_dir.mkdir(parents=True, exist_ok=True)
        for sub in (fconfig.EXTRACT_DIR, fconfig.FRAME_DIR, fconfig.SECURED_DIR, fconfig.TMP_DIR):
            (self.case_dir / sub).mkdir(exist_ok=True)
        self.db_path = self.case_dir / fconfig.CASE_DB
        self.conn = sqlite3.connect(str(self.db_path), check_same_thread=False, timeout=30)
        self.conn.execute("PRAGMA journal_mode=WAL;")
        self.conn.execute("PRAGMA synchronous=NORMAL;")
        self.conn.executescript(SCHEMA)
        self.conn.commit()
        self._lock = threading.RLock()

    def close(self) -> None:
        try:
            self.conn.close()
        except Exception:  # noqa: BLE001
            pass

    # ------------------------------------------------------------------ info
    def set_info(self, key: str, value: str) -> None:
        with self._lock:
            self.conn.execute(
                "INSERT INTO case_info(key,value) VALUES(?,?) "
                "ON CONFLICT(key) DO UPDATE SET value=excluded.value", (key, value))
            self.conn.commit()

    def get_info(self, key: str, default: str = "") -> str:
        row = self.conn.execute("SELECT value FROM case_info WHERE key=?", (key,)).fetchone()
        return row[0] if row else default

    def all_info(self) -> dict[str, str]:
        return dict(self.conn.execute("SELECT key, value FROM case_info").fetchall())

    def init_workspace(self, evidence_dir: str) -> None:
        """Catat identitas sesi (otomatis, tanpa input manual)."""
        first = not self.get_info("created_at")
        if first:
            self.set_info("created_at", now_text())
        self.set_info("tool", f"{TOOL_NAME} v{TOOL_VERSION}")
        self.set_info("host", f"{platform.node()} / {platform.platform()}")
        self.set_info("operator", operator_name())
        self.set_info("evidence_dir", evidence_dir)
        self.audit("BUAT_WORKSPACE" if first else "BUKA_WORKSPACE",
                   json.dumps({"folder_bukti": evidence_dir, "komputer": platform.node()}, ensure_ascii=False))

    # ----------------------------------------------------------------- audit
    def audit(self, action: str, detail: str = "") -> None:
        with self._lock:
            row = self.conn.execute("SELECT entry_hash FROM audit ORDER BY id DESC LIMIT 1").fetchone()
            prev = row[0] if row else "0" * 64
            ts = time.time()
            ts_text = now_text(ts)
            examiner = operator_name()
            payload = f"{prev}|{ts_text}|{examiner}|{action}|{detail}"
            entry_hash = hashlib.sha256(payload.encode("utf-8")).hexdigest()
            self.conn.execute(
                "INSERT INTO audit(ts, ts_text, examiner, action, detail, prev_hash, entry_hash) "
                "VALUES(?,?,?,?,?,?,?)", (ts, ts_text, examiner, action, detail, prev, entry_hash))
            self.conn.commit()
            with open(self.case_dir / fconfig.AUDIT_TXT, "a", encoding="utf-8") as fh:
                fh.write(f"[{ts_text}] [{examiner}] {action} | {detail} | prev={prev[:16]} hash={entry_hash}\n")

    def verify_audit_chain(self) -> tuple[bool, str]:
        prev = "0" * 64
        rows = self.conn.execute(
            "SELECT id, ts_text, examiner, action, detail, prev_hash, entry_hash FROM audit ORDER BY id").fetchall()
        for rid, ts_text, examiner, action, detail, prev_hash, entry_hash in rows:
            if prev_hash != prev:
                return False, f"Rantai putus di entri #{rid}"
            calc = hashlib.sha256(f"{prev}|{ts_text}|{examiner}|{action}|{detail}".encode("utf-8")).hexdigest()
            if calc != entry_hash:
                return False, f"Entri audit #{rid} telah diubah"
            prev = entry_hash
        return True, f"Rantai audit utuh ({len(rows)} entri)"

    # ----------------------------------------------------------------- files
    def known_files(self) -> dict[str, tuple[int, int, float, str]]:
        cur = self.conn.execute("SELECT path, id, size, mtime, status FROM files")
        return {r[0]: (r[1], r[2], r[3], r[4]) for r in cur.fetchall()}

    def add_file(self, rec: dict) -> int:
        with self._lock:
            cols = ",".join(rec.keys())
            qs = ",".join("?" for _ in rec)
            cur = self.conn.execute(f"INSERT INTO files ({cols}) VALUES ({qs})", list(rec.values()))
            return cur.lastrowid

    def update_file(self, file_id: int, **fields) -> None:
        with self._lock:
            sets = ",".join(f"{k}=?" for k in fields)
            self.conn.execute(f"UPDATE files SET {sets} WHERE id=?", [*fields.values(), file_id])

    def commit(self) -> None:
        with self._lock:
            self.conn.commit()

    def get_file(self, file_id: int) -> dict | None:
        self.conn.row_factory = sqlite3.Row
        try:
            row = self.conn.execute("SELECT * FROM files WHERE id=?", (file_id,)).fetchone()
            return dict(row) if row else None
        finally:
            self.conn.row_factory = None

    def files_to_process(self, kinds: set[str]) -> list[dict]:
        self.conn.row_factory = sqlite3.Row
        try:
            rows = self.conn.execute(
                "SELECT * FROM files WHERE status='pending'").fetchall()
        finally:
            self.conn.row_factory = None
        out = [dict(r) for r in rows if r["kind"] in kinds]
        out.sort(key=lambda r: (fconfig.KIND_ORDER.get(r["kind"], 9), r["size"] or 0))
        return out

    def reset_crashed(self) -> int:
        with self._lock:
            cur = self.conn.execute(
                "UPDATE files SET status='crash', error='Proses terhenti mendadak (aplikasi tertutup/crash) "
                "saat memproses file ini' WHERE status='processing'")
            self.conn.commit()
            return cur.rowcount

    def requeue_failed(self) -> int:
        with self._lock:
            cur = self.conn.execute(
                "UPDATE files SET status='pending', error=NULL WHERE status IN ('error','crash')")
            self.conn.commit()
            return cur.rowcount

    def delete_segments(self, file_id: int) -> None:
        with self._lock:
            self.conn.execute("DELETE FROM segments WHERE file_id=?", (file_id,))

    def add_segments(self, file_id: int, segs: list[dict]) -> None:
        with self._lock:
            self.conn.executemany(
                "INSERT INTO segments(file_id, seq, source, t_start, t_end, page, label, text, norm, conf, frame_path) "
                "VALUES(?,?,?,?,?,?,?,?,?,?,?)",
                [(file_id, i, s["source"], s.get("t_start"), s.get("t_end"), s.get("page"),
                  s.get("label"), s["text"], s["norm"], s.get("conf"), s.get("frame_path"))
                 for i, s in enumerate(segs)])

    def segments_of(self, file_id: int) -> list[dict]:
        self.conn.row_factory = sqlite3.Row
        try:
            rows = self.conn.execute(
                "SELECT * FROM segments WHERE file_id=? ORDER BY seq", (file_id,)).fetchall()
            return [dict(r) for r in rows]
        finally:
            self.conn.row_factory = None

    def stats(self) -> dict:
        out = {"total": 0, "by_status": {}, "by_kind": {}, "segments": 0}
        for st, n in self.conn.execute("SELECT status, COUNT(*) FROM files GROUP BY status"):
            out["by_status"][st] = n
            out["total"] += n
        for k, n in self.conn.execute("SELECT kind, COUNT(*) FROM files GROUP BY kind"):
            out["by_kind"][k] = n
        out["segments"] = self.conn.execute("SELECT COUNT(*) FROM segments").fetchone()[0]
        return out

    def data_version(self) -> tuple[int, int]:
        r = self.conn.execute("SELECT COUNT(*), COALESCE(MAX(id),0) FROM segments").fetchone()
        return int(r[0]), int(r[1])
