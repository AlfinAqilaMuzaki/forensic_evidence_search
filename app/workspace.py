"""Lokasi data kerja otomatis per folder barang bukti.

Tidak ada konsep "folder kasus": cukup pilih folder bukti, dan semua hasil
(teks ekstraksi, hash, audit log, index foto, bukti diamankan) disimpan di
DATA_ANALISIS/<nama-folder>_<hash-path>/ di samping aplikasi -- TIDAK PERNAH
di dalam folder bukti dan tidak di drive C:.
"""
from __future__ import annotations

import hashlib
import sys
from pathlib import Path


def app_dir() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent.parent


def _writable(d: Path) -> bool:
    try:
        d.mkdir(parents=True, exist_ok=True)
        probe = d / ".tulis_test"
        probe.write_text("ok", encoding="utf-8")
        probe.unlink()
        return True
    except OSError:
        return False


def _data_root() -> Path:
    """DATA_ANALISIS di samping aplikasi; bila folder aplikasi tidak bisa ditulis
    (mis. terinstal di Program Files), pakai Documents pengguna."""
    primary = app_dir() / "DATA_ANALISIS"
    if _writable(primary):
        return primary
    fallback = Path.home() / "Documents" / "CyberForensicEvidenceSearch" / "DATA_ANALISIS"
    fallback.mkdir(parents=True, exist_ok=True)
    return fallback


DATA_ROOT = _data_root()


def workspace_for(evidence_dir: str | Path) -> Path:
    ev = Path(evidence_dir).resolve()
    digest = hashlib.sha1(str(ev).lower().encode("utf-8")).hexdigest()[:12]
    name = "".join(c if c.isalnum() or c in "-_" else "_" for c in (ev.name or "root"))[:40]
    return DATA_ROOT / f"{name}_{digest}"


def is_inside(child: Path, parent: Path) -> bool:
    child, parent = child.resolve(), parent.resolve()
    return child == parent or parent in child.parents


def validate_evidence_dir(evidence_dir: str | Path) -> str | None:
    """Kembalikan pesan error bila folder tidak aman dipakai, None bila aman."""
    ev = Path(evidence_dir)
    if not ev.is_dir():
        return "Folder bukti tidak ditemukan."
    if is_inside(DATA_ROOT, ev):
        return ("Folder bukti berisi folder aplikasi ini. Pindahkan aplikasi ke luar folder bukti "
                "supaya tidak ada data yang tertulis ke dalam folder bukti.")
    if is_inside(ev, DATA_ROOT):
        return "Folder yang dipilih adalah folder data hasil analisis, bukan folder bukti."
    return None
