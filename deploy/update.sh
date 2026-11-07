#!/usr/bin/env bash
# Обновление GlassCAD без потери данных.
#   sudo ./deploy/update.sh                 — из папки, где лежит этот скрипт (новая версия кода)
#   sudo ./deploy/update.sh glasscad.tar.gz — из архива
# Порядок: резервная копия БД → остановка → замена кода (старый код сохраняется) →
# зависимости → запуск (миграции применяются автоматически, с ещё одним бэкапом) →
# проверка; при ошибке код откатывается.
set -euo pipefail

APP_DIR=${APP_DIR:-/opt/glasscad}
DATA_DIR=${DATA_DIR:-/var/lib/glasscad}
PORT=${PORT:-8091}
SRC=${1:-$(cd "$(dirname "$0")/.." && pwd)}

if [[ $EUID -ne 0 ]]; then echo "Запустите через sudo"; exit 1; fi

TMP=""
if [[ -f "$SRC" ]]; then
  TMP=$(mktemp -d)
  tar -xzf "$SRC" -C "$TMP"
  SRC=$(find "$TMP" -maxdepth 2 -name requirements.txt -printf '%h\n' | head -1)
fi
[[ -f "$SRC/app/__init__.py" ]] || { echo "Не найден код GlassCAD в $SRC"; exit 1; }

NEW_VER=$(grep -oP 'VERSION = "\K[^"]+' "$SRC/app/__init__.py")
OLD_VER=$(grep -oP 'VERSION = "\K[^"]+' "$APP_DIR/app/__init__.py" 2>/dev/null || echo "-")
echo "==> Обновление $OLD_VER → $NEW_VER"

echo "==> Резервная копия БД"
"$(dirname "$0")/backup.sh" "pre-update-$OLD_VER" || { echo "Бэкап не удался — обновление прервано"; exit 1; }

systemctl stop glasscad || true

PREV="$APP_DIR.prev"
rm -rf "$PREV"
cp -a "$APP_DIR" "$PREV"

rsync -a --delete --exclude venv --exclude data --exclude .git --exclude '__pycache__' --exclude '.pytest_cache' "$SRC"/ "$APP_DIR"/
"$APP_DIR/venv/bin/pip" install -q -r "$APP_DIR/requirements.txt"
cp "$APP_DIR/deploy/glasscad.service" /tmp/glasscad.service.tpl
sed -i -e "s|@APP_DIR@|$APP_DIR|g" -e "s|@DATA_DIR@|$DATA_DIR|g" -e "s|@APP_USER@|${APP_USER:-glasscad}|g" -e "s|@PORT@|$PORT|g" /tmp/glasscad.service.tpl
mv /tmp/glasscad.service.tpl /etc/systemd/system/glasscad.service
systemctl daemon-reload
systemctl start glasscad

ok=0
for _ in $(seq 1 15); do
  sleep 1
  if curl -fsS "http://127.0.0.1:$PORT/api/version" >/dev/null 2>&1; then ok=1; break; fi
done

if [[ $ok -eq 1 ]]; then
  echo "==> Готово. Версия: $(curl -fsS http://127.0.0.1:$PORT/api/version)"
else
  echo "!! Новая версия не запустилась — откат кода. БД не изменена или восстановима из $DATA_DIR/backups"
  systemctl stop glasscad || true
  rm -rf "$APP_DIR"; mv "$PREV" "$APP_DIR"
  systemctl start glasscad
  exit 1
fi
[[ -n "$TMP" ]] && rm -rf "$TMP"
exit 0
