"""Uji skala: (1) pipeline nyata pada ribuan file dokumen kecil,
(2) kecepatan pencarian pada ratusan ribu segmen teks (simulasi ribuan
video/audio yang sudah ditranskrip).

    python tests/scale_test.py <folder_kerja> [jumlah_file=3000] [jumlah_segmen=500000]
"""
from __future__ import annotations

import random
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.forensic.pipeline import CaseProcessor, ExtractOptions  # noqa: E402
from app.forensic.search import TextSearcher  # noqa: E402
from app.forensic.store import CaseStore  # noqa: E402
from app.forensic.textnorm import normalize  # noqa: E402

WORDS = ("saya kamu dia kita mereka pergi makan rumah kantor jalan besok kemarin uang transfer "
         "rekening bos siap aman oke tolong kirim barang lokasi jam malam pagi motor mobil hp "
         "nomor alamat ketemu tunggu cepat lambat polisi teman keluarga kerja bayar harga").split()
TARGET = "hay tolong lakukan penyerangan itu"


def sentence(n: int) -> str:
    return " ".join(random.choice(WORDS) for _ in range(n))


def main() -> None:
    root = Path(sys.argv[1])
    n_files = int(sys.argv[2]) if len(sys.argv) > 2 else 3000
    n_segs = int(sys.argv[3]) if len(sys.argv) > 3 else 500000
    random.seed(7)

    # ---------- (1) pipeline nyata: ribuan file
    ev = root / "bukti_banyak"
    if not ev.exists():
        for i in range(n_files):
            d = ev / f"folder_{i // 500:02d}"
            d.mkdir(parents=True, exist_ok=True)
            txt = sentence(80)
            if i in (123, 2500):
                txt += f" {TARGET} " + sentence(10)
            (d / f"chat_{i:05d}.txt").write_text(txt, encoding="utf-8")
    ws = root / "ws_banyak"
    store = CaseStore(ws)
    store.init_workspace(str(ev))
    t0 = time.time()
    st = CaseProcessor(store, str(ev)).run(ExtractOptions(kinds={"document"}), lambda m: None,
                                           lambda d, t, m: None, lambda: False)
    t1 = time.time() - t0
    print(f"[1] {st.processed} file diproses (scan+hash+ekstraksi+simpan) dalam {t1:.1f}s "
          f"= {t1 / max(1, st.processed) * 1000:.1f} ms/file")
    t0 = time.time()
    st2 = CaseProcessor(store, str(ev)).run(ExtractOptions(kinds={"document"}), lambda m: None,
                                            lambda d, t, m: None, lambda: False)
    print(f"    run ulang (incremental, tidak ada yg berubah): {time.time() - t0:.1f}s, diproses={st2.processed}")
    s = TextSearcher(ws)
    hits = s.search(TARGET, "fuzzy", 80)
    print(f"    cari fuzzy -> {len(hits)} temuan: {[h.name for h in hits]}")
    s.close()
    store.close()

    # ---------- (2) skala pencarian: ratusan ribu segmen
    ws2 = root / "ws_segmen"
    if not (ws2 / "case.db").exists():
        st2 = CaseStore(ws2)
        st2.init_workspace("simulasi")
        per_file = 100
        fid_count = n_segs // per_file
        planted = set(random.sample(range(n_segs), 25))
        k = 0
        for f in range(fid_count):
            fid = st2.add_file(dict(path=f"X:/sim/video_{f:05d}.mp4", name=f"video_{f:05d}.mp4", ext=".mp4",
                                    kind="video", size=1, mtime=0, status="done", sha256="0" * 64, md5="0" * 32))
            segs = []
            for j in range(per_file):
                txt = sentence(random.randint(6, 18))
                if k in planted:
                    txt = sentence(3) + " hai to long lakukan penyerangan itu " + sentence(3)
                segs.append({"source": "asr", "text": txt, "norm": normalize(txt), "t_start": j * 4.0,
                             "t_end": j * 4.0 + 4, "label": f"{j * 4}s"})
                k += 1
            st2.add_segments(fid, segs)
            if f % 200 == 0:
                st2.commit()
        st2.commit()
        st2.close()
    s = TextSearcher(ws2)
    t0 = time.time()
    s._load()
    print(f"[2] {len(s._win_text)} jendela teks dimuat ({n_segs} segmen) dalam {time.time() - t0:.1f}s")
    for mode in ("frasa", "semua", "fuzzy", "fuzzy"):
        t0 = time.time()
        hits = s.search(TARGET, mode, 80)
        print(f"    {mode:6s}: {len(hits):3d} temuan dalam {time.time() - t0:.2f}s")
    s.close()


if __name__ == "__main__":
    main()
