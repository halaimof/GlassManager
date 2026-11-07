from __future__ import annotations

import copy
from datetime import date

from fastapi import APIRouter, Body, HTTPException, Query
from fastapi.responses import Response

from .. import repo
from ..db import new_id, now_iso, session
from ..engine import resolve
from ..export.pdf import build_pdf
from .common import company_info, product_summary

router = APIRouter(prefix="/api/orders", tags=["orders"])

STATUSES = [
    ("draft", "Черновик"), ("measure", "Замер"), ("approval", "Согласование"), ("production", "В производство"),
    ("tempering", "Закалка"), ("ready", "Готово"), ("install", "Монтаж"), ("done", "Завершён"),
]
ORDER_FIELDS = ("number", "client", "phone", "date", "comment", "status")


@router.get("/statuses")
def statuses():
    return [{"key": k, "name": n} for k, n in STATUSES]


@router.get("")
def list_orders(q: str = "", status: str = ""):
    sql = """SELECT o.*, (SELECT COUNT(*) FROM products p WHERE p.order_id=o.id) AS products_count
             FROM orders o WHERE 1=1"""
    args: list = []
    if q:
        sql += " AND (o.number LIKE ? OR o.client LIKE ? OR o.phone LIKE ? OR o.comment LIKE ?)"
        args += [f"%{q}%"] * 4
    if status:
        sql += " AND o.status=?"
        args.append(status)
    sql += " ORDER BY o.updated_at DESC"
    with session() as c:
        rows = c.execute(sql, args).fetchall()
    out = []
    for r in rows:
        d = dict(r)
        d.pop("data", None)
        out.append(d)
    return out


@router.post("")
def create_order(body: dict = Body(default={})):
    oid = new_id()
    ts = now_iso()
    vals = {
        "number": str(body.get("number") or repo.next_order_number()),
        "client": body.get("client") or "",
        "phone": body.get("phone") or "",
        "date": body.get("date") or date.today().isoformat(),
        "comment": body.get("comment") or "",
        "status": body.get("status") or "draft",
    }
    with session() as c:
        c.execute("INSERT INTO orders(id, number, client, phone, date, comment, status, data, created_at, updated_at) "
                  "VALUES (?,?,?,?,?,?,?,?,?,?)",
                  (oid, *[vals[k] for k in ORDER_FIELDS], "{}", ts, ts))
    return get_order(oid)


@router.get("/{order_id}")
def get_order(order_id: str):
    o = repo.order_get(order_id)
    if not o:
        raise HTTPException(404, "Заказ не найден")
    lib = repo.load_library()
    out = []
    for p in repo.products_of(order_id):
        summ = product_summary(p, lib)
        try:
            res = resolve(p["data"], lib)
            planes = {pl["key"]: pl["dx"] for pl in res["planes"]}
            summ["thumb"] = [{"contour": g["contour"], "x": g["x"] + planes.get(g["plane"], 0), "y": g["y"],
                              "holes": g["holes"]} for g in res["glasses"]]
            summ["glass_sizes"] = [f"{g['w']:.0f}×{g['h']:.0f}" for g in res["glasses"]]
            summ["problems"] = len(res["errors"])
        except Exception:  # noqa: BLE001 — превью не должно ломать заказ
            summ["thumb"] = []
        out.append(summ)
    o["products"] = out
    return o


@router.put("/{order_id}")
def update_order(order_id: str, body: dict = Body(...)):
    o = repo.order_get(order_id)
    if not o:
        raise HTTPException(404, "Заказ не найден")
    vals = {k: (body[k] if k in body and body[k] is not None else o[k]) for k in ORDER_FIELDS}
    with session() as c:
        c.execute("UPDATE orders SET number=?, client=?, phone=?, date=?, comment=?, status=?, updated_at=? WHERE id=?",
                  (*[vals[k] for k in ORDER_FIELDS], now_iso(), order_id))
    return get_order(order_id)


@router.delete("/{order_id}")
def delete_order(order_id: str):
    with session() as c:
        n = c.execute("DELETE FROM orders WHERE id=?", (order_id,)).rowcount
    if not n:
        raise HTTPException(404, "Заказ не найден")
    return {"ok": True}


@router.post("/{order_id}/duplicate")
def duplicate_order(order_id: str):
    o = repo.order_get(order_id)
    if not o:
        raise HTTPException(404, "Заказ не найден")
    new = create_order({**{k: o[k] for k in ORDER_FIELDS}, "number": None, "status": "draft",
                        "comment": (o["comment"] + " (копия)").strip()})
    for p in repo.products_of(order_id):
        repo.product_create(new["id"], p["name"], p["kind"], copy.deepcopy(p["data"]))
    return get_order(new["id"])


@router.get("/{order_id}/pdf")
def order_pdf(order_id: str, mode: str = Query("full", pattern="^(client|production|full)$"), product_id: str = ""):
    o = repo.order_get(order_id)
    if not o:
        raise HTTPException(404, "Заказ не найден")
    lib = repo.load_library()
    products = repo.products_of(order_id)
    if product_id:
        products = [p for p in products if p["id"] == product_id]
    resolved = {}
    for p in products:
        resolved[p["id"]] = resolve(p["data"], lib)
        summ = product_summary(p, lib)
        p["template_name"] = summ.get("template_name")
        p["kit_name"] = summ.get("kit_name")
    pdf = build_pdf(o, products, resolved, company_info(), mode)
    names = {"client": "klient", "production": "proizvodstvo", "full": "polnyj"}
    fname = f"zakaz-{o['number'] or 'bez-nomera'}-{names[mode]}.pdf"
    return Response(pdf, media_type="application/pdf", headers={"Content-Disposition": f'inline; filename="{fname}"'})


