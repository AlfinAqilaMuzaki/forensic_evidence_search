"""Pembaca chat: export chat WhatsApp (.txt) dan database chat (SQLite).

Didukung:
- Export chat WhatsApp (fitur "Ekspor chat") format Android & iPhone,
  dipecah per pesan: tanggal/jam + pengirim + isi + lampiran.
- WhatsApp Android  `msgstore.db` (sudah didekripsi) - skema baru (tabel
  message/chat/jid, 2021+) dan skema lama (tabel messages). Nama kontak
  diambil dari `wa.db` di folder yang sama bila ada.
- WhatsApp iPhone   `ChatStorage.sqlite` (ZWAMESSAGE / ZWACHATSESSION).
- Database SQLite lain (Telegram, LINE, browser, aplikasi apa pun): semua
  kolom teks per baris tabel (dengan batas ukuran).

KEAMANAN BUKTI: database TIDAK pernah dibuka langsung dari folder bukti.
File .db beserta -wal/-shm/-journal disalin ke folder sementara workspace,
salinan itulah yang dibuka (SQLite bisa menulis file -shm/-wal saat membuka
database; dengan menyalin dulu, folder bukti tidak tersentuh sama sekali),
lalu salinan dihapus.
"""
from __future__ import annotations

import re
import shutil
import sqlite3
import tempfile
import time
from pathlib import Path
from typing import Any, Callable, Optional

from . import fconfig

StopCheck = Callable[[], bool]
SubProgress = Callable[[str], None]

# ---------------------------------------------------------------------------
# Export chat WhatsApp (.txt)
# ---------------------------------------------------------------------------
_TS = r"\d{1,2}[/.\-]\d{1,2}[/.\-]\d{2,4},?\s+\d{1,2}[.:]\d{2}(?:[.:]\d{2})?(?:\s?[APap]\.?\s?[Mm]\.?)?"
# Android: "12/11/26 21.02 - Andi: pesan"   iPhone: "[12/11/26 21.02.15] Andi: pesan"
_LINE_ANDROID = re.compile(rf"^‎?({_TS})\s+-\s+(.*)$")
_LINE_IOS = re.compile(rf"^‎?\[({_TS})\]\s+(.*)$")
_MEDIA_NAME = re.compile(
    r"([\w\-. ]+\.(?:jpe?g|png|webp|gif|mp4|3gp|mov|opus|ogg|m4a|mp3|aac|amr|pdf|docx?|xlsx?|pptx?|vcf))",
    re.IGNORECASE)


def _split_sender(rest: str) -> tuple[str, str]:
    # "Nama: isi"  - nama tidak mengandung ':' ; pesan sistem tidak punya pengirim
    m = re.match(r"^([^:]{1,80}?):\s(.*)$", rest, re.S)
    if m:
        return m.group(1).strip("‎ "), m.group(2)
    return "Sistem", rest


def parse_chat_export(text: str) -> Optional[list[dict]]:
    """Kembalikan segmen per pesan bila teks adalah export chat WhatsApp, else None."""
    lines = text.splitlines()
    if not lines:
        return None
    hits = sum(1 for ln in lines[:400] if _LINE_ANDROID.match(ln) or _LINE_IOS.match(ln))
    sample = min(len(lines), 400)
    if hits < 2 or hits < 0.3 * sum(1 for ln in lines[:sample] if ln.strip()):
        return None
    msgs: list[list[str]] = []
    for ln in lines:
        m = _LINE_ANDROID.match(ln) or _LINE_IOS.match(ln)
        if m:
            msgs.append([m.group(1), m.group(2)])
        elif msgs:
            msgs[-1][1] += "\n" + ln  # baris lanjutan pesan multi-baris
    segs = []
    for i, (ts, rest) in enumerate(msgs, 1):
        sender, body = _split_sender(rest.strip())
        body = body.replace("‎", "").strip()
        if not body:
            continue
        mm = _MEDIA_NAME.search(body)
        segs.append({"source": "chat_export", "text": f"{sender}: {body}",
                     "label": f"{ts} • {sender}", "page": i, "ref": mm.group(1).strip() if mm else None})
    return segs


# ---------------------------------------------------------------------------
# Database SQLite
# ---------------------------------------------------------------------------
def _fmt_epoch(ts: Optional[float]) -> str:
    if ts is None:
        return "-"
    try:
        return time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(ts))
    except (OverflowError, OSError, ValueError):
        return str(ts)


def _copy_db(path: str, tmp_root: Path) -> tuple[Path, Path]:
    """Salin db + file pendamping (-wal, -shm, -journal) ke folder sementara."""
    tmp = Path(tempfile.mkdtemp(prefix="db_", dir=tmp_root))
    src = Path(path)
    dst = tmp / src.name
    shutil.copy2(src, dst)
    for suf in ("-wal", "-shm", "-journal"):
        side = Path(str(src) + suf)
        if side.exists():
            shutil.copy2(side, Path(str(dst) + suf))
    return tmp, dst


def _tables(conn: sqlite3.Connection) -> dict[str, list[str]]:
    out = {}
    for (name,) in conn.execute("SELECT name FROM sqlite_master WHERE type='table'"):
        try:
            out[name] = [r[1] for r in conn.execute(f'PRAGMA table_info("{name}")')]
        except sqlite3.DatabaseError:
            continue
    return out


def _contacts_from_wa_db(db_path: str, tmp_root: Path) -> dict[str, str]:
    """Nama kontak dari wa.db (Android) di folder yang sama, bila ada."""
    wa = Path(db_path).with_name("wa.db")
    if not wa.exists():
        return {}
    tmp, copy = _copy_db(str(wa), tmp_root)
    try:
        c = sqlite3.connect(str(copy))
        cols = [r[1] for r in c.execute("PRAGMA table_info(wa_contacts)")]
        name_cols = [x for x in ("display_name", "wa_name", "given_name") if x in cols]
        if "jid" not in cols or not name_cols:
            return {}
        q = f"SELECT jid, COALESCE({', '.join(name_cols)}) FROM wa_contacts"
        return {j: n for j, n in c.execute(q) if j and n}
    except sqlite3.DatabaseError:
        return {}
    finally:
        try:
            c.close()
        except Exception:  # noqa: BLE001
            pass
        shutil.rmtree(tmp, ignore_errors=True)


def _wa_android_new(c: sqlite3.Connection, t: dict, contacts: dict, should_stop: StopCheck) -> list[dict]:
    jids = {r[0]: r[1] for r in c.execute("SELECT _id, raw_string FROM jid")}
    chats = {}
    chat_cols = t.get("chat", [])
    subj = "subject" if "subject" in chat_cols else "NULL"
    for cid, jrow, sj in c.execute(f"SELECT _id, jid_row_id, {subj} FROM chat"):
        jid = jids.get(jrow, "")
        chats[cid] = (sj or contacts.get(jid) or jid or f"chat#{cid}", jid)
    media = {}
    if "message_media" in t:
        mcols = t["message_media"]
        cap = "media_caption" if "media_caption" in mcols else "NULL"
        if "file_path" in mcols:
            for mid, fp, mc in c.execute(f"SELECT message_row_id, file_path, {cap} FROM message_media"):
                media[mid] = (fp, mc)
    mcols = t["message"]
    sender_col = "sender_jid_row_id" if "sender_jid_row_id" in mcols else "NULL"
    type_col = "message_type" if "message_type" in mcols else "0"
    segs = []
    q = (f"SELECT _id, chat_row_id, from_me, {sender_col}, timestamp, {type_col}, text_data "
         f"FROM message ORDER BY chat_row_id, timestamp")
    for i, (mid, chat_id, from_me, sjid, ts, mtype, text) in enumerate(c.execute(q)):
        if i % 2000 == 0 and should_stop():
            break
        fp, cap = media.get(mid, (None, None))
        body = text or cap or ""
        if fp:
            body = (body + " " if body else "") + f"[media: {Path(fp).name}]"
        if not body.strip():
            continue
        chat_name, chat_jid = chats.get(chat_id, (f"chat#{chat_id}", ""))
        if from_me:
            sender = "Saya (pemilik HP)"
        else:
            sj = jids.get(sjid) if sjid else chat_jid
            sender = contacts.get(sj or "", "") or sj or chat_name
        segs.append({"source": "wa_db", "text": f"{sender}: {body}",
                     "label": f"{_fmt_epoch((ts or 0) / 1000)} • Chat: {chat_name} • Dari: {sender}",
                     "page": mid, "ref": fp})
    return segs


def _wa_android_legacy(c: sqlite3.Connection, t: dict, contacts: dict, should_stop: StopCheck) -> list[dict]:
    cols = t["messages"]
    cap = "media_caption" if "media_caption" in cols else "NULL"
    res = "remote_resource" if "remote_resource" in cols else "NULL"
    name = "media_name" if "media_name" in cols else "NULL"
    segs = []
    q = (f"SELECT _id, key_remote_jid, key_from_me, data, timestamp, {cap}, {res}, {name} "
         f"FROM messages ORDER BY key_remote_jid, timestamp")
    for i, (mid, jid, from_me, data, ts, mc, rres, mname) in enumerate(c.execute(q)):
        if i % 2000 == 0 and should_stop():
            break
        body = data or mc or ""
        if mname:
            body = (body + " " if body else "") + f"[media: {mname}]"
        if not body.strip() or jid == "-1":
            continue
        chat_name = contacts.get(jid or "", "") or jid or "-"
        sender = "Saya (pemilik HP)" if from_me else (contacts.get(rres or "", "") or rres or chat_name)
        segs.append({"source": "wa_db", "text": f"{sender}: {body}",
                     "label": f"{_fmt_epoch((ts or 0) / 1000)} • Chat: {chat_name} • Dari: {sender}",
                     "page": mid, "ref": mname})
    return segs


def _wa_ios(c: sqlite3.Connection, t: dict, should_stop: StopCheck) -> list[dict]:
    sessions = {}
    scols = t.get("ZWACHATSESSION", [])
    if scols:
        pn = "ZPARTNERNAME" if "ZPARTNERNAME" in scols else "NULL"
        cj = "ZCONTACTJID" if "ZCONTACTJID" in scols else "NULL"
        for pk, name, jid in c.execute(f"SELECT Z_PK, {pn}, {cj} FROM ZWACHATSESSION"):
            sessions[pk] = name or jid or f"chat#{pk}"
    members = {}
    gcols = t.get("ZWAGROUPMEMBER", [])
    if "ZMEMBERJID" in gcols and "ZCONTACTNAME" in gcols:
        members = {j: n for j, n in c.execute("SELECT ZMEMBERJID, ZCONTACTNAME FROM ZWAGROUPMEMBER") if j and n}
    media = {}
    mcols = t.get("ZWAMEDIAITEM", [])
    if "ZMEDIALOCALPATH" in mcols:
        title = "ZTITLE" if "ZTITLE" in mcols else "NULL"
        for pk, fp, tt in c.execute(f"SELECT Z_PK, ZMEDIALOCALPATH, {title} FROM ZWAMEDIAITEM"):
            media[pk] = (fp, tt)
    cols = t["ZWAMESSAGE"]

    def col(n):
        return n if n in cols else "NULL"
    q = (f"SELECT Z_PK, {col('ZCHATSESSION')}, {col('ZISFROMME')}, {col('ZFROMJID')}, {col('ZPUSHNAME')}, "
         f"{col('ZMESSAGEDATE')}, {col('ZTEXT')}, {col('ZMEDIAITEM')} FROM ZWAMESSAGE "
         f"ORDER BY {col('ZCHATSESSION')}, {col('ZMESSAGEDATE')}")
    segs = []
    for i, (pk, sess, from_me, fjid, push, date, text, mitem) in enumerate(c.execute(q)):
        if i % 2000 == 0 and should_stop():
            break
        fp, tt = media.get(mitem, (None, None))
        body = text or tt or ""
        if fp:
            body = (body + " " if body else "") + f"[media: {Path(fp).name}]"
        if not body.strip():
            continue
        chat_name = sessions.get(sess, f"chat#{sess}")
        sender = "Saya (pemilik HP)" if from_me else (members.get(fjid or "", "") or push or fjid or chat_name)
        ts = (date + 978307200) if isinstance(date, (int, float)) else None  # epoch Apple 2001-01-01
        segs.append({"source": "wa_db", "text": f"{sender}: {body}",
                     "label": f"{_fmt_epoch(ts)} • Chat: {chat_name} • Dari: {sender}",
                     "page": pk, "ref": fp})
    return segs


def _generic(c: sqlite3.Connection, t: dict, should_stop: StopCheck, sub: SubProgress,
             platform: Optional[str] = None) -> list[dict]:
    from .social import PLATFORM_LABEL

    prefix = f"{PLATFORM_LABEL.get(platform, platform)} • " if platform else ""
    segs = []
    total = 0
    for name, cols in t.items():
        if name.startswith("sqlite_") or re.search(r"_(content|segments|segdir|docsize|stat|data|idx|config)$", name):
            continue
        if should_stop() or total > fconfig.DB_MAX_TOTAL_CHARS:
            break
        sub(f"tabel {name}")
        try:
            cur = c.execute(f'SELECT rowid, * FROM "{name}" LIMIT {fconfig.DB_MAX_ROWS_PER_TABLE}')
        except sqlite3.DatabaseError:
            try:
                cur = c.execute(f'SELECT NULL, * FROM "{name}" LIMIT {fconfig.DB_MAX_ROWS_PER_TABLE}')
            except sqlite3.DatabaseError:
                continue
        for row in cur:
            parts = []
            for i, v in enumerate(row):
                if i == 0 or i - 1 >= len(cols):
                    continue
                if isinstance(v, str) and len(v.strip()) >= 3:
                    parts.append(f"{cols[i - 1]}={v}")
                elif isinstance(v, (bytes, bytearray)):
                    bt = blob_text(v, 5)
                    if bt:
                        parts.append(f"{cols[i - 1]}(blob)={bt}")
            if not parts:
                continue
            txt = " | ".join(parts)[:4000]
            total += len(txt)
            segs.append({"source": "db_text", "text": txt, "label": f"{prefix}Tabel {name} • baris {row[0]}",
                         "page": row[0] if isinstance(row[0], int) else None})
            if total > fconfig.DB_MAX_TOTAL_CHARS:
                break
    return segs


def extract_database(path: str, tmp_root: Path, should_stop: StopCheck, sub: SubProgress) -> tuple[list[dict], str]:
    """Kembalikan (segmen, jenis_database)."""
    ext = Path(path).suffix.lower()
    if ext in fconfig.ENCRYPTED_DB_EXT or ".crypt" in Path(path).name.lower():
        raise RuntimeError("Database WhatsApp TERENKRIPSI (.crypt). Dekripsi dulu dengan kunci (file 'key') "
                           "menggunakan tool forensik, lalu analisis msgstore.db hasil dekripsi.")
    tmp_root.mkdir(parents=True, exist_ok=True)
    tmp, copy = _copy_db(path, tmp_root)
    conn = None
    try:
        conn = sqlite3.connect(str(copy))
        try:
            t = _tables(conn)
        except sqlite3.DatabaseError as exc:
            from .social import detect_platform_from_path

            plat = detect_platform_from_path(path)
            hint = f" ({plat})" if plat else ""
            raise RuntimeError(f"Database TERENKRIPSI atau rusak{hint}: {exc}. Aplikasi seperti Signal, WeChat, "
                               "dan Telegram iPhone memakai enkripsi SQLCipher - butuh kunci/dekripsi dengan "
                               "tool forensik sebelum bisa dibaca.") from exc
        if {"message", "chat", "jid"} <= set(t) and "text_data" in t["message"]:
            sub("WhatsApp Android (msgstore.db)")
            return _wa_android_new(conn, t, _contacts_from_wa_db(path, tmp_root), should_stop), "WhatsApp Android"
        if "messages" in t and "key_remote_jid" in t["messages"]:
            sub("WhatsApp Android (skema lama)")
            return _wa_android_legacy(conn, t, _contacts_from_wa_db(path, tmp_root), should_stop), \
                "WhatsApp Android (lama)"
        if "ZWAMESSAGE" in t:
            sub("WhatsApp iPhone (ChatStorage.sqlite)")
            return _wa_ios(conn, t, should_stop), "WhatsApp iPhone"
        app_db = detect_app_db(t)
        if app_db:
            name, fn = app_db
            sub(name)
            return fn(conn, t, should_stop), name
        from .social import detect_platform_from_path

        plat = detect_platform_from_path(path)
        return _generic(conn, t, should_stop, sub, plat), f"SQLite umum{f' ({plat})' if plat else ''}"
    finally:
        if conn is not None:
            conn.close()
        shutil.rmtree(tmp, ignore_errors=True)


# ===========================================================================
# Database aplikasi lain dari ekstraksi ponsel
# ===========================================================================
_BLOB_RUN = re.compile(r"[^\x00-\x08\x0b-\x1f\x7f-\x9f�]{4,}")
_NOISE = re.compile(r"^(NS[A-Z]\w+|__kIM\w*|streamtyped|\$classname|\$classes|X\$versionY|bplist\d*)$")


def blob_text(b: Any, min_len: int = 4) -> str:
    """Ambil teks terbaca dari kolom BLOB (Telegram TL, attributedBody iMessage, protobuf, dll)."""
    if not isinstance(b, (bytes, bytearray)) or not b or len(b) > 2_000_000:
        return ""
    s = bytes(b).decode("utf-8", errors="replace")
    runs = []
    for r in _BLOB_RUN.findall(s):
        r = r.strip()
        if len(r) < min_len or _NOISE.match(r):
            continue
        letters = sum(ch.isalpha() or ch.isspace() for ch in r)
        if letters / len(r) >= 0.6 and any(ch.isalpha() for ch in r):
            runs.append(r)
    return " ".join(runs)


def _lbl(platform: str, when: str, chat: str, sender: str) -> str:
    from .social import PLATFORM_LABEL

    parts = [PLATFORM_LABEL.get(platform, platform), when]
    if chat:
        parts.append(f"Chat: {chat}")
    if sender:
        parts.append(f"Dari: {sender}")
    return " • ".join(parts)


def _telegram_android(c: sqlite3.Connection, t: dict, should_stop: StopCheck) -> list[dict]:
    names = {}
    for tbl in ("users", "chats"):
        if tbl in t and "uid" in t[tbl] and "name" in t[tbl]:
            for uid, name in c.execute(f"SELECT uid, name FROM {tbl}"):
                nm = (name or "").split(";;;")[0].strip()
                names[uid if tbl == "users" else -uid] = nm or str(uid)
    cols = t["messages_v2"]
    out_col = "out" if "out" in cols else "0"
    segs = []
    for i, (mid, uid, date, data, out) in enumerate(c.execute(
            f"SELECT mid, uid, date, data, {out_col} FROM messages_v2 ORDER BY uid, date")):
        if i % 2000 == 0 and should_stop():
            break
        text = blob_text(data)
        if not text:
            continue
        chat = names.get(uid) or str(uid)
        sender = "Saya (pemilik HP)" if out else chat
        segs.append({"source": "telegram", "text": f"{sender}: {text}", "page": mid,
                     "label": _lbl("telegram", _fmt_epoch(date), chat, sender)})
    return segs


def _messenger_android(c: sqlite3.Connection, t: dict, should_stop: StopCheck) -> list[dict]:
    import json as _json

    threads = {}
    if "threads" in t and "thread_key" in t["threads"] and "name" in t["threads"]:
        threads = {k: n for k, n in c.execute("SELECT thread_key, name FROM threads") if n}
    sender_col = "sender" if "sender" in t["messages"] else "NULL"
    segs = []
    for i, (mid, tk, text, snd, ts) in enumerate(c.execute(
            f"SELECT msg_id, thread_key, text, {sender_col}, timestamp_ms FROM messages ORDER BY thread_key, timestamp_ms")):
        if i % 2000 == 0 and should_stop():
            break
        if not text:
            continue
        sender = ""
        if snd:
            try:
                sender = _json.loads(snd).get("name", "")
            except (ValueError, AttributeError):
                sender = str(snd)
        chat = threads.get(tk) or str(tk)
        segs.append({"source": "messenger", "text": f"{sender}: {text}" if sender else text, "page": None,
                     "label": _lbl("messenger", _fmt_epoch((ts or 0) / 1000), chat, sender)})
    return segs


def _instagram_android(c: sqlite3.Connection, t: dict, should_stop: StopCheck) -> list[dict]:
    import json as _json

    cols = t["messages"]
    text_col = "text" if "text" in cols else "NULL"
    msg_col = "message" if "message" in cols else "NULL"
    ts_col = "timestamp" if "timestamp" in cols else "NULL"
    user_col = "user_id" if "user_id" in cols else "NULL"
    titles = {}
    if "threads" in t and "thread_id" in t["threads"] and "thread_info" in t["threads"]:
        for tid, info in c.execute("SELECT thread_id, thread_info FROM threads"):
            try:
                titles[tid] = _json.loads(info).get("thread_title") or ""
            except (ValueError, TypeError, AttributeError):
                pass
    segs = []
    for i, (tid, uid, ts, text, msg) in enumerate(c.execute(
            f"SELECT thread_id, {user_col}, {ts_col}, {text_col}, {msg_col} FROM messages")):
        if i % 2000 == 0 and should_stop():
            break
        body = text or ""
        if not body and msg:
            try:
                body = _json.loads(msg).get("text") or ""
            except (ValueError, TypeError, AttributeError):
                body = blob_text(msg) if isinstance(msg, bytes) else str(msg)
        if not body:
            continue
        when = _fmt_epoch(ts / 1e6 if ts and ts > 1e14 else (ts / 1e3 if ts and ts > 1e11 else ts))
        chat = titles.get(tid) or str(tid)
        sender = f"user {uid}" if uid else ""
        segs.append({"source": "instagram", "text": f"{sender}: {body}" if sender else body,
                     "label": _lbl("instagram", when, chat, sender)})
    return segs


def _line_android(c: sqlite3.Connection, t: dict, should_stop: StopCheck) -> list[dict]:
    contacts = {}
    if "contacts" in t and "m_id" in t["contacts"] and "name" in t["contacts"]:
        contacts = {m: n for m, n in c.execute("SELECT m_id, name FROM contacts") if n}
    chats = {}
    if "chat" in t and "chat_id" in t["chat"] and "name" in t["chat"]:
        chats = {k: n for k, n in c.execute("SELECT chat_id, name FROM chat") if n}
    segs = []
    for i, (cid, frm, content, ts) in enumerate(c.execute(
            "SELECT chat_id, from_mid, content, created_time FROM chat_history ORDER BY chat_id, created_time")):
        if i % 2000 == 0 and should_stop():
            break
        if not content:
            continue
        sender = "Saya (pemilik HP)" if not frm else contacts.get(frm, frm)
        chat = chats.get(cid) or contacts.get(cid) or str(cid)
        segs.append({"source": "line", "text": f"{sender}: {content}",
                     "label": _lbl("line", _fmt_epoch(float(ts) / 1000 if ts else None), chat, sender)})
    return segs


def _imessage(c: sqlite3.Connection, t: dict, should_stop: StopCheck) -> list[dict]:
    handles = {r: h for r, h in c.execute("SELECT ROWID, id FROM handle")} if "handle" in t else {}
    cols = t["message"]
    body_col = "attributedBody" if "attributedBody" in cols else "NULL"
    svc = "service" if "service" in cols else "NULL"
    segs = []
    for i, (rid, text, hid, date, me, body, service) in enumerate(c.execute(
            f"SELECT ROWID, text, handle_id, date, is_from_me, {body_col}, {svc} FROM message ORDER BY date")):
        if i % 2000 == 0 and should_stop():
            break
        msg = text or blob_text(body)
        if not msg:
            continue
        ts = None
        if isinstance(date, (int, float)) and date:
            ts = (date / 1e9 if date > 1e12 else date) + 978307200
        who = handles.get(hid, "")
        sender = "Saya (pemilik HP)" if me else who
        plat_label = service or "iMessage/SMS"
        segs.append({"source": "imessage", "text": f"{sender}: {msg}",
                     "label": _lbl("imessage", _fmt_epoch(ts), who, sender) + (f" • {plat_label}" if service else "")})
    return segs


def _android_sms(c: sqlite3.Connection, t: dict, should_stop: StopCheck) -> list[dict]:
    segs = []
    for i, (addr, date, typ, body) in enumerate(c.execute("SELECT address, date, type, body FROM sms ORDER BY date")):
        if i % 2000 == 0 and should_stop():
            break
        if not body:
            continue
        sender = "Saya (pemilik HP)" if typ == 2 else (addr or "")
        segs.append({"source": "sms", "text": f"{sender}: {body}",
                     "label": _lbl("sms", _fmt_epoch((date or 0) / 1000), addr or "", sender)})
    return segs


def detect_app_db(t: dict) -> Optional[tuple[str, Callable]]:
    """Kenali database aplikasi dari struktur tabelnya."""
    def has(tbl, *cols):
        return tbl in t and all(col in t[tbl] for col in cols)
    if has("messages_v2", "uid", "date", "data"):
        return "Telegram Android (cache4.db)", _telegram_android
    if has("messages", "thread_key", "text", "timestamp_ms") and "msg_id" in t["messages"]:
        return "Facebook Messenger Android (threads_db2)", _messenger_android
    if has("messages", "thread_id") and ("text" in t["messages"] or "message" in t["messages"]) \
            and "key_remote_jid" not in t["messages"]:
        return "Instagram Android (direct.db)", _instagram_android
    if has("chat_history", "chat_id", "from_mid", "content", "created_time"):
        return "LINE", _line_android
    if has("message", "text", "handle_id", "date", "is_from_me"):
        return "iMessage/SMS iPhone (sms.db)", _imessage
    if has("sms", "address", "date", "type", "body"):
        return "SMS Android (mmssms.db)", _android_sms
    return None
