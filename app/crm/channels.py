"""Внешние каналы: веб-формы сайта, телефония (webhook), Telegram-бот,
почта (IMAP/SMTP), произвольный HTTP-провайдер (WhatsApp и др. через сервис-посредник).

Входящие обращения превращаются в контакт + сделку + событие в ленте.
Опрос Telegram и почты выполняется фоновым потоком (работает без «белого» IP).
"""
from __future__ import annotations

import email
import email.header
import email.utils
import imaplib
import json
import logging
import smtplib
import ssl
import threading
import time
import urllib.request
from email.message import EmailMessage

from ..db import dumps, now_iso, session
from .service import (add_event, create_deal, create_task, due_from, find_or_create_contact, get,
                      open_deal_of_contact, rows)

log = logging.getLogger("glasscad.channels")

CHANNEL_KINDS = {
    "form": "Заявки с сайта / веб-форма",
    "telephony": "Телефония (webhook звонков)",
    "telegram": "Telegram-бот",
    "email": "Почта (IMAP / SMTP)",
    "http": "WhatsApp / другой мессенджер через провайдера (HTTP)",
}
SECRET_KEYS = {"bot_token", "imap_password", "smtp_password", "auth_header"}
MASK = "••••••"

ALIASES = {
    "name": ("name", "fio", "имя", "фио", "client", "contact_name", "your-name"),
    "phone": ("phone", "tel", "телефон", "phone_number", "caller", "from_number", "client_phone", "your-phone"),
    "email": ("email", "mail", "почта", "e-mail", "your-email"),
    "text": ("text", "message", "comment", "сообщение", "комментарий", "body", "your-message"),
}


def mask_config(cfg: dict) -> dict:
    return {k: (MASK if k in SECRET_KEYS and v else v) for k, v in (cfg or {}).items()}


def merge_config(old: dict, new: dict) -> dict:
    out = dict(old or {})
    for k, v in (new or {}).items():
        if k in SECRET_KEYS and v == MASK:
            continue
        out[k] = v
    return out


def _pick(payload: dict, key: str) -> str:
    low = {str(k).lower(): v for k, v in payload.items()}
    for alias in ALIASES[key]:
        v = low.get(alias)
        if v not in (None, ""):
            return str(v).strip()
    return ""


def _deal_for(c, channel: dict, contact: dict, *, author: str, source: str) -> dict:
    cfg = channel.get("data") or {}
    deal = None if cfg.get("always_new_deal") else open_deal_of_contact(c, contact["id"])
    if deal:
        return deal
    return create_deal(c, {"contact_id": contact["id"], "pipeline_id": cfg.get("pipeline_id") or None,
                           "stage_id": cfg.get("stage_id") or None, "source": source,
                           "responsible_id": cfg.get("responsible_id") or None}, author=author)


# ------------------------------------------------------------------ входящие webhook
def handle_inbound(c, channel: dict, payload: dict) -> dict:
    kind = channel["kind"]
    src = channel["name"]
    if kind == "telephony":
        return _handle_call(c, channel, payload)
    name, phone, mail, text = (_pick(payload, k) for k in ("name", "phone", "email", "text"))
    if not (phone or mail or name):
        raise ValueError("В заявке нет имени, телефона или e-mail")
    contact, _ = find_or_create_contact(c, name=name, phone=phone, email=mail, source=src)
    deal = _deal_for(c, channel, contact, author=src, source=src)
    extra = {k: v for k, v in payload.items() if str(k).lower().startswith("utm_") or k in ("page", "form", "url")}
    body = text or "Заявка без текста"
    add_event(c, deal_id=deal["id"], contact_id=contact["id"], kind="message_in", text=body,
              data={"channel_id": channel["id"], "channel": src, "fields": extra}, author=src)
    if (channel.get("data") or {}).get("task_text"):
        create_task(c, {"text": channel["data"]["task_text"], "kind": "call", "due_at": due_from(hours=1),
                        "deal_id": deal["id"], "contact_id": contact["id"],
                        "responsible_id": deal.get("responsible_id")}, author=src)
    return {"ok": True, "contact_id": contact["id"], "deal_id": deal["id"]}


def _handle_call(c, channel: dict, p: dict) -> dict:
    cfg = channel.get("data") or {}
    phone = _pick(p, "phone")
    direction = str(p.get("direction") or p.get("type") or "in").lower()
    direction = "out" if direction in ("out", "outgoing", "исходящий") else "in"
    status = str(p.get("status") or p.get("disposition") or "answered").lower()
    missed = status in ("missed", "noanswer", "no_answer", "busy", "cancel", "пропущен", "failed")
    duration = int(float(p.get("duration") or p.get("billsec") or 0))
    record = p.get("record_url") or p.get("recording") or p.get("record") or ""
    contact, created = find_or_create_contact(c, phone=phone, name=_pick(p, "name"), source=channel["name"])
    deal = open_deal_of_contact(c, contact["id"])
    if not deal and direction == "in" and (created or cfg.get("create_deal", True)):
        deal = _deal_for(c, channel, contact, author=channel["name"], source=channel["name"])
    mm, ss = divmod(duration, 60)
    text = f"{'Входящий' if direction == 'in' else 'Исходящий'} звонок · " + ("пропущен" if missed else f"{mm}:{ss:02d}")
    add_event(c, deal_id=deal["id"] if deal else None, contact_id=contact["id"], kind="call", text=text,
              data={"phone": phone, "direction": direction, "missed": missed, "duration": duration,
                    "record_url": record, "channel_id": channel["id"]}, author=channel["name"])
    if missed and direction == "in":
        create_task(c, {"text": f"Перезвонить {contact['name']} ({phone})", "kind": "call", "due_at": due_from(hours=0.25),
                        "deal_id": deal["id"] if deal else None, "contact_id": contact["id"],
                        "responsible_id": deal.get("responsible_id") if deal else None}, author=channel["name"])
    return {"ok": True, "contact_id": contact["id"], "deal_id": deal["id"] if deal else None}


# ------------------------------------------------------------------ отправка
def _http(url: str, *, data: dict | None = None, headers: dict | None = None, timeout=20) -> dict:
    body = json.dumps(data).encode() if data is not None else None
    req = urllib.request.Request(url, data=body, headers={"Content-Type": "application/json", **(headers or {})},
                                 method="POST" if body is not None else "GET")
    with urllib.request.urlopen(req, timeout=timeout) as r:
        raw = r.read().decode("utf-8", "replace")
    try:
        return json.loads(raw) if raw else {}
    except json.JSONDecodeError:
        return {"raw": raw[:500]}


def _tg(cfg: dict, method: str, params: dict | None = None, timeout=20) -> dict:
    token = cfg.get("bot_token") or ""
    if not token:
        raise ValueError("Не задан токен Telegram-бота")
    url = f"https://api.telegram.org/bot{token}/{method}"
    res = _http(url, data=params or {}, timeout=timeout)
    if not res.get("ok"):
        raise ValueError(f"Telegram: {res.get('description') or res}")
    return res


def _smtp_send(cfg: dict, to: str, subject: str, text: str) -> None:
    msg = EmailMessage()
    msg["From"] = cfg.get("from") or cfg.get("smtp_user")
    msg["To"] = to
    msg["Subject"] = subject
    msg.set_content(text)
    host, port = cfg.get("smtp_host"), int(cfg.get("smtp_port") or 465)
    if not host:
        raise ValueError("Не задан SMTP-сервер")
    ctx = ssl.create_default_context()
    if port == 465:
        s = smtplib.SMTP_SSL(host, port, timeout=30, context=ctx)
    else:
        s = smtplib.SMTP(host, port, timeout=30)
        s.starttls(context=ctx)
    try:
        if cfg.get("smtp_user"):
            s.login(cfg["smtp_user"], cfg.get("smtp_password") or "")
        s.send_message(msg)
    finally:
        s.quit()


def _http_send(cfg: dict, phone: str, text: str, contact: dict) -> None:
    url = cfg.get("send_url")
    if not url:
        raise ValueError("Не задан адрес отправки (send_url) провайдера")
    headers = {}
    ah = cfg.get("auth_header") or ""
    if ":" in ah:
        k, v = ah.split(":", 1)
        headers[k.strip()] = v.strip()
    _http(url, data={"to": phone, "phone": phone, "text": text, "name": contact["name"]}, headers=headers)


def active_channels(c, kind: str | None = None) -> list[dict]:
    sql, args = "SELECT * FROM channels WHERE active=1", []
    if kind:
        sql += " AND kind=?"
        args.append(kind)
    return rows(c.execute(sql + " ORDER BY created_at", args).fetchall())


def send_to_contact(c, deal_id: str | None, text: str, *, contact_id: str | None = None, channel_id: str | None = None,
                    subject: str = "", author: str = "") -> dict:
    deal = get(c, "deals", deal_id) if deal_id else None
    cid = contact_id or (deal or {}).get("contact_id")
    contact = get(c, "contacts", cid) if cid else None
    if not contact:
        raise ValueError("У сделки нет контакта")
    if not text.strip():
        raise ValueError("Пустое сообщение")
    cdata = contact.get("data") or {}
    candidates = [get(c, "channels", channel_id)] if channel_id else active_channels(c)
    chosen = None
    for ch in candidates:
        if not ch:
            continue
        if ch["kind"] == "telegram" and cdata.get("telegram_chat_id"):
            chosen = ch
            break
        if ch["kind"] == "http" and contact["phone"]:
            chosen = ch
            break
        if ch["kind"] == "email" and contact["email"]:
            chosen = ch
            break
    if not chosen:
        raise ValueError("Нет подходящего канала: у контакта нет Telegram/телефона/e-mail или канал не настроен")
    cfg = chosen.get("data") or {}
    if chosen["kind"] == "telegram":
        _tg(cfg, "sendMessage", {"chat_id": cdata["telegram_chat_id"], "text": text})
        kind = "message_out"
    elif chosen["kind"] == "email":
        _smtp_send(cfg, contact["email"], subject or (deal["name"] if deal else "Сообщение"), text)
        kind = "email_out"
    else:
        _http_send(cfg, contact["phone"], text, contact)
        kind = "message_out"
    return add_event(c, deal_id=deal_id, contact_id=contact["id"], kind=kind, text=text,
                     data={"channel_id": chosen["id"], "channel": chosen["name"], "subject": subject}, author=author)


# ------------------------------------------------------------------ опрос (Telegram, почта)
def _set_state(c, ch_id: str, **kw) -> None:
    cur = get(c, "channels", ch_id)
    st = dict(cur.get("state") or {})
    st.update(kw)
    c.execute("UPDATE channels SET state=? WHERE id=?", (dumps(st), ch_id))


def poll_telegram(c, ch: dict) -> int:
    cfg, st = ch.get("data") or {}, ch.get("state") or {}
    res = _tg(cfg, "getUpdates", {"offset": int(st.get("offset") or 0), "timeout": 0,
                                  "allowed_updates": ["message"]}, timeout=25)
    n = 0
    offset = int(st.get("offset") or 0)
    for upd in res.get("result", []):
        offset = max(offset, int(upd["update_id"]) + 1)
        msg = upd.get("message") or {}
        chat = msg.get("chat") or {}
        if not chat.get("id"):
            continue
        frm = msg.get("from") or {}
        name = " ".join(x for x in (frm.get("first_name"), frm.get("last_name")) if x) or frm.get("username") or "Telegram"
        text = msg.get("text") or msg.get("caption") or "[вложение]"
        phone = (msg.get("contact") or {}).get("phone_number") or ""
        contact, _ = find_or_create_contact(c, name=name, phone=phone, source=ch["name"],
                                            data={"telegram_chat_id": str(chat["id"]), "telegram_username": frm.get("username") or ""})
        deal = _deal_for(c, ch, contact, author=ch["name"], source=ch["name"])
        add_event(c, deal_id=deal["id"], contact_id=contact["id"], kind="message_in", text=text,
                  data={"channel_id": ch["id"], "channel": ch["name"]}, author=name)
        n += 1
    _set_state(c, ch["id"], offset=offset, last_ok=now_iso(), last_error="")
    return n


def _decode(s) -> str:
    parts = email.header.decode_header(s or "")
    return "".join(p.decode(enc or "utf-8", "replace") if isinstance(p, bytes) else p for p, enc in parts)


def _body(msg) -> str:
    if msg.is_multipart():
        for part in msg.walk():
            if part.get_content_type() == "text/plain" and "attachment" not in str(part.get("Content-Disposition") or ""):
                return part.get_payload(decode=True).decode(part.get_content_charset() or "utf-8", "replace")
        return ""
    return msg.get_payload(decode=True).decode(msg.get_content_charset() or "utf-8", "replace")


def poll_email(c, ch: dict) -> int:
    cfg = ch.get("data") or {}
    host = cfg.get("imap_host")
    if not host:
        raise ValueError("Не задан IMAP-сервер")
    m = imaplib.IMAP4_SSL(host, int(cfg.get("imap_port") or 993))
    n = 0
    try:
        m.login(cfg.get("imap_user") or "", cfg.get("imap_password") or "")
        m.select(cfg.get("imap_folder") or "INBOX")
        _typ, data = m.search(None, "UNSEEN")
        for num in (data[0].split() if data and data[0] else [])[:25]:
            _t, msgdata = m.fetch(num, "(RFC822)")
            msg = email.message_from_bytes(msgdata[0][1])
            name, addr = email.utils.parseaddr(_decode(msg.get("From")))
            subject = _decode(msg.get("Subject"))
            contact, _ = find_or_create_contact(c, name=name, email=addr, source=ch["name"])
            deal = _deal_for(c, ch, contact, author=ch["name"], source=ch["name"])
            add_event(c, deal_id=deal["id"], contact_id=contact["id"], kind="email_in",
                      text=(f"{subject}\n\n" if subject else "") + _body(msg)[:5000],
                      data={"channel_id": ch["id"], "channel": ch["name"], "subject": subject, "from": addr}, author=name or addr)
            n += 1
    finally:
        try:
            m.logout()
        except Exception:  # noqa: BLE001
            pass
    _set_state(c, ch["id"], last_ok=now_iso(), last_error="")
    return n


def poll_channel(ch_id: str) -> int:
    with session() as c:
        ch = get(c, "channels", ch_id)
        try:
            if ch["kind"] == "telegram":
                return poll_telegram(c, ch)
            if ch["kind"] == "email":
                return poll_email(c, ch)
            return 0
        except Exception as e:  # noqa: BLE001
            _set_state(c, ch_id, last_error=f"{now_iso()}: {e}")
            raise


class Poller(threading.Thread):
    """Фоновый опрос каналов. Telegram — каждые ~15 с, почта — по настройке (по умолчанию 120 с)."""

    def __init__(self):
        super().__init__(daemon=True, name="glasscad-poller")
        self.stop_event = threading.Event()
        self.last: dict[str, float] = {}

    def run(self):
        while not self.stop_event.wait(15):
            try:
                with session() as c:
                    chans = [ch for ch in active_channels(c) if ch["kind"] in ("telegram", "email")]
                for ch in chans:
                    interval = 15 if ch["kind"] == "telegram" else max(30, int((ch["data"] or {}).get("poll_seconds") or 120))
                    if time.time() - self.last.get(ch["id"], 0) < interval:
                        continue
                    self.last[ch["id"]] = time.time()
                    try:
                        poll_channel(ch["id"])
                    except Exception as e:  # noqa: BLE001
                        log.warning("Канал %s: %s", ch["name"], e)
            except Exception as e:  # noqa: BLE001
                log.warning("Опрос каналов: %s", e)


def form_snippet(base_url: str, ch: dict) -> str:
    url = f"{base_url.rstrip('/')}/api/inbound/{ch['id']}/{ch['token']}"
    return f"""<form id="glasscad-form" style="display:grid;gap:8px;max-width:360px">
  <input name="name" placeholder="Ваше имя" required>
  <input name="phone" placeholder="Телефон" required>
  <textarea name="message" placeholder="Размеры проёма, пожелания"></textarea>
  <button type="submit">Вызвать замерщика</button>
</form>
<script>
document.getElementById('glasscad-form').addEventListener('submit', async (e) => {{
  e.preventDefault();
  const data = Object.fromEntries(new FormData(e.target));
  data.page = location.href;
  new URLSearchParams(location.search).forEach((v, k) => {{ if (k.startsWith('utm_')) data[k] = v; }});
  await fetch('{url}', {{ method: 'POST', headers: {{ 'Content-Type': 'application/json' }}, body: JSON.stringify(data) }});
  e.target.innerHTML = '<p>Спасибо! Мы перезвоним.</p>';
}});
</script>"""

