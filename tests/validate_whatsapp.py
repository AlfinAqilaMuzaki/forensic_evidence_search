"""Validasi modul chat/database WhatsApp.

    python tests/validate_whatsapp.py <folder_bukti_wa> <folder_hasil> [base|small]
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.forensic.pipeline import CaseProcessor, ExtractOptions  # noqa: E402
from app.forensic.report import secure_hits  # noqa: E402
from app.forensic.search import TextSearcher  # noqa: E402
from app.forensic.store import CaseStore  # noqa: E402

Q = "tolong lakukan penyerangan itu"


def snapshot(ev: str) -> dict:
    return {str(p): (p.stat().st_size, p.stat().st_mtime) for p in Path(ev).rglob("*") if p.is_file()}


def main() -> int:
    ev, ws = sys.argv[1], sys.argv[2]
    model = sys.argv[3] if len(sys.argv) > 3 else "base"
    before = snapshot(ev)
    store = CaseStore(ws)
    store.init_workspace(ev)
    st = CaseProcessor(store, ev).run(ExtractOptions(whisper_model=model), lambda m: None,
                                      lambda a, b, c: None, lambda: False)
    print(f"diproses={st.processed} error={st.errors}")
    rows = {r[0]: r for r in store.conn.execute("SELECT name, kind, status, n_segments, error FROM files")}
    for r in rows.values():
        print(f"  {r[2]:11s} {r[1]:9s} segmen={r[3]:<3} {r[0]}  {(r[4] or '')[:70]}")

    hits = TextSearcher(ws).search(Q, "fuzzy", 80)
    print(f"\n{len(hits)} temuan:")
    for h in hits:
        extra = f" | terkait={h.ref} ({'ada' if h.ref_path else 'tidak ada'})" if h.ref else (
            f" | {h.context}" if h.context else "")
        print(f"  {h.score:5.1f} {h.name:42s} {h.source_label:26s} {h.label[:60]}{extra}")

    names = {h.name for h in hits}
    checks = {
        "export Android dipecah per pesan + jam/pengirim":
            any(h.name == "WhatsApp Chat dengan Budi.txt" and h.source == "chat_export" and "21.02" in h.label
                and "Andi" in h.label for h in hits),
        "pesan multi-baris tergabung":
            any(h.source == "chat_export" and "besok malam" in h.text for h in hits),
        "export iPhone": any(h.name == "_chat.txt" and h.source == "chat_export" for h in hits),
        "msgstore.db (skema baru) + pengirim 'Saya'":
            any(h.name == "msgstore.db" and h.source == "wa_db" and "Saya" in h.text for h in hits),
        "nama kontak dari wa.db": any("Budi Kontak" in (h.label or "") for h in hits if h.name == "msgstore.db"),
        "msgstore skema lama": "msgstore_lama.db" in names,
        "iPhone ChatStorage.sqlite": "ChatStorage.sqlite" in names,
        "SQLite umum": "catatan.sqlite" in names,
        "isi file -wal ikut terbaca": "catatan_wal.db" in names,
        "voice note .opus ditranskrip": "PTT-20261112-WA0003.opus" in names,
        "voice note dihubungkan ke chat":
            any(h.name == "PTT-20261112-WA0003.opus" and h.context and "Chat:" in h.context for h in hits),
        "crypt15 diberi keterangan terenkripsi":
            rows.get("msgstore-2026-11-12.1.db.crypt15", (0, 0, "", 0, ""))[2] == "error"
            and "TERENKRIPSI" in (rows["msgstore-2026-11-12.1.db.crypt15"][4] or ""),
    }
    # file media terkait pesan (gambar dari msgstore) dapat ditemukan
    store_hits = TextSearcher(ws).search("foto lokasi target", "fuzzy", 80)
    checks["pesan media -> file terkait ditemukan"] = any(
        h.name == "msgstore.db" and h.ref and h.ref_path for h in store_hits)

    out = secure_hits(store, hits, Q, "fuzzy", True)
    checks["paket bukti + PDF dibuat"] = (out / "laporan.html").exists()
    after = snapshot(ev)
    checks["folder bukti tidak berubah (tanpa -shm/-wal baru)"] = before == after

    print()
    ok = True
    for k, v in checks.items():
        print(f"  [{'OK' if v else 'GAGAL'}] {k}")
        ok &= bool(v)
    print("\nHASIL:", "LULUS" if ok else "GAGAL")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
