"""Доступ к данным (SQLite)."""
from __future__ import annotations

import copy
import json
from typing import Any

from .db import session, dumps, new_id, now_iso, row_to_dict
from .engine.library import Library

LIB_COLLECTIONS = {
    "manufacturers": "Производители",
    "categories": "Категории фурнитуры",
    "hardware": "Фурнитура",
    "profiles": "Профили",
    "kits": "Комплекты",
    "construction_templates": "Шаблоны конструкций",
    "op_templates": "Шаблоны обработки",
}


# ------------------------------------------------------------------ library
def lib_list(collection: str) -> list[dict]:
    with session() as c:
        rows = c.execute("SELECT * FROM library WHERE collection=? ORDER BY name COLLATE NOCASE", (collection,)).fetchall()
    return [row_to_dict(r) for r in rows]


def lib_get(item_id: str) -> dict | None:
    with session() as c:
        return row_to_dict(c.execute("SELECT * FROM library WHERE id=?", (item_id,)).fetchone())


def lib_create(collection: str, name: str, data: dict, item_id: str | None = None) -> dict:
    iid = item_id or new_id()
    ts = now_iso()
    with session() as c:
        c.execute("INSERT INTO library(id, collection, name, data, created_at, updated_at) VALUES (?,?,?,?,?,?)",
                  (iid, collection, name, dumps(data), ts, ts))
    return lib_get(iid)


def lib_update(item_id: str, name: str | None, data: dict | None) -> dict | None:
    cur = lib_get(item_id)
    if not cur:
        return None
    with session() as c:
        c.execute("UPDATE library SET name=?, data=?, updated_at=? WHERE id=?",
                  (cur["name"] if name is None else name, dumps(cur["data"] if data is None else data), now_iso(), item_id))
    return lib_get(item_id)


def lib_delete(item_id: str) -> bool:
    with session() as c:
        return c.execute("DELETE FROM library WHERE id=?", (item_id,)).rowcount > 0


def lib_duplicate(item_id: str) -> dict | None:
    cur = lib_get(item_id)
    if not cur:
        return None
    data = copy.deepcopy(cur["data"])
    data.pop("builtin_key", None)
    return lib_create(cur["collection"], f"{cur['name']} (копия)", data)


# ------------------------------------------------------------------ dxf
def dxf_get(dxf_id: str) -> dict | None:
    with session() as c:
        return row_to_dict(c.execute("SELECT * FROM dxf_files WHERE id=?", (dxf_id,)).fetchone())


def dxf_list() -> list[dict]:
    with session() as c:
        rows = c.execute("SELECT id, name, original_filename, stored_name, created_at, updated_at FROM dxf_files ORDER BY name").fetchall()
    return [dict(r) for r in rows]


def load_library() -> Library:
    items: dict[str, dict[str, dict]] = {}
    with session() as c:
        for r in c.execute("SELECT * FROM library"):
            d = row_to_dict(r)
            items.setdefault(d["collection"], {})[d["id"]] = d
        dxf = {r["id"]: row_to_dict(r) for r in c.execute("SELECT * FROM dxf_files")}
    return Library(items, dxf)


# ------------------------------------------------------------------ settings
def settings_get() -> dict[str, Any]:
    with session() as c:
        rows = c.execute("SELECT key, value FROM settings").fetchall()
    out = {}
    for r in rows:
        try:
            out[r["key"]] = json.loads(r["value"])
        except json.JSONDecodeError:
            out[r["key"]] = r["value"]
    return out


def settings_set(values: dict[str, Any]) -> None:
    with session() as c:
        for k, v in values.items():
            c.execute("INSERT INTO settings(key, value) VALUES (?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                      (k, dumps(v)))


# ------------------------------------------------------------------ orders / products
def order_get(order_id: str) -> dict | None:
    with session() as c:
        return row_to_dict(c.execute("SELECT * FROM orders WHERE id=?", (order_id,)).fetchone())


def products_of(order_id: str) -> list[dict]:
    with session() as c:
        rows = c.execute("SELECT * FROM products WHERE order_id=? ORDER BY position, created_at", (order_id,)).fetchall()
    return [row_to_dict(r) for r in rows]


def product_get(pid: str) -> dict | None:
    with session() as c:
        return row_to_dict(c.execute("SELECT * FROM products WHERE id=?", (pid,)).fetchone())


def product_save(pid: str, *, name=None, kind=None, data=None, position=None) -> dict | None:
    cur = product_get(pid)
    if not cur:
        return None
    with session() as c:
        c.execute("UPDATE products SET name=?, kind=?, data=?, position=?, updated_at=? WHERE id=?",
                  (cur["name"] if name is None else name, cur["kind"] if kind is None else kind,
                   dumps(cur["data"] if data is None else data), cur["position"] if position is None else position,
                   now_iso(), pid))
        c.execute("UPDATE orders SET updated_at=? WHERE id=?", (now_iso(), cur["order_id"]))
    return product_get(pid)


def product_create(order_id: str, name: str, kind: str, data: dict) -> dict:
    pid = new_id()
    ts = now_iso()
    with session() as c:
        pos = c.execute("SELECT COALESCE(MAX(position), 0) + 1 AS p FROM products WHERE order_id=?", (order_id,)).fetchone()["p"]
        c.execute("INSERT INTO products(id, order_id, name, kind, position, data, created_at, updated_at) VALUES (?,?,?,?,?,?,?,?)",
                  (pid, order_id, name, kind, pos, dumps(data), ts, ts))
    return product_get(pid)


def next_order_number() -> str:
    with session() as c:
        nums = [r["number"] for r in c.execute("SELECT number FROM orders")]
    ints = [int(x) for x in nums if str(x).isdigit()]
    return str(max(ints) + 1 if ints else 1)
