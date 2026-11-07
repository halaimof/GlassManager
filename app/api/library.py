from __future__ import annotations

import shutil
from pathlib import Path

from fastapi import APIRouter, Body, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse

from .. import repo
from ..config import DXF_DIR
from ..db import dumps, new_id, now_iso, session
from ..engine.hardware import CONNECTION_TYPES
from ..engine.library import profile_deduction
from ..engine.model import PANEL_TYPES
from ..engine.operations import X_REFS, Y_REFS
from ..hardware_dxf import DxfImportError, parse_dxf

router = APIRouter(prefix="/api", tags=["library"])


def _check(coll: str):
    if coll not in repo.LIB_COLLECTIONS:
        raise HTTPException(404, "Неизвестный раздел библиотеки")


@router.get("/meta")
def meta():
    """Справочники для интерфейса."""
    return {
        "collections": repo.LIB_COLLECTIONS,
        "panel_types": PANEL_TYPES,
        "connection_types": CONNECTION_TYPES,
        "x_refs": X_REFS,
        "y_refs": Y_REFS,
    }


@router.get("/lib/{coll}")
def lib_list(coll: str):
    _check(coll)
    items = repo.lib_list(coll)
    if coll == "profiles":
        for it in items:
            it["deduction"] = profile_deduction(it["data"])
    return items


@router.post("/lib/{coll}")
def lib_create(coll: str, body: dict = Body(...)):
    _check(coll)
    name = (body.get("name") or "").strip() or "Без названия"
    return repo.lib_create(coll, name, body.get("data") or {})


@router.get("/lib/{coll}/{item_id}")
def lib_get(coll: str, item_id: str):
    _check(coll)
    it = repo.lib_get(item_id)
    if not it or it["collection"] != coll:
        raise HTTPException(404, "Не найдено")
    return it


@router.put("/lib/{coll}/{item_id}")
def lib_update(coll: str, item_id: str, body: dict = Body(...)):
    lib_get(coll, item_id)
    return repo.lib_update(item_id, body.get("name"), body.get("data"))


@router.delete("/lib/{coll}/{item_id}")
def lib_delete(coll: str, item_id: str):
    lib_get(coll, item_id)
    repo.lib_delete(item_id)
    return {"ok": True}


@router.post("/lib/{coll}/{item_id}/duplicate")
def lib_duplicate(coll: str, item_id: str):
    lib_get(coll, item_id)
    return repo.lib_duplicate(item_id)


# ------------------------------------------------------------------ DXF фурнитуры
@router.get("/dxf")
def dxf_list():
    return repo.dxf_list()


def store_dxf(src_path: Path, name: str, original: str) -> dict:
    parsed = parse_dxf(src_path)
    did = new_id()
    stored = f"{did}.dxf"
    shutil.copyfile(src_path, DXF_DIR / stored)
    ts = now_iso()
    with session() as c:
        c.execute("INSERT INTO dxf_files(id, name, original_filename, stored_name, data, created_at, updated_at) "
                  "VALUES (?,?,?,?,?,?,?)", (did, name, original, stored, dumps(parsed), ts, ts))
    return repo.dxf_get(did)


@router.post("/dxf")
async def dxf_upload(file: UploadFile = File(...), name: str = Form("")):
    if not (file.filename or "").lower().endswith(".dxf"):
        raise HTTPException(400, "Нужен файл .dxf")
    tmp = DXF_DIR / f"upload-{new_id()}.tmp"
    with tmp.open("wb") as f:
        shutil.copyfileobj(file.file, f)
    try:
        return store_dxf(tmp, name.strip() or Path(file.filename).stem, file.filename)
    except DxfImportError as e:
        raise HTTPException(400, str(e)) from e
    finally:
        tmp.unlink(missing_ok=True)


@router.get("/dxf/{dxf_id}")
def dxf_get(dxf_id: str):
    d = repo.dxf_get(dxf_id)
    if not d:
        raise HTTPException(404, "DXF не найден")
    return d


@router.put("/dxf/{dxf_id}")
def dxf_rename(dxf_id: str, body: dict = Body(...)):
    dxf_get(dxf_id)
    with session() as c:
        c.execute("UPDATE dxf_files SET name=?, updated_at=? WHERE id=?", (body.get("name") or "DXF", now_iso(), dxf_id))
    return repo.dxf_get(dxf_id)


@router.post("/dxf/{dxf_id}/duplicate")
def dxf_duplicate(dxf_id: str):
    d = dxf_get(dxf_id)
    return store_dxf(DXF_DIR / d["stored_name"], f"{d['name']} (копия)", d["original_filename"])


@router.delete("/dxf/{dxf_id}")
def dxf_delete(dxf_id: str):
    d = dxf_get(dxf_id)
    with session() as c:
        c.execute("DELETE FROM dxf_files WHERE id=?", (dxf_id,))
    (DXF_DIR / d["stored_name"]).unlink(missing_ok=True)
    return {"ok": True}


@router.get("/dxf/{dxf_id}/file")
def dxf_file(dxf_id: str):
    d = dxf_get(dxf_id)
    return FileResponse(DXF_DIR / d["stored_name"], filename=d["original_filename"] or f"{d['name']}.dxf")
