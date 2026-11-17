"""Dataset uji media sosial & aplikasi pesan (export akun + database aplikasi ponsel).

    python tests/make_social_dataset.py <folder_output>

Setiap sumber memuat kalimat target "tolong lakukan penyerangan itu" (dengan variasi).
"""
from __future__ import annotations

import json
import sqlite3
import sys
from pathlib import Path

T = "tolong lakukan penyerangan itu"


def w(p: Path, text: str) -> None:
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text, encoding="utf-8")


def meta_mojibake(s: str) -> str:
    """Tiru encoding rusak khas export Meta (UTF-8 disimpan per byte)."""
    return s.encode("utf-8").decode("latin-1")


def db(p: Path, script: str, params: list | None = None) -> sqlite3.Connection:
    p.parent.mkdir(parents=True, exist_ok=True)
    c = sqlite3.connect(p)
    c.executescript(script)
    for q, v in params or []:
        c.execute(q, v)
    c.commit()
    c.close()


def main(out: Path) -> None:
    # ---------------- Meta: Facebook / Instagram / Threads / Messenger
    fb = {"participants": [{"name": "Budi Santoso"}, {"name": "Pemilik Akun"}],
          "messages": [
              {"sender_name": "Budi Santoso", "timestamp_ms": 1794500000000, "content": meta_mojibake("halo bro 😀")},
              {"sender_name": "Pemilik Akun", "timestamp_ms": 1794500060000,
               "content": meta_mojibake(f"Bro {T} ya, jangan bilang siapa² 😡")},
              {"sender_name": "Budi Santoso", "timestamp_ms": 1794500100000,
               "photos": [{"uri": "messages/inbox/budisantoso_123/photos/lokasi_1.jpg"}]}],
          "title": "Budi Santoso", "thread_path": "inbox/budisantoso_123"}
    w(out / "facebook/your_facebook_activity/messages/inbox/budisantoso_123/message_1.json",
      json.dumps(fb, ensure_ascii=True))
    ig = dict(fb, title="andi.ig", participants=[{"name": "andi.ig"}])
    ig["messages"] = [{"sender_name": "andi.ig", "timestamp_ms": 1794500200000, "content": f"hay {T} malam ini"}]
    w(out / "instagram/your_instagram_activity/messages/inbox/andiig_456/message_1.json", json.dumps(ig))
    w(out / "instagram/your_instagram_activity/threads/threads_and_replies.json", json.dumps(
        {"text_post_app_text_posts": [{"media": [{"title": f"Pengumuman: {T} besok", "creation_timestamp": 1794500300}]}]}))
    w(out / "instagram/your_instagram_activity/comments/post_comments_1.json", json.dumps(
        [{"media_list_data": [{"uri": ""}], "string_map_data": {
            "Comment": {"value": f"setuju, {T}!"}, "Media Owner": {"value": "akun_lain"}, "Time": {"timestamp": 1794500400}}}]))
    w(out / "messenger_e2ee/budi_santoso.json", json.dumps(
        {"participants": ["Budi Santoso", "Pemilik Akun"], "threadName": "Budi Santoso",
         "messages": [{"isUnsent": False, "media": [], "reactions": [], "senderName": "Budi Santoso",
                       "text": f"oke aku {T}", "timestamp": 1794500500000, "type": "text"}]}))

    # ---------------- Telegram Desktop (JSON & HTML)
    w(out / "telegram/ChatExport_2026-11-12/result.json", json.dumps({
        "name": "Rudi Telegram", "type": "personal_chat", "id": 777,
        "messages": [
            {"id": 1, "type": "message", "date": "2026-11-12T21:00:00", "from": "Rudi", "text": "siap?"},
            {"id": 2, "type": "message", "date": "2026-11-12T21:01:00", "from": "Andi",
             "text": ["hay ", {"type": "bold", "text": "tolong lakukan"}, " penyerangan itu"]},
            {"id": 3, "type": "message", "date": "2026-11-12T21:02:00", "from": "Rudi",
             "photo": "photos/photo_1@12-11-2026_21-02-00.jpg", "text": ""}]}))
    w(out / "telegram/ChatExport_2026-11-13/messages.html", f"""<!DOCTYPE html><html><body>
<div class="page_wrap"><div class="page_header"><div class="content"><div class="text bold">Grup Rencana</div></div></div>
<div class="history">
<div class="message default clearfix" id="message10"><div class="body">
<div class="pull_right date details" title="13.11.2026 20:00:00 UTC+07:00">20:00</div>
<div class="from_name">Sari </div><div class="text">Kumpul jam 8</div></div></div>
<div class="message default clearfix joined" id="message11"><div class="body">
<div class="pull_right date details" title="13.11.2026 20:01:00 UTC+07:00">20:01</div>
<div class="text">Hay {T} sesuai rencana</div></div></div>
</div></div></body></html>""")

    # ---------------- Twitter / X archive
    w(out / "twitter/data/tweets.js", "window.YTD.tweets.part0 = " + json.dumps([
        {"tweet": {"id_str": "1", "created_at": "Thu Nov 12 21:00:00 +0000 2026", "full_text": f"Kalian {T}! #aksi"}}]))
    w(out / "twitter/data/direct-messages.js", "window.YTD.direct_messages.part0 = " + json.dumps([
        {"dmConversation": {"conversationId": "111-222", "messages": [
            {"messageCreate": {"senderId": "111", "recipientId": "222", "text": f"hay {T}",
                               "createdAt": "2026-11-12T21:05:00.000Z", "mediaUrls": []}}]}}]))

    # ---------------- Discord (data package & DiscordChatExporter)
    w(out / "discord/package/messages/c111/channel.json", json.dumps({"id": "111", "type": 0, "name": "rencana",
                                                                        "guild": {"id": "9", "name": "Server Rahasia"}}))
    w(out / "discord/package/messages/c111/messages.json", json.dumps([
        {"ID": 1, "Timestamp": "2026-11-12 21:10:00", "Contents": f"semua {T}", "Attachments": ""}]))
    w(out / "discord/package/messages/c222/channel.json", json.dumps({"id": "222", "type": 1, "recipients": ["555", "666"]}))
    w(out / "discord/package/messages/c222/messages.csv",
      f"ID,Timestamp,Contents,Attachments\n1,2026-11-12 21:11:00,\"dm: {T}\",\n")
    w(out / "discord/exporter/Server Rahasia - general [123].json", json.dumps({
        "guild": {"id": "9", "name": "Server Rahasia"}, "channel": {"id": "123", "name": "general"},
        "messages": [{"id": "1", "timestamp": "2026-11-12T21:12:00+07:00", "content": f"ingat {T}",
                      "author": {"id": "5", "name": "andi#0001", "nickname": "Andi"}, "attachments": []}]}))

    # ---------------- TikTok, Snapchat, Skype, Google Chat, LinkedIn
    w(out / "tiktok/user_data_tiktok.json", json.dumps({"Direct Message": {"Direct Messages": {"ChatHistory": {
        "Chat History with budi_tt:": [{"Date": "2026-11-12 21:20:00", "From": "budi_tt", "Content": f"bro {T}"}]}}}}))
    w(out / "snapchat/json/chat_history.json", json.dumps({"sari_snap": [
        {"From": "sari_snap", "Media Type": "TEXT", "Created": "2026-11-12 21:25:00 UTC", "Content": f"{T} ya"}]}))
    w(out / "skype/messages.json", json.dumps({"userId": "live:pemilik", "conversations": [
        {"id": "8:live:rudi", "displayName": "Rudi Skype", "MessageList": [
            {"id": "1", "originalarrivaltime": "2026-11-12T21:30:00.000Z", "from": "8:live:rudi",
             "content": f"hay {T}", "messagetype": "RichText"}]}]}))
    w(out / "google_chat/Groups/DM abc/messages.json", json.dumps({"messages": [
        {"creator": {"name": "Dewi", "email": "dewi@example.com"}, "created_date": "Thursday, November 12, 2026 at 9:35:00 PM UTC",
         "text": f"tolong ya, lakukan penyerangan itu"}]}))
    w(out / "linkedin/messages.csv",
      "CONVERSATION ID,CONVERSATION TITLE,FROM,SENDER PROFILE URL,TO,DATE,SUBJECT,CONTENT,FOLDER\n"
      f"c1,Proyek,Rina,https://x,Pemilik,2026-11-12 21:40:00 UTC,,\"{T} minggu ini\",INBOX\n")

    # ---------------- SMS Backup & Restore (XML)
    w(out / "sms/sms-20261112.xml", f"""<?xml version='1.0' encoding='UTF-8' standalone='yes' ?>
<smses count="2">
  <sms protocol="0" address="+6281200000009" date="1794500700000" type="1" body="Hay {T}" contact_name="Joko" />
  <sms protocol="0" address="+6281200000009" date="1794500760000" type="2" body="siap" contact_name="Joko" />
</smses>""")
    w(out / "sms/calls-20261112.xml", """<?xml version='1.0' encoding='UTF-8' standalone='yes' ?>
<calls count="1"><call number="+6281200000009" duration="65" date="1794500800000" type="2" contact_name="Joko" /></calls>""")

    # ---------------- Database aplikasi dari ekstraksi ponsel Android
    a = out / "hp_android/data/data"
    tl = b"\x01\x00\x00\x00\xb5\x1a" + bytes([len(f"hay {T}".encode())]) + f"hay {T}".encode() + b"\x00\x00\x0f\xa3\x99"
    db(a / "org.telegram.messenger/files/cache4.db", """
      CREATE TABLE users (uid INTEGER PRIMARY KEY, name TEXT, status INTEGER, data BLOB);
      CREATE TABLE messages_v2 (mid INTEGER, uid INTEGER, read_state INTEGER, send_state INTEGER, date INTEGER,
        data BLOB, out INTEGER, ttl INTEGER, media INTEGER, replydata BLOB, imp INTEGER, mention INTEGER,
        forwards INTEGER, replies_data BLOB, thread_reply_id INTEGER, is_channel INTEGER, reply_to_message_id INTEGER,
        custom_params BLOB, group_id INTEGER, reply_to_story_id INTEGER);
      INSERT INTO users VALUES (5001, 'rudi tele;;;rudi_t', 0, NULL);""",
       [("INSERT INTO messages_v2 (mid, uid, date, data, out) VALUES (?,?,?,?,?)", (1, 5001, 1794500900, tl, 0))])
    db(a / "com.facebook.orca/databases/threads_db2", """
      CREATE TABLE threads (thread_key TEXT PRIMARY KEY, name TEXT);
      CREATE TABLE messages (msg_id TEXT PRIMARY KEY, thread_key TEXT, text TEXT, sender TEXT, timestamp_ms INTEGER);
      INSERT INTO threads VALUES ('ONE_TO_ONE:1:2', NULL);""",
       [("INSERT INTO messages VALUES (?,?,?,?,?)",
         ("m1", "ONE_TO_ONE:1:2", f"aku mau {T}", json.dumps({"user_key": "FACEBOOK:1", "name": "Budi FB"}), 1794501000000))])
    db(a / "com.instagram.android/databases/direct.db", """
      CREATE TABLE threads (thread_id TEXT PRIMARY KEY, thread_info TEXT);
      CREATE TABLE messages (_id INTEGER PRIMARY KEY, thread_id TEXT, user_id TEXT, timestamp INTEGER,
        message_type TEXT, text TEXT, message TEXT);""",
       [("INSERT INTO threads VALUES (?,?)", ("t1", json.dumps({"thread_title": "andi.ig"}))),
        ("INSERT INTO messages VALUES (?,?,?,?,?,?,?)",
         (1, "t1", "999", 1794501100000000, "text", None, json.dumps({"text": f"hay {T} (dari direct.db)"})))])
    db(a / "jp.naver.line.android/databases/naver_line", """
      CREATE TABLE contacts (m_id TEXT PRIMARY KEY, name TEXT);
      CREATE TABLE chat (chat_id TEXT PRIMARY KEY, name TEXT);
      CREATE TABLE chat_history (id INTEGER PRIMARY KEY, chat_id TEXT, from_mid TEXT, content TEXT, created_time TEXT);
      INSERT INTO contacts VALUES ('u123', 'Tono LINE');""",
       [("INSERT INTO chat_history VALUES (?,?,?,?,?)", (1, "u123", "u123", f"{T} segera", "1794501200000"))])
    db(a / "com.android.providers.telephony/databases/mmssms.db", """
      CREATE TABLE sms (_id INTEGER PRIMARY KEY, address TEXT, date INTEGER, type INTEGER, body TEXT);""",
       [("INSERT INTO sms VALUES (?,?,?,?,?)", (1, "+6281300000001", 1794501300000, 1, f"HAY {T.upper()}"))])
    db(a / "com.discord/cache/cache.db", "CREATE TABLE kv (k TEXT, v BLOB);",
       [("INSERT INTO kv VALUES (?,?)", ("msg", b"\x08\x01\x12" + f"discord cache: {T}".encode() + b"\x18\x02"))])
    enc = a / "org.thoughtcrime.securesms/databases/signal.db"
    enc.parent.mkdir(parents=True, exist_ok=True)
    enc.write_bytes(bytes((i * 37 + 11) % 256 for i in range(8192)))  # tiruan SQLCipher (terenkripsi)

    # ---------------- iPhone: iMessage/SMS (sms.db) dengan attributedBody
    body = (b"\x04\x0bstreamtyped\x81\xe8\x03\x84\x01@\x84\x84\x84\x12NSAttributedString\x00\x84\x84\x08NSObject"
            b"\x00\x85\x92\x84\x84\x84\x08NSString\x01\x94\x84\x01+" + bytes([len(f"hay {T}")]) + f"hay {T}".encode()
            + b"\x86\x84\x02iI\x01\x0f\x92\x84\x84\x84\x0cNSDictionary\x00")
    db(out / "hp_iphone/HomeDomain/Library/SMS/sms.db", """
      CREATE TABLE handle (ROWID INTEGER PRIMARY KEY, id TEXT, service TEXT);
      CREATE TABLE message (ROWID INTEGER PRIMARY KEY, text TEXT, handle_id INTEGER, date INTEGER, is_from_me INTEGER,
        attributedBody BLOB, service TEXT);
      INSERT INTO handle VALUES (1, '+6281400000002', 'iMessage');""",
       [("INSERT INTO message VALUES (?,?,?,?,?,?,?)", (1, None, 1, 815000000000000000, 0, body, "iMessage"))])

    # ---------------- Pengecoh (tidak boleh jadi temuan)
    w(out / "lainnya/package.json", json.dumps({"name": "app", "description": "aplikasi kasir", "version": "1.0"}))
    w(out / "lainnya/produk.csv", "id,name,description\n1,Beras,beras premium 5kg\n")
    print(f"Dataset media sosial dibuat di {out}")


if __name__ == "__main__":
    main(Path(sys.argv[1] if len(sys.argv) > 1 else "tests/_social_dataset"))
