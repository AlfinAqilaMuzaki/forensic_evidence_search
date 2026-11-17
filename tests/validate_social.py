"""Validasi pembaca media sosial & aplikasi pesan.

    python tests/validate_social.py <folder_bukti_sosmed> <folder_hasil>
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.forensic.pipeline import CaseProcessor, ExtractOptions  # noqa: E402
from app.forensic.search import TextSearcher  # noqa: E402
from app.forensic.store import CaseStore  # noqa: E402

Q = "tolong lakukan penyerangan itu"

# (nama file, sumber yang diharapkan, potongan label yang diharapkan)
EXPECT = [
    ("message_1.json", "facebook", "Chat: Budi Santoso"),
    ("message_1.json", "instagram", "Chat: andi.ig"),
    ("threads_and_replies.json", "threads", "Threads"),
    ("post_comments_1.json", "instagram", "Instagram"),
    ("budi_santoso.json", "messenger", "Dari: Budi Santoso"),
    ("result.json", "telegram", "Chat: Rudi Telegram"),
    ("messages.html", "telegram", "Chat: Grup Rencana"),
    ("tweets.js", "twitter", "tweet"),
    ("direct-messages.js", "twitter", "DM"),
    ("messages.json", "discord", "Server Rahasia #rencana"),
    ("messages.csv", "discord", "Chat: DM"),
    ("Server Rahasia - general [123].json", "discord", "Dari: Andi"),
    ("user_data_tiktok.json", "tiktok", "Dari: budi_tt"),
    ("chat_history.json", "snapchat", "Dari: sari_snap"),
    ("messages.json", "skype", "Rudi Skype"),
    ("messages.json", "gchat", "Dari: Dewi"),
    ("messages.csv", "linkedin", "Dari: Rina"),
    ("sms-20261112.xml", "sms", "Dari: Joko"),
    ("cache4.db", "telegram", "rudi tele"),
    ("threads_db2", "messenger", "Dari: Budi FB"),
    ("direct.db", "instagram", "Chat: andi.ig"),
    ("naver_line", "line", "Dari: Tono LINE"),
    ("mmssms.db", "sms", "+6281300000001"),
    ("cache.db", "db_text", "Discord"),
    ("sms.db", "imessage", "+6281400000002"),
]


def main() -> int:
    ev, ws = sys.argv[1], sys.argv[2]
    before = {str(p): (p.stat().st_size, p.stat().st_mtime) for p in Path(ev).rglob("*") if p.is_file()}
    store = CaseStore(ws)
    store.init_workspace(ev)
    st = CaseProcessor(store, ev).run(ExtractOptions(kinds={"document", "database"}), lambda m: None,
                                      lambda a, b, c: None, lambda: False)
    print(f"diproses={st.processed} error={st.errors}")
    files = list(store.conn.execute("SELECT name, kind, status, ext_mismatch, error, path FROM files"))
    hits = TextSearcher(ws).search(Q, "fuzzy", 75)
    print(f"{len(hits)} temuan")
    for h in sorted(hits, key=lambda x: x.source):
        print(f"  {h.score:5.1f} {h.source:10s} {h.name:38s} {h.label[:85]}")

    ok = True
    print()
    for name, src, lab in EXPECT:
        found = any(h.name == name and h.source == src and lab.lower() in h.label.lower() for h in hits)
        ok &= found
        print(f"  [{'OK' if found else 'GAGAL'}] {src:10s} {name}  ({lab})")

    def check(desc, cond):
        nonlocal ok
        ok &= bool(cond)
        print(f"  [{'OK' if cond else 'GAGAL'}] {desc}")
    check("encoding Meta diperbaiki (emoji tampil benar)", any("😡" in h.text for h in hits))
    sig = [f for f in files if f[0] == "signal.db"]
    check("Signal (SQLCipher) ditandai terenkripsi", sig and sig[0][2] == "error" and "TERENKRIPSI" in (sig[0][4] or ""))
    check("tidak ada file salah ditandai DISAMARKAN", not [f[0] for f in files if f[3]])
    check("pengecoh tidak jadi temuan", not any(h.name in ("package.json", "produk.csv") for h in hits))
    check("folder bukti tidak berubah",
          before == {str(p): (p.stat().st_size, p.stat().st_mtime) for p in Path(ev).rglob("*") if p.is_file()})
    print("\nHASIL:", "LULUS" if ok else "GAGAL")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
