"""Бизнес-логика CRM: контакты, сделки, этапы, лента событий, задачи, автоматизация.

Все функции работают в одной транзакции с переданным соединением `c`,
API-слой только разбирает запросы.
"""
from __future__ import annotations

import json
import re
import sqlite3
from datetime import datetime, timedelta
from typing import Any

from ..db import dumps, new_id, now_iso

TASK_KINDS = {
    "call": "Позвонить", "measure": "Замер", "meeting": "Встреча", "install": "Монтаж",
    "email": "Написать", "other": "Другое",
}
EVENT_KINDS = {
    "note": "Примечание", "created": "Создано", "stage": "Смена этапа", "task_done": "Задача выполнена",
    "message_in": "Входящее сообщение", "message_out": "Исходящее сообщение", "call": "Звонок",
    "email_in": "Входящее письмо", "email_out": "Исходящее письмо", "system": "Система", "field": "Изменение",
}
AUTOMATION_TRIGGERS = {
    "stage_enter": "Сделка перешла на этап", "deal_created": "Создана сделка",
    "deal_won": "Сделка успешна", "deal_lost": "Сделка не реализована",
}
AUTOMATION_ACTIONS = {
    "create_task": "Создать задачу", "add_note": "Добавить примечание", "set_order_status": "Сменить статус заказа",
    "create_order": "Создать заказ из сделки", "set_responsible": "Назначить ответственного",
    "send_message": "Отправить сообщение клиенту", "move_stage": "Перевести на этап",
}


def row(r: sqlite3.Row | None) -> dict | None:
    if r is None:
        return None
    d = dict(r)
    for k in ("data", "state"):
        if k in d:
            try:
                d[k] = json.loads(d[k] or "{}")
            except json.JSONDecodeError:
                d[k] = {}
    return d


def rows(rs) -> list[dict]:
    return [row(r) for r in rs]


def norm_phone(phone: str | None) -> str:
    digits = re.sub(r"\D", "", phone or "")
    if len(digits) == 11 and digits[0] in "78":
        digits = "7" + digits[1:]
    elif len(digits) == 10:
        digits = "7" + digits
    return digits


# ------------------------------------------------------------------ универсальные операции
TABLE_FIELDS: dict[str, tuple[str, ...]] = {
    "crm_users": ("name", "color", "active"),
    "companies": ("name", "phone", "email", "address", "inn", "comment"),
    "contacts": ("name", "phone", "email", "company_id", "position", "comment"),
    "pipelines": ("name", "position"),
    "stages": ("pipeline_id", "name", "color", "position", "kind"),
    "deals": ("name", "pipeline_id", "stage_id", "amount", "contact_id", "company_id", "order_id",
              "responsible_id", "source", "tags", "comment"),
    "tasks": ("text", "kind", "due_at", "done", "result", "deal_id", "contact_id", "responsible_id"),
    "automations": ("name", "active", "trigger", "stage_id"),
    "channels": ("name", "kind", "active", "token"),
}
HAS_DATA = {"crm_users", "companies", "contacts", "deals", "tasks", "automations", "channels"}


def get(c, table: str, rid: str) -> dict | None:
    return row(c.execute(f"SELECT * FROM {table} WHERE id=?", (rid,)).fetchone())


def insert(c, table: str, values: dict, rid: str | None = None) -> dict:
    fields = TABLE_FIELDS[table]
    rid = rid or new_id()
    ts = now_iso()
    cols = ["id"] + [f for f in fields if f in values] + ["created_at", "updated_at"]
    vals = [rid] + [values[f] for f in fields if f in values] + [ts, ts]
    if table in HAS_DATA:
        cols.append("data")
        vals.append(dumps(values.get("data") or {}))
    if table == "contacts":
        cols.append("phone_norm")
        vals.append(norm_phone(values.get("phone")))
    c.execute(f"INSERT INTO {table}({', '.join(cols)}) VALUES ({', '.join('?' * len(cols))})", vals)
    return get(c, table, rid)


def update(c, table: str, rid: str, values: dict) -> dict | None:
    cur = get(c, table, rid)
    if not cur:
        return None
    sets, vals = [], []
    for f in TABLE_FIELDS[table]:
        if f in values:
            sets.append(f"{f}=?")
            vals.append(values[f])
    if table in HAS_DATA and "data" in values and values["data"] is not None:
        merged = dict(cur.get("data") or {})
        merged.update(values["data"])
        sets.append("data=?")
        vals.append(dumps(merged))
    if table == "contacts" and "phone" in values:
        sets.append("phone_norm=?")
        vals.append(norm_phone(values["phone"]))
    sets.append("updated_at=?")
    vals.append(now_iso())
    c.execute(f"UPDATE {table} SET {', '.join(sets)} WHERE id=?", (*vals, rid))
    return get(c, table, rid)


# ------------------------------------------------------------------ лента событий
def add_event(c, *, deal_id=None, contact_id=None, kind="note", text="", data=None, author="") -> dict:
    eid = new_id()
    c.execute("INSERT INTO events(id, deal_id, contact_id, kind, text, data, author, created_at) VALUES (?,?,?,?,?,?,?,?)",
              (eid, deal_id, contact_id, kind, text, dumps(data or {}), author, now_iso()))
    return row(c.execute("SELECT * FROM events WHERE id=?", (eid,)).fetchone())


# ------------------------------------------------------------------ контакты
def find_contact(c, *, phone=None, email=None, telegram_chat_id=None) -> dict | None:
    if telegram_chat_id:
        r = c.execute("SELECT * FROM contacts WHERE json_extract(data, '$.telegram_chat_id')=?",
                      (str(telegram_chat_id),)).fetchone()
        if r:
            return row(r)
    pn = norm_phone(phone)
    if len(pn) >= 6:
        r = c.execute("SELECT * FROM contacts WHERE phone_norm=? ORDER BY created_at LIMIT 1", (pn,)).fetchone()
        if r:
            return row(r)
    if email:
        r = c.execute("SELECT * FROM contacts WHERE lower(email)=lower(?) ORDER BY created_at LIMIT 1", (email.strip(),)).fetchone()
        if r:
            return row(r)
    return None


def find_or_create_contact(c, *, name="", phone="", email="", data=None, source="") -> tuple[dict, bool]:
    tg = (data or {}).get("telegram_chat_id")
    cur = find_contact(c, phone=phone, email=email, telegram_chat_id=tg)
    if cur:
        patch: dict[str, Any] = {}
        if phone and not cur["phone"]:
            patch["phone"] = phone
        if email and not cur["email"]:
            patch["email"] = email
        if name and not cur["name"]:
            patch["name"] = name
        if data:
            patch["data"] = data
        if patch:
            cur = update(c, "contacts", cur["id"], patch)
        return cur, False
    d = dict(data or {})
    if source:
        d["source"] = source
    return insert(c, "contacts", {"name": name or phone or email or "Новый контакт", "phone": phone or "",
                                  "email": email or "", "data": d}), True


# ------------------------------------------------------------------ сделки
def default_pipeline(c) -> dict | None:
    return row(c.execute("SELECT * FROM pipelines ORDER BY position, created_at LIMIT 1").fetchone())


def first_stage(c, pipeline_id: str) -> dict | None:
    return row(c.execute("SELECT * FROM stages WHERE pipeline_id=? AND kind='open' ORDER BY position LIMIT 1",
                         (pipeline_id,)).fetchone())


def open_deal_of_contact(c, contact_id: str) -> dict | None:
    return row(c.execute(
        """SELECT d.* FROM deals d JOIN stages s ON s.id=d.stage_id
           WHERE d.contact_id=? AND s.kind='open' ORDER BY d.updated_at DESC LIMIT 1""", (contact_id,)).fetchone())


def create_deal(c, values: dict, author="") -> dict:
    v = dict(values)
    if not v.get("pipeline_id"):
        p = default_pipeline(c)
        v["pipeline_id"] = p["id"] if p else None
    if not v.get("stage_id") and v.get("pipeline_id"):
        st = first_stage(c, v["pipeline_id"])
        v["stage_id"] = st["id"] if st else None
    if not v.get("responsible_id"):
        u = c.execute("SELECT id FROM crm_users WHERE active=1 ORDER BY created_at LIMIT 1").fetchone()
        v["responsible_id"] = u["id"] if u else None
    if not v.get("name"):
        contact = get(c, "contacts", v["contact_id"]) if v.get("contact_id") else None
        v["name"] = f"Сделка — {contact['name']}" if contact else "Новая сделка"
    if v.get("contact_id") and not v.get("company_id"):
        contact = get(c, "contacts", v["contact_id"])
        if contact and contact.get("company_id"):
            v["company_id"] = contact["company_id"]
    deal = insert(c, "deals", v)
    c.execute("UPDATE deals SET stage_changed_at=? WHERE id=?", (now_iso(), deal["id"]))
    stage = get(c, "stages", deal["stage_id"]) if deal["stage_id"] else None
    add_event(c, deal_id=deal["id"], contact_id=deal["contact_id"], kind="created",
              text=f"Сделка создана{(' на этапе «' + stage['name'] + '»') if stage else ''}",
              data={"to_stage": deal["stage_id"], "source": deal["source"]}, author=author)
    run_automations(c, "deal_created", deal["id"], author=author)
    if stage:
        run_automations(c, "stage_enter", deal["id"], stage_id=stage["id"], author=author)
    return get(c, "deals", deal["id"])


def move_deal(c, deal_id: str, stage_id: str, author="", reason: str = "", _depth: int = 0) -> dict:
    deal = get(c, "deals", deal_id)
    if not deal or deal["stage_id"] == stage_id:
        return deal
    old = get(c, "stages", deal["stage_id"]) if deal["stage_id"] else None
    new = get(c, "stages", stage_id)
    if not new:
        raise ValueError("Этап не найден")
    ts = now_iso()
    closed_at = ts if new["kind"] in ("won", "lost") else None
    c.execute("UPDATE deals SET stage_id=?, pipeline_id=?, stage_changed_at=?, closed_at=?, updated_at=? WHERE id=?",
              (stage_id, new["pipeline_id"], ts, closed_at, ts, deal_id))
    if reason:
        update(c, "deals", deal_id, {"data": {"lost_reason": reason}})
    add_event(c, deal_id=deal_id, contact_id=deal["contact_id"], kind="stage",
              text=f"Этап: {old['name'] if old else '—'} → {new['name']}" + (f" (причина: {reason})" if reason else ""),
              data={"from_stage": deal["stage_id"], "to_stage": stage_id}, author=author)
    if _depth < 5:
        run_automations(c, "stage_enter", deal_id, stage_id=stage_id, author=author, depth=_depth + 1)
        if new["kind"] == "won":
            run_automations(c, "deal_won", deal_id, author=author, depth=_depth + 1)
        elif new["kind"] == "lost":
            run_automations(c, "deal_lost", deal_id, author=author, depth=_depth + 1)
    return get(c, "deals", deal_id)


def create_order_for_deal(c, deal_id: str) -> str:
    deal = get(c, "deals", deal_id)
    if deal.get("order_id"):
        return deal["order_id"]
    contact = get(c, "contacts", deal["contact_id"]) if deal["contact_id"] else None
    nums = [r["number"] for r in c.execute("SELECT number FROM orders")]
    ints = [int(x) for x in nums if str(x).isdigit()]
    number = str(max(ints) + 1 if ints else 1)
    oid = new_id()
    ts = now_iso()
    c.execute("INSERT INTO orders(id, number, client, phone, date, comment, status, data, created_at, updated_at) "
              "VALUES (?,?,?,?,?,?,?,?,?,?)",
              (oid, number, contact["name"] if contact else deal["name"], contact["phone"] if contact else "",
               ts[:10], deal["name"], "measure", "{}", ts, ts))
    c.execute("UPDATE deals SET order_id=?, updated_at=? WHERE id=?", (oid, ts, deal_id))
    add_event(c, deal_id=deal_id, contact_id=deal["contact_id"], kind="system", text=f"Создан заказ №{number}",
              data={"order_id": oid})
    return oid


# ------------------------------------------------------------------ задачи
def due_from(days=0, hours=0, at_time: str | None = None) -> str:
    dt = datetime.now() + timedelta(days=float(days or 0), hours=float(hours or 0))
    if at_time and re.match(r"^\d{1,2}:\d{2}$", at_time):
        hh, mm = at_time.split(":")
        dt = dt.replace(hour=int(hh), minute=int(mm), second=0)
    return dt.isoformat(timespec="minutes")


def create_task(c, values: dict, author="") -> dict:
    t = insert(c, "tasks", {**values, "done": 0})
    if t["deal_id"] or t["contact_id"]:
        add_event(c, deal_id=t["deal_id"], contact_id=t["contact_id"], kind="system",
                  text=f"Поставлена задача: {TASK_KINDS.get(t['kind'], '')} — {t['text']} (срок {fmt_dt(t['due_at'])})",
                  data={"task_id": t["id"]}, author=author)
    return t


def complete_task(c, task_id: str, result: str = "", author="") -> dict:
    t = get(c, "tasks", task_id)
    if not t:
        raise ValueError("Задача не найдена")
    c.execute("UPDATE tasks SET done=1, done_at=?, result=?, updated_at=? WHERE id=?",
              (now_iso(), result or "", now_iso(), task_id))
    add_event(c, deal_id=t["deal_id"], contact_id=t["contact_id"], kind="task_done",
              text=f"Выполнено: {t['text']}" + (f". Результат: {result}" if result else ""),
              data={"task_id": task_id}, author=author)
    return get(c, "tasks", task_id)


def fmt_dt(s: str | None) -> str:
    if not s:
        return "без срока"
    try:
        d = datetime.fromisoformat(s)
        return d.strftime("%d.%m.%Y %H:%M")
    except ValueError:
        return s


# ------------------------------------------------------------------ автоматизация
def render_template(c, text: str, deal: dict) -> str:
    contact = get(c, "contacts", deal["contact_id"]) if deal.get("contact_id") else None
    stage = get(c, "stages", deal["stage_id"]) if deal.get("stage_id") else None
    order = row(c.execute("SELECT * FROM orders WHERE id=?", (deal["order_id"],)).fetchone()) if deal.get("order_id") else None
    repl = {
        "{name}": deal["name"], "{contact}": contact["name"] if contact else "", "{phone}": contact["phone"] if contact else "",
        "{amount}": f"{deal['amount']:,.0f}".replace(",", " "), "{stage}": stage["name"] if stage else "",
        "{order}": order["number"] if order else "",
    }
    for k, v in repl.items():
        text = text.replace(k, str(v))
    return text


def run_automations(c, trigger: str, deal_id: str, *, stage_id: str | None = None, author="", depth: int = 1) -> None:
    sql = "SELECT * FROM automations WHERE active=1 AND trigger=?"
    args: list = [trigger]
    if trigger == "stage_enter":
        sql += " AND stage_id=?"
        args.append(stage_id)
    for auto in rows(c.execute(sql, args).fetchall()):
        deal = get(c, "deals", deal_id)
        if not deal:
            return
        if auto["data"].get("pipeline_id") and auto["data"]["pipeline_id"] != deal["pipeline_id"]:
            continue
        for act in auto["data"].get("actions") or []:
            try:
                _run_action(c, act, deal, auto, depth)
            except Exception as e:  # noqa: BLE001 — ошибка автоматизации не должна ломать сделку
                add_event(c, deal_id=deal_id, kind="system", text=f"Автоматизация «{auto['name']}»: ошибка — {e}")


def _run_action(c, act: dict, deal: dict, auto: dict, depth: int) -> None:
    t = act.get("type")
    by = f"Автоматизация: {auto['name']}"
    if t == "create_task":
        create_task(c, {"text": render_template(c, act.get("text") or "Задача", deal), "kind": act.get("kind") or "call",
                         "due_at": due_from(act.get("due_days") or 0, act.get("due_hours") or 0, act.get("at_time")),
                         "deal_id": deal["id"], "contact_id": deal["contact_id"],
                         "responsible_id": act.get("responsible_id") or deal["responsible_id"]}, author=by)
    elif t == "add_note":
        add_event(c, deal_id=deal["id"], contact_id=deal["contact_id"], kind="note",
                  text=render_template(c, act.get("text") or "", deal), author=by)
    elif t == "set_responsible" and act.get("user_id"):
        update(c, "deals", deal["id"], {"responsible_id": act["user_id"]})
        add_event(c, deal_id=deal["id"], kind="system", text="Назначен ответственный", author=by)
    elif t == "create_order":
        create_order_for_deal(c, deal["id"])
    elif t == "set_order_status" and act.get("status"):
        oid = deal.get("order_id") or (create_order_for_deal(c, deal["id"]) if act.get("create_if_missing") else None)
        if oid:
            c.execute("UPDATE orders SET status=?, updated_at=? WHERE id=?", (act["status"], now_iso(), oid))
            add_event(c, deal_id=deal["id"], kind="system", text=f"Статус заказа изменён: {act['status']}", author=by)
    elif t == "move_stage" and act.get("stage_id"):
        move_deal(c, deal["id"], act["stage_id"], author=by, _depth=depth)
    elif t == "send_message":
        from .channels import send_to_contact  # локальный импорт: каналы зависят от сервиса

        send_to_contact(c, deal["id"], render_template(c, act.get("text") or "", deal), author=by,
                        channel_id=act.get("channel_id"))
