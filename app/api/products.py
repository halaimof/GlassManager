from __future__ import annotations

import copy
import io
import re
import zipfile

from fastapi import APIRouter, Body, HTTPException
from fastapi.responses import Response

from .. import repo
from ..db import session
from ..engine import resolve
from ..engine.model import empty_product_data, new_panel, normalize, remap_ids
from ..engine.templates import apply_kit, apply_template, template_from_product
from ..export.dxf_export import glass_dxf, product_dxf
from .common import product_summary

router = APIRouter(prefix="/api", tags=["products"])

KINDS = {"shower": "Душевая", "railing": "Стеклянное ограждение", "mirror": "Зеркало",
         "apron": "Фартук", "partition": "Перегородка", "other": "Другое"}


def _payload(p: dict) -> dict:
    lib = repo.load_library()
    data = normalize(p["data"])
    return {"product": {**p, "data": data}, "resolved": resolve(data, lib), "summary": product_summary(p, lib)}


def _get(pid: str) -> dict:
    p = repo.product_get(pid)
    if not p:
        raise HTTPException(404, "Изделие не найдено")
    return p


@router.get("/product-kinds")
def kinds():
    return [{"key": k, "name": v} for k, v in KINDS.items()]


@router.post("/orders/{order_id}/products")
def create_product(order_id: str, body: dict = Body(default={})):
    if not repo.order_get(order_id):
        raise HTTPException(404, "Заказ не найден")
    lib = repo.load_library()
    data = empty_product_data()
    data["mode"] = body.get("mode") or "quick"
    if body.get("measurement"):
        data["measurement"].update(body["measurement"])
    if body.get("settings"):
        data["settings"].update(body["settings"])
    kind = body.get("kind") or "shower"
    if body.get("template_id"):
        t = repo.lib_get(body["template_id"])
        if t:
            data = apply_template(data, {**t["data"], "id": t["id"]})
    elif data["mode"] == "manual":
        p = new_panel("fixed" if kind == "shower" else "other", "Стекло 1")
        p["width"] = {"mode": "value", "value": 800, "formula": ""}
        p["height_override"] = 2000
        for side in ("left", "right", "bottom"):
            p["edges"][side]["kind"] = "free"
        data["panels"] = [p]
    if body.get("kit_id"):
        k = repo.lib_get(body["kit_id"])
        if k:
            data = apply_kit(data, {**k["data"], "id": k["id"]}, lib)
    name = body.get("name") or KINDS.get(kind, "Изделие")
    p = repo.product_create(order_id, name, kind, data)
    return _payload(p)


@router.get("/products/{pid}")
def get_product(pid: str):
    return _payload(_get(pid))


@router.put("/products/{pid}")
def update_product(pid: str, body: dict = Body(...)):
    _get(pid)
    p = repo.product_save(pid, name=body.get("name"), kind=body.get("kind"),
                          data=normalize(body["data"]) if body.get("data") is not None else None,
                          position=body.get("position"))
    return _payload(p)


@router.post("/preview")
def preview(body: dict = Body(...)):
    """Расчёт без сохранения (мастер создания, проверка формул)."""
    return resolve(normalize(body.get("data") or {}), repo.load_library())


@router.delete("/products/{pid}")
def delete_product(pid: str):
    with session() as c:
        if not c.execute("DELETE FROM products WHERE id=?", (pid,)).rowcount:
            raise HTTPException(404, "Изделие не найдено")
    return {"ok": True}


@router.post("/products/{pid}/duplicate")
def duplicate_product(pid: str, body: dict = Body(default={})):
    p = _get(pid)
    target = body.get("order_id") or p["order_id"]
    if not repo.order_get(target):
        raise HTTPException(404, "Заказ не найден")
    new = repo.product_create(target, f"{p['name']} (копия)", p["kind"], remap_ids(copy.deepcopy(p["data"])))
    return _payload(new)


@router.post("/products/{pid}/apply_template")
def product_apply_template(pid: str, body: dict = Body(...)):
    p = _get(pid)
    t = repo.lib_get(body.get("template_id") or "")
    if not t:
        raise HTTPException(404, "Шаблон не найден")
    data = apply_template(p["data"], {**t["data"], "id": t["id"]})
    if data.get("kit_id"):
        k = repo.lib_get(data["kit_id"])
        if k:
            data = apply_kit(data, {**k["data"], "id": k["id"]}, repo.load_library())
    return _payload(repo.product_save(pid, data=data))


@router.post("/products/{pid}/apply_kit")
def product_apply_kit(pid: str, body: dict = Body(...)):
    p = _get(pid)
    k = repo.lib_get(body.get("kit_id") or "")
    if not k:
        raise HTTPException(404, "Комплект не найден")
    data = apply_kit(p["data"], {**k["data"], "id": k["id"]}, repo.load_library())
    return _payload(repo.product_save(pid, data=data))


@router.post("/products/{pid}/save_as_template")
def save_as_template(pid: str, body: dict = Body(default={})):
    p = _get(pid)
    tdata = template_from_product(p["data"])
    tdata["kind"] = p["kind"]
    tdata["description"] = body.get("description") or f"Создан из изделия «{p['name']}»"
    item = repo.lib_create("construction_templates", body.get("name") or f"{p['name']} — шаблон", tdata)
    return item


def _slug(s: str) -> str:
    s = re.sub(r"[^\w\-]+", "_", s, flags=re.UNICODE).strip("_")
    return s or "glass"


@router.get("/products/{pid}/dxf")
def product_dxf_export(pid: str, glass_id: str = "", whole: bool = False, dims: bool = True):
    p = _get(pid)
    order = repo.order_get(p["order_id"]) or {}
    res = resolve(p["data"], repo.load_library())
    num = order.get("number") or ""
    prod_index = next((i for i, x in enumerate(repo.products_of(p["order_id"]), 1) if x["id"] == pid), 1)
    if whole:
        content = product_dxf(res, with_dims=dims, order_no=num)
        return Response(content, media_type="application/dxf",
                        headers={"Content-Disposition": f'attachment; filename="{_ascii(num)}-{prod_index}-construction.dxf"'})
    glasses = res["glasses"]
    if glass_id:
        g = next((g for g in glasses if g["id"] == glass_id), None)
        if not g:
            raise HTTPException(404, "Стекло не найдено")
        part = f"{num}-{prod_index}-{g['pos']}"
        content = glass_dxf(g, axes=res["axes"], with_dims=dims, order_no=num, part_no=part)
        return Response(content, media_type="application/dxf",
                        headers={"Content-Disposition": f'attachment; filename="{_ascii(part)}.dxf"'})
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        for g in glasses:
            part = f"{num}-{prod_index}-{g['pos']}"
            z.writestr(f"{part}_{_slug(g['name'])}.dxf", glass_dxf(g, axes=res["axes"], with_dims=dims, order_no=num, part_no=part))
        z.writestr(f"{num}-{prod_index}_construction.dxf", product_dxf(res, with_dims=dims, order_no=num))
    return Response(buf.getvalue(), media_type="application/zip",
                    headers={"Content-Disposition": f'attachment; filename="{_ascii(num)}-{prod_index}-dxf.zip"'})


def _ascii(s: str) -> str:
    return re.sub(r"[^A-Za-z0-9\-_.]", "_", s or "order")
