"""Пути и настройки запуска. Данные всегда хранятся отдельно от кода."""
import os
from pathlib import Path

APP_DIR = Path(__file__).resolve().parent.parent
STATIC_DIR = APP_DIR / "static"

# По умолчанию при установке: /var/lib/glasscad (см. deploy/install.sh).
# Для разработки — ./data рядом с кодом.
DATA_DIR = Path(os.environ.get("GLASSCAD_DATA", APP_DIR / "data"))
DB_PATH = DATA_DIR / "glasscad.db"
UPLOADS_DIR = DATA_DIR / "uploads"
DXF_DIR = UPLOADS_DIR / "dxf"
BACKUP_DIR = DATA_DIR / "backups"

HOST = os.environ.get("GLASSCAD_HOST", "0.0.0.0")
PORT = int(os.environ.get("GLASSCAD_PORT", "8091"))

FONT_DIRS = [
    Path(os.environ.get("GLASSCAD_FONTS", APP_DIR / "fonts")),
    Path("/usr/share/fonts/truetype/dejavu"),
    Path("/usr/share/fonts/dejavu"),
    Path("/usr/share/fonts/TTF"),
]


def ensure_dirs() -> None:
    for d in (DATA_DIR, UPLOADS_DIR, DXF_DIR, BACKUP_DIR):
        d.mkdir(parents=True, exist_ok=True)
