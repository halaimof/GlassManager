"""HTTP API CRM: /api/crm/* и входящие webhook /api/inbound/*."""
from __future__ import annotations

import json
import secrets
from datetime import date, timedelta
from urllib.parse import parse_qs, unquote

from fastapi import APIRouter, Body, HTTPException, Request

from ..api.orders import STATUSES
from ..db import now_iso, session
from . import service as S
from .analytics import analytics
from .channels import CHANNEL_KINDS, form_snippet, handle_inbound, mask_config, merge_config, poll_channel, send_to_contact

router = APIRouter(prefix="/api/crm", tags=["crm"])
inbound = APIRouter(prefix="/api/inbound", tags=["inbound"])


def author_of(request: Request) -> str:
    uid = request.headers.get("x-gc-user") or ""
    if not uid:
        return ""
    with session() as c:
        u = S.get(c, "crm_users", uid)
    return u["name"] if u else ""


def _404(obj, what="Запись"):
    if not obj:
        raise HTTPException(404, f"{what} не найдена")
    return obj


def _clean(body: dict, table: str) -> dict:
    allowed = set(S.TABLE_FIELDS[table]) | {"data"}
    out = {k: v for k, v in body.items() if k in allowed}
    for k in ("company_id", "contact_id", "order_id", "responsible_id", "deal_id", "stage_id", "pipeline_id", "due_at"):
        if k in out and out[k] == "":
            out[k] = None
    return out


@router.get("/meta")
def meta():
    return {"task_kinds": S.TASK_KINDS, "event_kinds": S.EVENT_KINDS, "triggers": S.AUTOMATION_TRIGGERS,
            "actions": S.AUTOMATION_ACTIONS, "channel_kinds": CHANNEL_KINDS,
            "order_statuses": [{"key": k, "name": n} for k, n in STATUSES]}


# ------------------------------------------------------------------ пользователи (ответственные)
@router.get("/users")
def users():
    with session() as c:
        return S.rows(c.execute("SELECT * FROM crm_users ORDER BY active DESC, name").fetchall())


@router.post("/users")
def user_create(body: dict = Body(...)):
    with session() as c:
        return S.insert(c, "crm_users", {"name": body.get("name") or "Менеджер", "color": body.get("color") or "#1f6f8b", "active": 1})


@router.put("/users/{uid}")
def user_update(uid: str, body: dict = Body(...)):
    with session() as c:
        return _404(S.update(c, "crm_users", uid, _clean(body, "crm_users")))


@router.post("/users/{uid}/duplicate")
def user_dup(uid: str):
    with session() as c:
        u = _404(S.get(c, "crm_users", uid))
        return S.insert(c, "crm_users", {"name": u["name"] + " (копия)", "color": u["color"], "active": 1})


@router.delete("/users/{uid}")
def user_delete(uid: str):
    with session() as c:
        c.execute("UPDATE deals SET responsible_id=NULL WHERE responsible_id=?", (uid,))
        c.execute("UPDATE tasks SET responsible_id=NULL WHERE responsible_id=?", (uid,))
        c.execute("DELETE FROM crm_users WHERE id=?", (uid,))
    return {"ok": True}


# ------------------------------------------------------------------ воронки и этапы
def _pipelines(c):
    ps = S.rows(c.execute("SELECT * FROM pipelines ORDER BY position, created_at").fetchall())
    for p in ps:
        p["stages"] = S.rows(c.execute("SELECT * FROM stages WHERE pipeline_id=? ORDER BY position", (p["id"],)).fetchall())
    return ps


@router.get("/pipelines")
def pipelines():
    with session() as c:
        return _pipelines(c)


DEFAULT_STAGES = [("Новая заявка", "#d6eaf8", "open"), ("В работе", "#fdebd0", "open"),
                  ("Успешно реализовано", "#d4efdf", "won"), ("Закрыто и не реализовано", "#e5e8e8", "lost")]


@router.post("/pipelines")
def pipeline_create(body: dict = Body(...)):
    with session() as c:
        pos = c.execute("SELECT COALESCE(MAX(position),0)+1 p FROM pipelines").fetchone()["p"]
        p = S.insert(c, "pipelines", {"name": body.get("name") or "Новая воронка", "position": pos})
        for i, (n, col, k) in enumerate(DEFAULT_STAGES):
            S.insert(c, "stages", {"pipeline_id": p["id"], "name": n, "color": col, "position": i, "kind": k})
    return pipelines()


@router.put("/pipelines/{pid}")
def pipeline_update(pid: str, body: dict = Body(...)):
    with session() as c:
        _404(S.update(c, "pipelines", pid, _clean(body, "pipelines")), "Воронка")
        if "stage_order" in body:
            for i, sid in enumerate(body["stage_order"]):
                c.execute("UPDATE stages SET position=? WHERE id=? AND pipeline_id=?", (i, sid, pid))
    return pipelines()


@router.post("/pipelines/{pid}/duplicate")
def pipeline_dup(pid: str):
    with session() as c:
        p = _404(S.get(c, "pipelines", pid), "Воронка")
        pos = c.execute("SELECT COALESCE(MAX(position),0)+1 p FROM pipelines").fetchone()["p"]
        n = S.insert(c, "pipelines", {"name": p["name"] + " (копия)", "position": pos})
        for s in S.rows(c.execute("SELECT * FROM stages WHERE pipeline_id=? ORDER BY position", (pid,)).fetchall()):
            S.insert(c, "stages", {"pipeline_id": n["id"], "name": s["name"], "color": s["color"], "position": s["position"], "kind": s["kind"]})
    return pipelines()


@router.delete("/pipelines/{pid}")
def pipeline_delete(pid: str):
    with session() as c:
        if c.execute("SELECT COUNT(*) n FROM deals WHERE pipeline_id=?", (pid,)).fetchone()["n"]:
            raise HTTPException(400, "В воронке есть сделки — перенесите или удалите их")
        if c.execute("SELECT COUNT(*) n FROM pipelines").fetchone()["n"] <= 1:
            raise HTTPException(400, "Нельзя удалить последнюю воронку")
        c.execute("DELETE FROM pipelines WHERE id=?", (pid,))
    return pipelines()


@router.post("/pipelines/{pid}/stages")
def stage_create(pid: str, body: dict = Body(default={})):
    with session() as c:
        _404(S.get(c, "pipelines", pid), "Воронка")
        # новый этап — перед закрывающими
        pos = c.execute("SELECT COALESCE(MAX(position),-1)+1 p FROM stages WHERE pipeline_id=? AND kind='open'", (pid,)).fetchone()["p"]
        c.execute("UPDATE stages SET position=position+1 WHERE pipeline_id=? AND position>=?", (pid, pos))
        S.insert(c, "stages", {"pipeline_id": pid, "name": body.get("name") or "Новый этап", "color": body.get("color") or "#e8f6f3",
                               "position": pos, "kind": "open"})
    return pipelines()


@router.put("/stages/{sid}")
def stage_update(sid: str, body: dict = Body(...)):
    with session() as c:
        _404(S.update(c, "stages", sid, {k: v for k, v in body.items() if k in ("name", "color", "kind")}), "Этап")
    return pipelines()


@router.post("/stages/{sid}/duplicate")
def stage_dup(sid: str):
    with session() as c:
        s = _404(S.get(c, "stages", sid), "Этап")
        c.execute("UPDATE stages SET position=position+1 WHERE pipeline_id=? AND position>?", (s["pipeline_id"], s["position"]))
        S.insert(c, "stages", {"pipeline_id": s["pipeline_id"], "name": s["name"] + " (копия)", "color": s["color"],
                               "position": s["position"] + 1, "kind": s["kind"]})
    return pipelines()


@router.delete("/stages/{sid}")
def stage_delete(sid: str, move_to: str = ""):
    with session() as c:
        _404(S.get(c, "stages", sid), "Этап")
        n = c.execute("SELECT COUNT(*) n FROM deals WHERE stage_id=?", (sid,)).fetchone()["n"]
        if n:
            target = S.get(c, "stages", move_to) if move_to else None
            if not target:
                raise HTTPException(400, f"На этапе {n} сделок — выберите этап, куда их перенести")
            c.execute("UPDATE deals SET stage_id=?, pipeline_id=? WHERE stage_id=?", (target["id"], target["pipeline_id"], sid))
        c.execute("DELETE FROM stages WHERE id=?", (sid,))
        c.execute("UPDATE automations SET active=0 WHERE stage_id=?", (sid,))
    return pipelines()


# ------------------------------------------------------------------ сделки
DEAL_SELECT = """
SELECT d.*, ct.name AS contact_name, ct.phone AS contact_phone, co.name AS company_name,
       s.name AS stage_name, s.kind AS stage_kind, s.color AS stage_color, u.name AS responsible_name, u.color AS responsible_color,
       o.number AS order_number, o.status AS order_status,
       (SELECT MIN(due_at) FROM tasks t WHERE t.deal_id=d.id AND t.done=0) AS next_task_at,
       (SELECT COUNT(*) FROM tasks t WHERE t.deal_id=d.id AND t.done=0) AS open_tasks,
       (SELECT MAX(created_at) FROM events e WHERE e.deal_id=d.id) AS last_event_at
FROM deals d
LEFT JOIN contacts ct ON ct.id=d.contact_id LEFT JOIN companies co ON co.id=d.company_id
LEFT JOIN stages s ON s.id=d.stage_id LEFT JOIN crm_users u ON u.id=d.responsible_id
LEFT JOIN orders o ON o.id=d.order_id
"""


@router.get("/deals")
def deals(pipeline_id: str = "", q: str = "", responsible_id: str = "", order_id: str = "", contact_id: str = "",
          company_id: str = "", state: str = ""):
    sql, args = DEAL_SELECT + " WHERE 1=1", []
    for col, val in (("d.pipeline_id", pipeline_id), ("d.responsible_id", responsible_id), ("d.order_id", order_id),
                     ("d.contact_id", contact_id), ("d.company_id", company_id)):
        if val:
            sql += f" AND {col}=?"
            args.append(val)
    if state in ("open", "won", "lost"):
        sql += " AND s.kind=?"
        args.append(state)
    if q:
        sql += " AND (d.name LIKE ? OR ct.name LIKE ? OR ct.phone LIKE ? OR co.name LIKE ? OR d.tags LIKE ? OR o.number LIKE ?)"
        args += [f"%{q}%"] * 6
    sql += " ORDER BY d.updated_at DESC"
    with session() as c:
        return S.rows(c.execute(sql, args).fetchall())


def _deal_full(c, did: str) -> dict:
    d = _404(S.row(c.execute(DEAL_SELECT + " WHERE d.id=?", (did,)).fetchone()), "Сделка")
    d["contact"] = S.get(c, "contacts", d["contact_id"]) if d["contact_id"] else None
    d["company"] = S.get(c, "companies", d["company_id"]) if d["company_id"] else None
    d["events"] = S.rows(c.execute("SELECT * FROM events WHERE deal_id=? ORDER BY created_at DESC", (did,)).fetchall())
    d["tasks"] = S.rows(c.execute("SELECT * FROM tasks WHERE deal_id=? ORDER BY done, due_at", (did,)).fetchall())
    if d["order_id"]:
        d["products"] = [dict(r) for r in c.execute("SELECT id, name FROM products WHERE order_id=? ORDER BY position", (d["order_id"],))]
    return d


@router.post("/deals")
def deal_create(request: Request, body: dict = Body(default={})):
    with session() as c:
        v = _clean(body, "deals")
        if body.get("new_contact"):
            nc = body["new_contact"]
            contact, _ = S.find_or_create_contact(c, name=nc.get("name") or "", phone=nc.get("phone") or "", email=nc.get("email") or "")
            v["contact_id"] = contact["id"]
        d = S.create_deal(c, v, author=author_of(request))
        return _deal_full(c, d["id"])


@router.get("/deals/{did}")
def deal_get(did: str):
    with session() as c:
        return _deal_full(c, did)


FIELD_RU = {"name": "Название", "amount": "Бюджет", "contact_id": "Контакт", "company_id": "Компания",
            "responsible_id": "Ответственный", "source": "Источник", "tags": "Теги", "order_id": "Заказ", "comment": "Комментарий"}


@router.put("/deals/{did}")
def deal_update(did: str, request: Request, body: dict = Body(...)):
    author = author_of(request)
    with session() as c:
        cur = _404(S.get(c, "deals", did), "Сделка")
        v = _clean(body, "deals")
        stage = v.pop("stage_id", None)
        v.pop("pipeline_id", None)
        S.update(c, "deals", did, v)
        changed = [FIELD_RU[k] for k in v if k in FIELD_RU and v[k] != cur.get(k)]
        if changed:
            S.add_event(c, deal_id=did, contact_id=cur["contact_id"], kind="field", text="Изменено: " + ", ".join(changed), author=author)
        if stage and stage != cur["stage_id"]:
            S.move_deal(c, did, stage, author=author, reason=body.get("lost_reason") or "")
        return _deal_full(c, did)


@router.post("/deals/{did}/duplicate")
def deal_dup(did: str, request: Request):
    with session() as c:
        d = _404(S.get(c, "deals", did), "Сделка")
        v = {k: d[k] for k in S.TABLE_FIELDS["deals"] if k != "order_id"}
        v["name"] = d["name"] + " (копия)"
        return _deal_full(c, S.create_deal(c, v, author=author_of(request))["id"])


@router.delete("/deals/{did}")
def deal_delete(did: str):
    with session() as c:
        c.execute("DELETE FROM deals WHERE id=?", (did,))
    return {"ok": True}


@router.post("/deals/{did}/order")
def deal_order(did: str, body: dict = Body(default={})):
    with session() as c:
        _404(S.get(c, "deals", did), "Сделка")
        if body.get("order_id"):
            c.execute("UPDATE deals SET order_id=?, updated_at=? WHERE id=?", (body["order_id"], now_iso(), did))
            S.add_event(c, deal_id=did, kind="system", text="Сделка привязана к заказу")
        else:
            S.create_order_for_deal(c, did)
        return _deal_full(c, did)


@router.post("/deals/{did}/notes")
def deal_note(did: str, request: Request, body: dict = Body(...)):
    with session() as c:
        d = _404(S.get(c, "deals", did), "Сделка")
        S.add_event(c, deal_id=did, contact_id=d["contact_id"], kind="note", text=body.get("text") or "", author=author_of(request))
        return _deal_full(c, did)


@router.post("/deals/{did}/message")
def deal_message(did: str, request: Request, body: dict = Body(...)):
    with session() as c:
        _404(S.get(c, "deals", did), "Сделка")
        try:
            send_to_contact(c, did, body.get("text") or "", channel_id=body.get("channel_id") or None,
                            subject=body.get("subject") or "", author=author_of(request))
        except Exception as e:  # noqa: BLE001 — показать причину пользователю
            raise HTTPException(400, f"Не отправлено: {e}") from e
        return _deal_full(c, did)


@router.put("/events/{eid}")
def event_update(eid: str, body: dict = Body(...)):
    with session() as c:
        c.execute("UPDATE events SET text=? WHERE id=? AND kind='note'", (body.get("text") or "", eid))
    return {"ok": True}


@router.delete("/events/{eid}")
def event_delete(eid: str):
    with session() as c:
        c.execute("DELETE FROM events WHERE id=? AND kind='note'", (eid,))
    return {"ok": True}


# ------------------------------------------------------------------ контакты и компании
@router.get("/contacts")
def contacts(q: str = "", company_id: str = ""):
    sql = """SELECT ct.*, co.name AS company_name,
             (SELECT COUNT(*) FROM deals d WHERE d.contact_id=ct.id) AS deals_count
             FROM contacts ct LEFT JOIN companies co ON co.id=ct.company_id WHERE 1=1"""
    args: list = []
    if q:
        sql += " AND (ct.name LIKE ? OR ct.phone LIKE ? OR ct.email LIKE ? OR co.name LIKE ? OR ct.phone_norm LIKE ?)"
        args += [f"%{q}%"] * 4 + [f"%{S.norm_phone(q) or q}%"]
    if company_id:
        sql += " AND ct.company_id=?"
        args.append(company_id)
    with session() as c:
        return S.rows(c.execute(sql + " ORDER BY ct.updated_at DESC LIMIT 1000", args).fetchall())


def _entity_full(c, table: str, eid: str) -> dict:
    e = _404(S.get(c, table, eid))
    key = "contact_id" if table == "contacts" else "company_id"
    e["deals"] = S.rows(c.execute(DEAL_SELECT + f" WHERE d.{key}=? ORDER BY d.created_at DESC", (eid,)).fetchall())
    if table == "contacts":
        e["company"] = S.get(c, "companies", e["company_id"]) if e["company_id"] else None
        e["events"] = S.rows(c.execute("SELECT * FROM events WHERE contact_id=? ORDER BY created_at DESC LIMIT 200", (eid,)).fetchall())
        e["tasks"] = S.rows(c.execute("SELECT * FROM tasks WHERE contact_id=? ORDER BY done, due_at", (eid,)).fetchall())
    else:
        e["contacts"] = S.rows(c.execute("SELECT * FROM contacts WHERE company_id=? ORDER BY name", (eid,)).fetchall())
    return e


@router.post("/contacts")
def contact_create(body: dict = Body(...)):
    with session() as c:
        dup = S.find_contact(c, phone=body.get("phone"), email=body.get("email")) if not body.get("force") else None
        if dup:
            raise HTTPException(409, f"Контакт с таким телефоном/e-mail уже есть: {dup['name']}")
        return _entity_full(c, "contacts", S.insert(c, "contacts", _clean(body, "contacts"))["id"])


@router.get("/contacts/{cid}")
def contact_get(cid: str):
    with session() as c:
        return _entity_full(c, "contacts", cid)


@router.put("/contacts/{cid}")
def contact_update(cid: str, body: dict = Body(...)):
    with session() as c:
        _404(S.update(c, "contacts", cid, _clean(body, "contacts")))
        return _entity_full(c, "contacts", cid)


@router.post("/contacts/{cid}/duplicate")
def contact_dup(cid: str):
    with session() as c:
        x = _404(S.get(c, "contacts", cid))
        v = {k: x[k] for k in S.TABLE_FIELDS["contacts"]}
        v["name"] += " (копия)"
        return S.insert(c, "contacts", v)


@router.delete("/contacts/{cid}")
def contact_delete(cid: str):
    with session() as c:
        c.execute("DELETE FROM contacts WHERE id=?", (cid,))
    return {"ok": True}


@router.post("/contacts/{cid}/message")
def contact_message(cid: str, request: Request, body: dict = Body(...)):
    with session() as c:
        try:
            send_to_contact(c, None, body.get("text") or "", contact_id=cid, channel_id=body.get("channel_id") or None,
                            subject=body.get("subject") or "", author=author_of(request))
        except Exception as e:  # noqa: BLE001
            raise HTTPException(400, f"Не отправлено: {e}") from e
        return _entity_full(c, "contacts", cid)


@router.get("/companies")
def companies(q: str = ""):
    sql = """SELECT co.*, (SELECT COUNT(*) FROM contacts ct WHERE ct.company_id=co.id) AS contacts_count,
             (SELECT COUNT(*) FROM deals d WHERE d.company_id=co.id) AS deals_count FROM companies co WHERE 1=1"""
    args: list = []
    if q:
        sql += " AND (co.name LIKE ? OR co.phone LIKE ? OR co.email LIKE ? OR co.inn LIKE ?)"
        args += [f"%{q}%"] * 4
    with session() as c:
        return S.rows(c.execute(sql + " ORDER BY co.name", args).fetchall())


@router.post("/companies")
def company_create(body: dict = Body(...)):
    with session() as c:
        return _entity_full(c, "companies", S.insert(c, "companies", _clean(body, "companies"))["id"])


@router.get("/companies/{cid}")
def company_get(cid: str):
    with session() as c:
        return _entity_full(c, "companies", cid)


@router.put("/companies/{cid}")
def company_update(cid: str, body: dict = Body(...)):
    with session() as c:
        _404(S.update(c, "companies", cid, _clean(body, "companies")))
        return _entity_full(c, "companies", cid)


@router.post("/companies/{cid}/duplicate")
def company_dup(cid: str):
    with session() as c:
        x = _404(S.get(c, "companies", cid))
        v = {k: x[k] for k in S.TABLE_FIELDS["companies"]}
        v["name"] += " (копия)"
        return S.insert(c, "companies", v)


@router.delete("/companies/{cid}")
def company_delete(cid: str):
    with session() as c:
        c.execute("DELETE FROM companies WHERE id=?", (cid,))
    return {"ok": True}


# ------------------------------------------------------------------ задачи
TASK_SELECT = """SELECT t.*, d.name AS deal_name, ct.name AS contact_name, ct.phone AS contact_phone, u.name AS responsible_name
FROM tasks t LEFT JOIN deals d ON d.id=t.deal_id LEFT JOIN contacts ct ON ct.id=COALESCE(t.contact_id, d.contact_id)
LEFT JOIN crm_users u ON u.id=t.responsible_id"""


@router.get("/tasks")
def tasks(scope: str = "open", responsible_id: str = "", date_from: str = "", date_to: str = ""):
    sql, args = TASK_SELECT + " WHERE 1=1", []
    today = date.today().isoformat()
    if scope == "open":
        sql += " AND t.done=0"
    elif scope == "done":
        sql += " AND t.done=1"
    elif scope == "overdue":
        sql += " AND t.done=0 AND t.due_at < ?"
        args.append(today)
    if responsible_id:
        sql += " AND t.responsible_id=?"
        args.append(responsible_id)
    if date_from:
        sql += " AND substr(t.due_at,1,10) >= ?"
        args.append(date_from)
    if date_to:
        sql += " AND substr(t.due_at,1,10) <= ?"
        args.append(date_to)
    sql += " ORDER BY t.done, t.due_at IS NULL, t.due_at" if scope != "done" else " ORDER BY t.done_at DESC LIMIT 500"
    with session() as c:
        return S.rows(c.execute(sql, args).fetchall())


@router.post("/tasks")
def task_create(request: Request, body: dict = Body(...)):
    with session() as c:
        v = _clean(body, "tasks")
        if v.get("deal_id") and not v.get("contact_id"):
            d = S.get(c, "deals", v["deal_id"])
            v["contact_id"] = d["contact_id"] if d else None
            if d and not v.get("responsible_id"):
                v["responsible_id"] = d["responsible_id"]
        return S.create_task(c, v, author=author_of(request))


@router.put("/tasks/{tid}")
def task_update(tid: str, body: dict = Body(...)):
    with session() as c:
        v = _clean(body, "tasks")
        v.pop("done", None)
        return _404(S.update(c, "tasks", tid, v), "Задача")


@router.post("/tasks/{tid}/complete")
def task_complete(tid: str, request: Request, body: dict = Body(default={})):
    with session() as c:
        t = S.complete_task(c, tid, body.get("result") or "", author=author_of(request))
        nxt = body.get("next")
        if nxt and nxt.get("text"):
            S.create_task(c, {"text": nxt["text"], "kind": nxt.get("kind") or "call", "due_at": nxt.get("due_at"),
                              "deal_id": t["deal_id"], "contact_id": t["contact_id"], "responsible_id": t["responsible_id"]},
                          author=author_of(request))
        return t


@router.post("/tasks/{tid}/reopen")
def task_reopen(tid: str):
    with session() as c:
        c.execute("UPDATE tasks SET done=0, done_at=NULL, updated_at=? WHERE id=?", (now_iso(), tid))
        return S.get(c, "tasks", tid)


@router.post("/tasks/{tid}/duplicate")
def task_dup(tid: str, request: Request):
    with session() as c:
        t = _404(S.get(c, "tasks", tid), "Задача")
        v = {k: t[k] for k in S.TABLE_FIELDS["tasks"] if k not in ("done", "result")}
        v["text"] += " (копия)"
        return S.create_task(c, v, author=author_of(request))


@router.delete("/tasks/{tid}")
def task_delete(tid: str):
    with session() as c:
        c.execute("DELETE FROM tasks WHERE id=?", (tid,))
    return {"ok": True}


# ------------------------------------------------------------------ автоматизация
@router.get("/automations")
def automations():
    with session() as c:
        return S.rows(c.execute("SELECT * FROM automations ORDER BY created_at").fetchall())


@router.post("/automations")
def automation_create(body: dict = Body(...)):
    with session() as c:
        return S.insert(c, "automations", {"name": body.get("name") or "Новое правило", "active": 1,
                                           "trigger": body.get("trigger") or "stage_enter", "stage_id": body.get("stage_id"),
                                           "data": body.get("data") or {"actions": []}})


@router.put("/automations/{aid}")
def automation_update(aid: str, body: dict = Body(...)):
    with session() as c:
        v = _clean(body, "automations")
        if "data" in v:  # действия заменяются целиком
            c.execute("UPDATE automations SET data=? WHERE id=?", (json.dumps(v.pop("data"), ensure_ascii=False), aid))
        return _404(S.update(c, "automations", aid, v), "Правило")


@router.post("/automations/{aid}/duplicate")
def automation_dup(aid: str):
    with session() as c:
        a = _404(S.get(c, "automations", aid), "Правило")
        return S.insert(c, "automations", {"name": a["name"] + " (копия)", "active": 0, "trigger": a["trigger"],
                                           "stage_id": a["stage_id"], "data": a["data"]})


@router.delete("/automations/{aid}")
def automation_delete(aid: str):
    with session() as c:
        c.execute("DELETE FROM automations WHERE id=?", (aid,))
    return {"ok": True}


# ------------------------------------------------------------------ каналы
def _public(ch: dict, base: str) -> dict:
    ch = dict(ch)
    ch["data"] = mask_config(ch.get("data") or {})
    ch["webhook_url"] = f"{base.rstrip('/')}/api/inbound/{ch['id']}/{ch['token']}"
    return ch


@router.get("/channels")
def channels(request: Request):
    base = str(request.base_url)
    with session() as c:
        return [_public(ch, base) for ch in S.rows(c.execute("SELECT * FROM channels ORDER BY created_at").fetchall())]


@router.post("/channels")
def channel_create(request: Request, body: dict = Body(...)):
    kind = body.get("kind") or "form"
    if kind not in CHANNEL_KINDS:
        raise HTTPException(400, "Неизвестный тип канала")
    with session() as c:
        ch = S.insert(c, "channels", {"name": body.get("name") or CHANNEL_KINDS[kind], "kind": kind, "active": 1,
                                      "token": secrets.token_urlsafe(18), "data": body.get("data") or {}})
        return _public(ch, str(request.base_url))


@router.put("/channels/{cid}")
def channel_update(cid: str, request: Request, body: dict = Body(...)):
    with session() as c:
        cur = _404(S.get(c, "channels", cid), "Канал")
        v = {k: body[k] for k in ("name", "active") if k in body}
        if "data" in body:
            c.execute("UPDATE channels SET data=? WHERE id=?", (json.dumps(merge_config(cur["data"], body["data"]), ensure_ascii=False), cid))
        if body.get("regenerate_token"):
            v["token"] = secrets.token_urlsafe(18)
        return _public(S.update(c, "channels", cid, v), str(request.base_url))


@router.post("/channels/{cid}/duplicate")
def channel_dup(cid: str, request: Request):
    with session() as c:
        ch = _404(S.get(c, "channels", cid), "Канал")
        n = S.insert(c, "channels", {"name": ch["name"] + " (копия)", "kind": ch["kind"], "active": 0,
                                     "token": secrets.token_urlsafe(18), "data": ch["data"]})
        return _public(n, str(request.base_url))


@router.delete("/channels/{cid}")
def channel_delete(cid: str):
    with session() as c:
        c.execute("DELETE FROM channels WHERE id=?", (cid,))
    return {"ok": True}


@router.post("/channels/{cid}/poll")
def channel_poll(cid: str):
    try:
        n = poll_channel(cid)
    except Exception as e:  # noqa: BLE001
        raise HTTPException(400, f"Ошибка канала: {e}") from e
    return {"ok": True, "received": n}


@router.get("/channels/{cid}/form")
def channel_form(cid: str, request: Request):
    with session() as c:
        ch = _404(S.get(c, "channels", cid), "Канал")
    return {"html": form_snippet(str(request.base_url), ch)}


# ------------------------------------------------------------------ аналитика и сводка
@router.get("/analytics")
def crm_analytics(pipeline_id: str = "", date_from: str = "", date_to: str = ""):
    df = date_from or (date.today() - timedelta(days=30)).isoformat()
    dt = date_to or date.today().isoformat()
    with session() as c:
        return analytics(c, pipeline_id or None, df, dt)


@router.get("/summary")
def summary():
    today = date.today().isoformat()
    with session() as c:
        return {
            "tasks_overdue": c.execute("SELECT COUNT(*) n FROM tasks WHERE done=0 AND due_at < ?", (today,)).fetchone()["n"],
            "tasks_today": c.execute("SELECT COUNT(*) n FROM tasks WHERE done=0 AND substr(due_at,1,10)=?", (today,)).fetchone()["n"],
            "new_messages": c.execute("SELECT COUNT(*) n FROM events WHERE kind IN ('message_in','email_in','call') AND created_at >= ?",
                                      (today,)).fetchone()["n"],
        }


# ------------------------------------------------------------------ входящие
async def _payload(request: Request) -> dict:
    ctype = request.headers.get("content-type", "")
    raw = await request.body()
    data: dict = {}
    if "json" in ctype:
        try:
            data = json.loads(raw or b"{}")
        except json.JSONDecodeError:
            data = {}
    elif raw:
        if "multipart" in ctype:
            form = await request.form()
            data = {k: str(v) for k, v in form.items()}
        else:
            data = {k: v[0] for k, v in parse_qs(raw.decode("utf-8", "replace")).items()}
    data.update({k: unquote(v) for k, v in request.query_params.items() if k not in data})
    if not isinstance(data, dict):
        data = {"text": str(data)}
    return data


@inbound.post("/{cid}/{token}")
@inbound.get("/{cid}/{token}")
async def inbound_hook(cid: str, token: str, request: Request):
    with session() as c:
        ch = S.get(c, "channels", cid)
        if not ch or not secrets.compare_digest(ch["token"], token) or not ch["active"]:
            raise HTTPException(404, "Канал не найден")
    payload = await _payload(request)
    if request.method == "GET" and not payload:
        return {"ok": True, "channel": ch["name"]}
    with session() as c:
        try:
            return handle_inbound(c, ch, payload)
        except ValueError as e:
            raise HTTPException(400, str(e)) from e

