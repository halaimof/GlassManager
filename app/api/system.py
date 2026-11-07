from __future__ import annotations

import shutil
from pathlib import Path

from fastapi import APIRouter, Body, File, HTTPException, UploadFile
from fastapi.responses import FileResponse

from .. import VERSION, repo
from ..config import BACKUP_DIR, DATA_DIR, UPLOADS_DIR
from ..db import backup_db, schema_version

router = APIRouter(prefix="/api", tags=["system"])


@router.get("/version")
def version():
    return {"app": "GlassCAD", "version": VERSION, "schema": schema_version(), "data_dir": str(DATA_DIR)}


@router.get("/settings")
def get_settings():
    s = repo.settings_get()
    return {"company": s.get("company") or {}}


@router.put("/settings")
def put_settings(body: dict = Body(...)):
    if "company" in body:
        cur = repo.settings_get().get("company") or {}
        cur.update(body["company"] or {})
        repo.settings_set({"company": cur})
    return get_settings()


@router.post("/settings/logo")
async def upload_logo(file: UploadFile = File(...)):
    ext = Path(file.filename or "").suffix.lower()
    if ext not in (".png", ".jpg", ".jpeg"):
        raise HTTPException(400, "Логотип: PNG или JPG")
    name = f"logo{ext}"
    with (UPLOADS_DIR / name).open("wb") as f:
        shutil.copyfileobj(file.file, f)
    cur = repo.settings_get().get("company") or {}
    cur["logo"] = name
    repo.settings_set({"company": cur})
    return get_settings()


@router.get("/settings/logo")
def get_logo():
    logo = (repo.settings_get().get("company") or {}).get("logo")
    if not logo or not (UPLOADS_DIR / logo).exists():
        raise HTTPException(404, "Нет логотипа")
    return FileResponse(UPLOADS_DIR / logo)


@router.delete("/settings/logo")
def delete_logo():
    cur = repo.settings_get().get("company") or {}
    cur.pop("logo", None)
    repo.settings_set({"company": cur})
    return get_settings()


@router.post("/backup")
def make_backup():
    return {"file": backup_db("manual")}


@router.get("/backups")
def list_backups():
    return [{"name": f.name, "size": f.stat().st_size} for f in sorted(BACKUP_DIR.glob("*.db"), reverse=True)]


@router.get("/backups/{name}")
def download_backup(name: str):
    f = BACKUP_DIR / Path(name).name
    if not f.exists():
        raise HTTPException(404, "Нет файла")
    return FileResponse(f, filename=f.name)
