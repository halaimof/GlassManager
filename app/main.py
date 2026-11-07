"""Точка входа: uvicorn app.main:app --host 0.0.0.0 --port 8091"""
from __future__ import annotations

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from . import VERSION
from .api import library, orders, products, system
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


@asynccontextmanager
async def lifespan(_app: FastAPI):
    startup()
    yield


app = FastAPI(title="GlassCAD", version=VERSION, lifespan=lifespan)
app.include_router(orders.router)
app.include_router(products.router)
app.include_router(library.router)
app.include_router(system.router)


@app.exception_handler(ValueError)
async def value_error_handler(_request: Request, exc: ValueError):
    return JSONResponse({"detail": str(exc)}, status_code=400)


app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")


@app.get("/")
def index():
    return FileResponse(STATIC_DIR / "index.html", headers={"Cache-Control": "no-cache"})


def run() -> None:
    import uvicorn

    uvicorn.run("app.main:app", host=HOST, port=PORT, log_level="info")


if __name__ == "__main__":
    run()
