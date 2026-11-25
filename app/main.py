"""Точка входа: uvicorn app.main:app --host 0.0.0.0 --port 8091"""
from __future__ import annotations

import logging
import os
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from . import VERSION
from .api import library, orders, products, system
from .crm import api as crm_api
from .crm.channels import Poller
from .crm.seed import seed_crm
from .config import HOST, PORT, STATIC_DIR, ensure_dirs
from .db import migrate
from .seed import seed

log = logging.getLogger("glasscad")


def startup() -> None:
    ensure_dirs()
    applied = migrate()
    if applied:
        log.info("Применены миграции: %s", applied)
    seed()
    seed_crm()


@asynccontextmanager
async def lifespan(_app: FastAPI):
    startup()
    poller = None
    if not os.environ.get("GLASSCAD_NO_POLLER"):
        poller = Poller()
        poller.start()
    yield
    if poller:
        poller.stop_event.set()


app = FastAPI(title="GlassCAD", version=VERSION, lifespan=lifespan)
app.include_router(orders.router)
app.include_router(products.router)
app.include_router(library.router)
app.include_router(system.router)
app.include_router(crm_api.router)
app.include_router(crm_api.inbound)


@app.exception_handler(ValueError)
async def value_error_handler(_request: Request, exc: ValueError):
    return JSONResponse({"detail": str(exc)}, status_code=400)


@app.middleware("http")
async def no_stale_frontend(request: Request, call_next):
    """Браузер всегда сверяет файлы интерфейса с сервером (ETag → 304, это дёшево).
    Без этого после обновления браузер мог смешать старые и новые JS-модули."""
    response = await call_next(request)
    path = request.url.path
    if path == "/" or path.startswith("/static/"):
        response.headers["Cache-Control"] = "no-cache"
    return response


app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")


@app.get("/")
def index():
    return FileResponse(STATIC_DIR / "index.html", headers={"Cache-Control": "no-cache"})


def run() -> None:
    import uvicorn

    uvicorn.run("app.main:app", host=HOST, port=PORT, log_level="info")


if __name__ == "__main__":
    run()
