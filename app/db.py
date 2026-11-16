"""Lapisan penyimpanan katalog (SQLite).

Menyimpan mapping id <-> path asli, metadata filesystem (dipakai HANYA untuk
incremental indexing / deteksi file berubah -- bukan untuk similarity), dan
perceptual hash. Embedding vector disimpan terpisah di FAISS (lihat
vector_index.py); `id` di tabel ini dipakai juga sebagai id di FAISS
(IndexIDMap) sehingga hasil pencarian FAISS bisa langsung di-join ke sini.
"""
from __future__ import annotations

import sqlite3
import time
from pathlib import Path

SCHEMA = """
CREATE TABLE IF NOT EXISTS images (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    path TEXT UNIQUE NOT NULL,
    size INTEGER NOT NULL,
    mtime REAL NOT NULL,
    width INTEGER,
    height INTEGER,
    phash TEXT,
    dhash TEXT,
    has_embedding INTEGER DEFAULT 0,
    status TEXT DEFAULT 'pending',
    error TEXT,
    indexed_at REAL
);
CREATE INDEX IF NOT EXISTS idx_images_path ON images(path);
CREATE INDEX IF NOT EXISTS idx_images_status ON images(status);

CREATE TABLE IF NOT EXISTS meta (
    key TEXT PRIMARY KEY,
    value TEXT
);
"""


class Catalog:
    def __init__(self, db_path: str | Path):
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        # check_same_thread=False: engine dibuat sekali lalu dipakai kembali
        # dari worker thread GUI yang berbeda-beda (satu operasi pada satu
        # waktu, tidak ada akses paralel), jadi aman untuk kasus pemakaian ini.
        self.conn = sqlite3.connect(str(self.db_path), check_same_thread=False)
        self.conn.execute("PRAGMA journal_mode=WAL;")
        self.conn.executescript(SCHEMA)
        self.conn.commit()

    def close(self) -> None:
        self.conn.close()

    # -- lookups used for incremental indexing -----------------------------
    def get_known_files(self) -> dict[str, tuple[int, float]]:
        """path -> (size, mtime) untuk semua file yang sudah tercatat (status ok/corrupt)."""
        cur = self.conn.execute("SELECT path, size, mtime FROM images")
        return {row[0]: (row[1], row[2]) for row in cur.fetchall()}

    def mark_missing(self, paths: list[str]) -> None:
        if not paths:
            return
        self.conn.executemany(
            "UPDATE images SET status='missing' WHERE path=?", [(p,) for p in paths]
        )
        self.conn.commit()

    # -- insert / update -----------------------------------------------------
    def upsert_pending(self, path: str, size: int, mtime: float) -> int:
        cur = self.conn.execute(
            """
            INSERT INTO images (path, size, mtime, status)
            VALUES (?, ?, ?, 'pending')
            ON CONFLICT(path) DO UPDATE SET size=excluded.size, mtime=excluded.mtime,
                status='pending', has_embedding=0, error=NULL
            """,
            (path, size, mtime),
        )
        if cur.lastrowid:
            return cur.lastrowid
        row = self.conn.execute("SELECT id FROM images WHERE path=?", (path,)).fetchone()
        return row[0]

    def set_success(self, image_id: int, width: int, height: int, phash: str, dhash: str) -> None:
        self.conn.execute(
            """
            UPDATE images
            SET width=?, height=?, phash=?, dhash=?, has_embedding=1,
                status='ok', error=NULL, indexed_at=?
            WHERE id=?
            """,
            (width, height, phash, dhash, time.time(), image_id),
        )

    def set_error(self, image_id: int, error: str) -> None:
        self.conn.execute(
            "UPDATE images SET status='corrupt', error=?, indexed_at=? WHERE id=?",
            (error, time.time(), image_id),
        )

    def commit(self) -> None:
        self.conn.commit()

    # -- reads for search -----------------------------------------------------
    def fetch_all_hashes(self) -> list[tuple[int, str, str]]:
        cur = self.conn.execute(
            "SELECT id, phash, dhash FROM images WHERE status='ok' AND phash IS NOT NULL"
        )
        return cur.fetchall()

    def fetch_rows(self, ids: list[int]) -> dict[int, sqlite3.Row]:
        if not ids:
            return {}
        self.conn.row_factory = sqlite3.Row
        placeholders = ",".join("?" for _ in ids)
        cur = self.conn.execute(
            f"SELECT * FROM images WHERE id IN ({placeholders})", ids
        )
        rows = {row["id"]: row for row in cur.fetchall()}
        self.conn.row_factory = None
        return rows

    def count_ok(self) -> int:
        return self.conn.execute("SELECT COUNT(*) FROM images WHERE status='ok'").fetchone()[0]

    def count_total(self) -> int:
        return self.conn.execute("SELECT COUNT(*) FROM images").fetchone()[0]

    # -- meta kv ---------------------------------------------------------------
    def set_meta(self, key: str, value: str) -> None:
        self.conn.execute(
            "INSERT INTO meta (key, value) VALUES (?, ?) "
            "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
            (key, value),
        )
        self.conn.commit()

    def get_meta(self, key: str, default: str | None = None) -> str | None:
        row = self.conn.execute("SELECT value FROM meta WHERE key=?", (key,)).fetchone()
        return row[0] if row else default
