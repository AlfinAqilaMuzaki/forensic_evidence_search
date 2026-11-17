"""Pembaca data media sosial & aplikasi pesan (export akun / "Download your information").

Setiap pesan/postingan/komentar menjadi satu segmen dengan label:
    "<platform> • <waktu> • <chat/percakapan> • Dari: <pengirim>"

Didukung (export resmi platform & tool umum):
- Meta: Facebook, Messenger, Instagram, Threads   (JSON; perbaikan encoding Meta otomatis)
- Telegram Desktop "Export chat history"            (result.json & messages.html)
- Twitter / X archive                               (data/*.js: tweets, direct-messages, likes, dll)
- Discord data package (messages.json/.csv + channel.json) & DiscordChatExporter (JSON)
- TikTok, Snapchat, Skype, Google Chat, LinkedIn   (JSON / CSV)
- SMS Backup & Restore (XML: SMS, MMS, log panggilan)
- JSON/CSV lain: pembaca umum yang mengenali objek "pesan" (teks + pengirim + waktu)
"""
from __future__ import annotations

import csv
import io
import json
import re
import time
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from html import unescape
from pathlib import Path
from typing import Any, Optional

# ---------------------------------------------------------------------------
# Util
# ---------------------------------------------------------------------------
TEXT_KEYS = ("text", "content", "contents", "body", "message", "full_text", "fullText", "caption",
             "comment", "value", "Content", "Contents", "Text", "Message", "Body", "description")
SENDER_KEYS = ("sender_name", "senderName", "sender", "from", "From", "author", "creator", "user",
               "username", "Sender", "displayName", "contact_name")
TIME_KEYS = ("timestamp_ms", "timestamp", "date", "Date", "created_at", "createdAt", "created_date",
             "Created", "creation_timestamp", "originalarrivaltime", "time", "Timestamp", "date_unixtime")
NAME_KEYS = ("title", "threadName", "name", "displayName", "conversation_title", "channel", "thread_path")

PLATFORM_LABEL = {
    "facebook": "Facebook", "messenger": "Messenger", "instagram": "Instagram", "threads": "Threads",
    "telegram": "Telegram", "twitter": "Twitter/X", "discord": "Discord", "tiktok": "TikTok",
    "snapchat": "Snapchat", "skype": "Skype", "gchat": "Google Chat", "linkedin": "LinkedIn",
    "sms": "SMS/Telepon", "line": "LINE", "imessage": "iMessage/SMS", "signal": "Signal",
    "wechat": "WeChat", "social": "Media sosial",
}


def fix_meta(s: Any) -> Any:
    """Export Meta (Facebook/Instagram/Threads) menyimpan UTF-8 sebagai \\u00XX per byte."""
    if isinstance(s, str) and s and max(map(ord, s)) < 256 and any(ord(c) > 127 for c in s):
        try:
            return s.encode("latin-1").decode("utf-8")
        except UnicodeError:
            return s
    return s


def fmt_time(v: Any) -> str:
    if v is None or v == "":
        return "-"
    if isinstance(v, (int, float)) or (isinstance(v, str) and re.fullmatch(r"\d{9,16}(\.\d+)?", v)):
        x = float(v)
        if x > 1e14:      # mikrodetik
            x /= 1e6
        elif x > 1e11:    # milidetik
            x /= 1e3
        try:
            return time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(x))
        except (OverflowError, OSError, ValueError):
            return str(v)
    return str(v)


def _text_of(v: Any) -> str:
    """Teks dari string / list campuran (format Telegram) / dict {'text':..}."""
    if v is None:
        return ""
    if isinstance(v, str):
        return v
    if isinstance(v, list):
        return "".join(_text_of(x) for x in v)
    if isinstance(v, dict):
        return _text_of(v.get("text") or v.get("value") or "")
    return str(v)


def _seg(platform: str, text: str, when: Any = None, chat: str = "", sender: str = "",
         ref: Optional[str] = None, kind: str = "") -> dict:
    parts = [PLATFORM_LABEL.get(platform, platform)]
    if kind:
        parts[0] += f" {kind}"
    parts.append(fmt_time(when))
    if chat:
        parts.append(f"Chat: {chat}")
    if sender:
        parts.append(f"Dari: {sender}")
    body = f"{sender}: {text}" if sender else text
    return {"source": platform, "text": body.strip(), "label": " • ".join(parts), "ref": ref}


def detect_platform_from_path(path: str) -> Optional[str]:
    p = path.lower().replace("\\", "/")
    table = [
        ("com.instagram.barcelona", "threads"), ("/threads/", "threads"), ("threads_and_replies", "threads"),
        ("com.instagram.android", "instagram"), ("instagram", "instagram"),
        ("com.facebook.orca", "messenger"), ("messenger", "messenger"),
        ("com.facebook.katana", "facebook"), ("facebook", "facebook"),
        ("org.telegram", "telegram"), ("telegram", "telegram"),
        ("com.twitter.android", "twitter"), ("twitter", "twitter"),
        ("com.discord", "discord"), ("discord", "discord"),
        ("com.zhiliaoapp.musically", "tiktok"), ("tiktok", "tiktok"),
        ("com.snapchat.android", "snapchat"), ("snapchat", "snapchat"),
        ("jp.naver.line", "line"), ("com.linkedin", "linkedin"), ("linkedin", "linkedin"),
        ("com.skype", "skype"), ("skype", "skype"),
        ("google_chat", "gchat"), ("google chat", "gchat"), ("hangouts", "gchat"), ("/groups/dm ", "gchat"),
        ("/groups/space ", "gchat"),
        ("org.thoughtcrime.securesms", "signal"), ("signal", "signal"),
        ("com.tencent.mm", "wechat"),
    ]
    for key, plat in table:
        if key in p:
            return plat
    return None


# ---------------------------------------------------------------------------
# Parser khusus
# ---------------------------------------------------------------------------
def _media_refs(m: dict) -> Optional[str]:
    for k in ("photos", "videos", "audio_files", "files", "gifs", "Attachments", "attachments", "mediaUrls"):
        v = m.get(k)
        if isinstance(v, list) and v:
            x = v[0]
            if isinstance(x, dict):
                return x.get("uri") or x.get("fileName") or x.get("url")
            return str(x)
        if isinstance(v, str) and v.strip():
            return v.strip().split()[0]
    for k in ("photo", "file", "media", "thumbnail"):
        if isinstance(m.get(k), str):
            return m[k]
    return None


def parse_meta_messages(d: dict, path: str) -> Optional[list[dict]]:
    """Facebook/Messenger/Instagram message_N.json (lama) & export Messenger E2EE (baru)."""
    msgs = d.get("messages")
    if not isinstance(msgs, list) or not msgs or not isinstance(msgs[0], dict):
        return None
    first = msgs[0]
    if not ({"sender_name", "timestamp_ms"} <= set(first) or {"senderName", "timestamp"} <= set(first)):
        return None
    plat = detect_platform_from_path(path) or "messenger"
    if plat not in ("facebook", "messenger", "instagram", "threads"):
        plat = "messenger"
    chat = fix_meta(d.get("title") or d.get("threadName") or "")
    if not chat and isinstance(d.get("participants"), list):
        names = [fix_meta(p.get("name") if isinstance(p, dict) else p) for p in d["participants"]]
        chat = ", ".join(n for n in names if n)
    segs = []
    for m in msgs:
        sender = fix_meta(m.get("sender_name") or m.get("senderName") or "")
        text = fix_meta(m.get("content") or m.get("text") or "")
        share = m.get("share") or {}
        if isinstance(share, dict) and share.get("link"):
            text = (text + " " if text else "") + f"[tautan: {share['link']}]"
        ref = _media_refs(m)
        if ref and not text:
            text = f"[media: {Path(ref).name}]"
        if not text:
            continue
        segs.append(_seg(plat, text, m.get("timestamp_ms") or m.get("timestamp"), chat, sender, ref))
    return segs


def parse_telegram_json(d: dict) -> Optional[list[dict]]:
    chats = []
    if isinstance(d.get("chats"), dict) and isinstance(d["chats"].get("list"), list):
        chats = d["chats"]["list"]
    elif isinstance(d.get("messages"), list) and ("type" in d or "name" in d):
        chats = [d]
    if not chats:
        return None
    sample = next((m for c in chats for m in c.get("messages", []) if isinstance(m, dict)), None)
    if sample is None or "date" not in sample or "type" not in sample:
        return None
    segs = []
    for c in chats:
        name = c.get("name") or str(c.get("id", ""))
        for m in c.get("messages", []):
            if not isinstance(m, dict):
                continue
            text = _text_of(m.get("text"))
            ref = _media_refs(m)
            if m.get("type") == "service":
                text = text or str(m.get("action", ""))
            if ref and not text:
                text = f"[media: {Path(ref).name}]"
            if not text.strip():
                continue
            sender = m.get("from") or m.get("actor") or ""
            segs.append(_seg("telegram", text, m.get("date"), name, sender, ref))
    return segs


_TG_MSG = re.compile(r'<div class="message (?:default|service)[^"]*"[^>]*id="message-?\d+"[^>]*>(.*?)(?=<div class="message |\Z)',
                     re.S)


def parse_telegram_html(html: str) -> Optional[list[dict]]:
    if 'class="page_header"' not in html or 'class="message default' not in html:
        return None
    chat = ""
    mh = re.search(r'<div class="page_header">.*?<div class="text bold">\s*(.*?)\s*</div>', html, re.S)
    if mh:
        chat = unescape(re.sub(r"<[^>]+>", "", mh.group(1))).strip()
    segs = []
    last_sender = ""
    for block in _TG_MSG.findall(html):
        mdate = re.search(r'class="pull_right date details" title="([^"]+)"', block)
        mfrom = re.search(r'<div class="from_name">\s*(.*?)\s*</div>', block, re.S)
        mtext = re.search(r'<div class="text">\s*(.*?)\s*</div>', block, re.S)
        mref = re.search(r'href="((?:photos|video_files|voice_messages|files|round_video_messages)/[^"]+)"', block)
        if mfrom:
            last_sender = unescape(re.sub(r"<[^>]+>", "", mfrom.group(1))).strip()
        text = unescape(re.sub(r"<br\s*/?>", "\n", mtext.group(1))) if mtext else ""
        text = re.sub(r"<[^>]+>", "", text).strip()
        ref = mref.group(1) if mref else None
        if ref and not text:
            text = f"[media: {Path(ref).name}]"
        if text:
            segs.append(_seg("telegram", text, mdate.group(1) if mdate else None, chat, last_sender, ref))
    return segs


def parse_twitter_js(raw: str, path: str) -> Optional[list[dict]]:
    m = re.match(r"\s*window\.YTD\.([\w.]+?)\.part\d+\s*=\s*", raw)
    if not m:
        return None
    try:
        data = json.loads(raw[m.end():])
    except json.JSONDecodeError:
        return None
    name = m.group(1)
    segs = []
    for item in data if isinstance(data, list) else []:
        if not isinstance(item, dict):
            continue
        if "dmConversation" in item:
            conv = item["dmConversation"]
            cid = conv.get("conversationId", "")
            for msg in conv.get("messages", []):
                mc = msg.get("messageCreate") or {}
                text = mc.get("text") or ""
                ref = (mc.get("mediaUrls") or [None])[0]
                if text or ref:
                    segs.append(_seg("twitter", text or f"[media: {ref}]", mc.get("createdAt"), f"DM {cid}",
                                     f"id {mc.get('senderId', '?')}", ref, "DM"))
        elif "tweet" in item:
            t = item["tweet"]
            media = ((t.get("extended_entities") or t.get("entities") or {}).get("media") or [{}])[0]
            segs.append(_seg("twitter", t.get("full_text") or t.get("text") or "", t.get("created_at"),
                             "", "", media.get("media_url_https"), "tweet"))
        elif "like" in item:
            lk = item["like"]
            if lk.get("fullText"):
                segs.append(_seg("twitter", lk["fullText"], None, "", "", None, "like"))
        else:
            segs.extend(walk_json(item, "twitter", label_kind=name))
    return [s for s in segs if s["text"]]


def parse_discord(d: Any, path: str) -> Optional[list[dict]]:
    # DiscordChatExporter
    if isinstance(d, dict) and isinstance(d.get("messages"), list) and isinstance(d.get("channel"), dict):
        ch = d["channel"].get("name") or ""
        g = (d.get("guild") or {}).get("name") or ""
        chat = f"{g} #{ch}" if g else ch
        segs = []
        for m in d["messages"]:
            a = m.get("author") or {}
            ref = _media_refs(m)
            text = m.get("content") or (f"[media: {ref}]" if ref else "")
            if text:
                segs.append(_seg("discord", text, m.get("timestamp"), chat, a.get("nickname") or a.get("name") or "", ref))
        return segs
    # Discord data package: messages/c<ID>/messages.json -> [{"ID","Timestamp","Contents","Attachments"}]
    if isinstance(d, list) and d and isinstance(d[0], dict) and {"ID", "Timestamp", "Contents"} <= set(d[0]):
        return [_seg("discord", m.get("Contents") or "", m.get("Timestamp"), _discord_channel(path), "Pemilik akun",
                     (m.get("Attachments") or None)) for m in d if (m.get("Contents") or m.get("Attachments"))]
    return None


def _discord_channel(path: str) -> str:
    ch = Path(path).with_name("channel.json")
    if ch.exists():
        try:
            c = json.loads(ch.read_text(encoding="utf-8"))
            name = c.get("name") or ""
            g = (c.get("guild") or {}).get("name") or ""
            if g or name:
                return f"{g} #{name}".strip()
            rec = c.get("recipients")
            if rec:
                return "DM " + ", ".join(map(str, rec))
        except (OSError, ValueError):
            pass
    return Path(path).parent.name


def parse_csv_messages(text: str, path: str) -> Optional[list[dict]]:
    try:
        rows = list(csv.reader(io.StringIO(text)))
    except csv.Error:
        return None
    if len(rows) < 2:
        return None
    head = [h.strip().lower() for h in rows[0]]

    def idx(*names):
        for n in names:
            if n in head:
                return head.index(n)
        return None
    it = idx("content", "contents", "text", "message", "body")
    if it is None:
        return None
    isd = idx("from", "sender", "author", "sender_name", "username")
    itm = idx("date", "timestamp", "created", "created_at", "time")
    ich = idx("conversation title", "channel", "conversation", "chat", "thread")
    plat = detect_platform_from_path(path) or ("linkedin" if "conversation id" in head else
                                               "discord" if head[:3] == ["id", "timestamp", "contents"] else "social")
    if plat == "discord" and ich is None:
        chat_default = _discord_channel(path)
    else:
        chat_default = ""
    segs = []
    for i, r in enumerate(rows[1:], 2):
        if it >= len(r) or not r[it].strip():
            continue
        g = (lambda k: r[k] if k is not None and k < len(r) else "")
        seg = _seg(plat, r[it], g(itm) or None, g(ich) or chat_default, g(isd))
        seg["page"] = i
        segs.append(seg)
    return segs


def parse_sms_xml(text: str) -> Optional[list[dict]]:
    if "<smses" not in text[:2000] and "<calls" not in text[:2000]:
        return None
    try:
        root = ET.fromstring(text)
    except ET.ParseError:
        return None
    segs = []
    for el in root.iter():
        a = el.attrib
        who = a.get("contact_name") if a.get("contact_name") not in (None, "(Unknown)") else ""
        num = a.get("address") or a.get("number") or ""
        party = f"{who} ({num})" if who else num
        if el.tag == "sms" and a.get("body"):
            sender = "Saya (pemilik HP)" if a.get("type") == "2" else party
            segs.append(_seg("sms", a["body"], a.get("date"), party, sender))
        elif el.tag == "mms":
            texts = [p.attrib.get("text", "") for p in el.iter("part") if p.attrib.get("ct") == "text/plain"]
            if any(texts):
                sender = "Saya (pemilik HP)" if a.get("msg_box") == "2" else party
                segs.append(_seg("sms", " ".join(texts), a.get("date"), party, sender, None, "MMS"))
        elif el.tag == "call":
            jenis = {"1": "masuk", "2": "keluar", "3": "tak terjawab", "5": "ditolak"}.get(a.get("type", ""), a.get("type", ""))
            segs.append(_seg("sms", f"Panggilan {jenis} {party}, durasi {a.get('duration', '?')} detik",
                             a.get("date"), party, "", None, "panggilan"))
    return segs


# ---------------------------------------------------------------------------
# Pembaca JSON umum: cari objek yang "berbentuk pesan/postingan"
# ---------------------------------------------------------------------------
def walk_json(node: Any, platform: str, label_kind: str = "", ctx: str = "", max_items: int = 500_000,
              meta_fix: bool = False) -> list[dict]:
    out: list[dict] = []

    def fx(v):
        return fix_meta(v) if meta_fix else v

    def rec(n, ctx_name, depth):
        if len(out) >= max_items or depth > 40:
            return
        if isinstance(n, dict):
            name = next((n[k] for k in NAME_KEYS if isinstance(n.get(k), str) and n.get(k)), None)
            ctx_here = fx(name) if name else ctx_name
            text = next((n[k] for k in TEXT_KEYS if isinstance(n.get(k), (str, list)) and _text_of(n.get(k)).strip()), None)
            when = next((n[k] for k in TIME_KEYS if n.get(k) not in (None, "")), None)
            if text is None and when is not None and isinstance(n.get("title"), str) and n["title"].strip():
                text = n["title"]  # postingan Meta/Threads: isi tersimpan di "title"
            if text is not None:
                sender = ""
                for k in SENDER_KEYS:
                    v = n.get(k)
                    if isinstance(v, dict):
                        v = v.get("name") or v.get("username") or v.get("email") or ""
                    if isinstance(v, str) and v:
                        sender = v
                        break
                seg = _seg(platform, fx(_text_of(text)), when, ctx_name if ctx_name != fx(_text_of(text)) else "",
                           fx(sender), _media_refs(n), label_kind)
                if len(seg["text"]) >= 2:
                    out.append(seg)
            for k, v in n.items():
                if isinstance(v, (dict, list)):
                    sub_ctx = ctx_here
                    if isinstance(k, str) and len(k) < 120 and re.search(r"(?i)chat|with|dengan|history|conversation", k):
                        sub_ctx = k.rstrip(":")
                    rec(v, sub_ctx, depth + 1)
        elif isinstance(n, list):
            for x in n:
                rec(x, ctx_name, depth + 1)
    rec(node, ctx, 0)
    return out


# ---------------------------------------------------------------------------
# Titik masuk untuk extractors.extract_document
# ---------------------------------------------------------------------------
def parse_social_file(path: str, ext: str, text: str) -> Optional[list[dict]]:
    """Kembalikan segmen bila file dikenali sebagai export media sosial/pesan; else None."""
    if ext == ".js" or text.lstrip().startswith("window.YTD."):
        return parse_twitter_js(text, path)
    if ext == ".html" or ext == ".htm":
        return parse_telegram_html(text)
    if ext == ".xml":
        return parse_sms_xml(text)
    if ext in (".csv", ".tsv"):
        return parse_csv_messages(text, path)
    if ext == ".json":
        try:
            d = json.loads(text)
        except json.JSONDecodeError:
            return None
        for fn in (lambda: parse_meta_messages(d, path) if isinstance(d, dict) else None,
                   lambda: parse_telegram_json(d) if isinstance(d, dict) else None,
                   lambda: parse_discord(d, path)):
            r = fn()
            if r:
                return r
        plat = detect_platform_from_path(path) or "social"
        is_meta = plat in ("facebook", "messenger", "instagram", "threads")
        segs = walk_json(d, plat, meta_fix=is_meta)
        # hanya dipakai bila benar-benar berisi teks bermakna (bukan file konfigurasi)
        if segs and (plat != "social" or len(segs) >= 1):
            return segs
    return None


def describe_sources() -> dict[str, str]:
    return {k: f"{v} (pesan/postingan)" for k, v in PLATFORM_LABEL.items()}


_ = datetime, timezone  # (disediakan untuk perluasan format waktu)
