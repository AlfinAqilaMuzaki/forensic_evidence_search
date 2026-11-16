"""Validasi end-to-end modul forensik teks (tanpa GUI).

    python tests/validate_forensic.py <folder_bukti> <folder_kasus> [base|small]
"""
from __future__ import annotations

import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.forensic.pipeline import CaseProcessor, ExtractOptions  # noqa: E402
from app.forensic.report import secure_hits  # noqa: E402
from app.forensic.search import TextSearcher  # noqa: E402
from app.forensic.store import CaseStore  # noqa: E402

EXPECT = {"notulen.docx", "laporan.pdf", "scan_surat.pdf", "chat_export.txt", "rekap.xlsx",
          "screenshot_chat.png", "IMG_0001.dat", "PTT-20260312.mp3", "VID_20260312.mp4"}
NOT_EXPECT = {"resep.txt", "kartu.png", "pemandangan.jpg", "distraktor.mp4", "salam.wav"}


def main() -> int:
    ev, case = sys.argv[1], sys.argv[2]
    model = sys.argv[3] if len(sys.argv) > 3 else "base"
    before = {p: p.stat().st_mtime for p in Path(ev).rglob("*") if p.is_file()}

    store = CaseStore(case)
    store.init_workspace(ev)
    proc = CaseProcessor(store, ev)
    t0 = time.time()
    st = proc.run(ExtractOptions(whisper_model=model), print,
                  lambda d, t, m: None, lambda: False)
    print(f"\nEkstraksi: diproses={st.processed} error={st.errors} waktu={time.time() - t0:.0f}s")
    for r in store.conn.execute("SELECT name, kind, detected_by, status, n_segments, error FROM files"):
        print("  ", r)

    s = TextSearcher(case)
    q = "hay tolong lakukan penyerangan itu"
    ok = True
    for mode in ("fuzzy", "frasa", "semua"):
        hits = s.search(q, mode=mode, threshold=80)
        names = {h.name for h in hits}
        print(f"\n[{mode}] {len(hits)} temuan di {len(names)} file")
        for h in hits:
            print(f"   {h.score:5.1f} {h.name:22s} {h.source_label:18s} {h.label:28s} | "
                  f"{h.text[h.match_span[0]:h.match_span[1]] if h.match_span else ''!r}")
        if mode == "fuzzy":
            miss = EXPECT - names
            fp = names & NOT_EXPECT
            print(f"   TIDAK DITEMUKAN: {sorted(miss) or '-'}   FALSE POSITIVE: {sorted(fp) or '-'}")
            ok = ok and not fp and len(miss) <= 1
            out = secure_hits(store, hits, q, mode, True, print)
            print("   paket bukti:", out, sorted(p.name for p in out.iterdir()))

    res = proc.verify_integrity(print, lambda d, t, m: None, lambda: False)
    print("\nVerifikasi:", {k: (v if not isinstance(v, list) else len(v)) for k, v in res.items()})
    after = {p: p.stat().st_mtime for p in Path(ev).rglob("*") if p.is_file()}
    untouched = before == after
    print("Folder bukti tidak berubah:", untouched)
    ok = ok and untouched and not res["changed"]
    print("\nHASIL:", "LULUS" if ok else "GAGAL")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
