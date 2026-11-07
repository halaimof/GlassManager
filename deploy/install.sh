#!/usr/bin/env bash
# Установка GlassCAD на Raspberry Pi / Debian / Ubuntu.
#   sudo ./deploy/install.sh
# Код: /opt/glasscad   Данные (БД, DXF, логотип, бэкапы): /var/lib/glasscad
set -euo pipefail

APP_DIR=${APP_DIR:-/opt/glasscad}
DATA_DIR=${DATA_DIR:-/var/lib/glasscad}
APP_USER=${APP_USER:-glasscad}
PORT=${PORT:-8091}
SRC_DIR=$(cd "$(dirname "$0")/.." && pwd)

if [[ $EUID -ne 0 ]]; then echo "Запустите через sudo"; exit 1; fi

echo "==> Системные пакеты"
apt-get update -qq
apt-get install -y -qq python3 python3-venv python3-pip fonts-dejavu-core rsync sqlite3 curl >/dev/null

echo "==> Пользователь $APP_USER"
id -u "$APP_USER" >/dev/null 2>&1 || useradd --system --home "$DATA_DIR" --shell /usr/sbin/nologin "$APP_USER"

echo "==> Код в $APP_DIR"
mkdir -p "$APP_DIR" "$DATA_DIR"
rsync -a --delete --exclude venv --exclude data --exclude .git --exclude '__pycache__' --exclude '.pytest_cache' \
  "$SRC_DIR"/ "$APP_DIR"/

echo "==> Python-окружение"
[[ -d "$APP_DIR/venv" ]] || python3 -m venv "$APP_DIR/venv"
"$APP_DIR/venv/bin/pip" install -q --upgrade pip
"$APP_DIR/venv/bin/pip" install -q -r "$APP_DIR/requirements.txt"

chown -R "$APP_USER":"$APP_USER" "$DATA_DIR"
chown -R root:root "$APP_DIR"

echo "==> systemd"
sed -e "s|@APP_DIR@|$APP_DIR|g" -e "s|@DATA_DIR@|$DATA_DIR|g" -e "s|@APP_USER@|$APP_USER|g" -e "s|@PORT@|$PORT|g" \
  "$APP_DIR/deploy/glasscad.service" > /etc/systemd/system/glasscad.service
systemctl daemon-reload
systemctl enable glasscad >/dev/null
systemctl restart glasscad

sleep 3
if curl -fsS "http://127.0.0.1:$PORT/api/version" >/dev/null; then
  IP=$(hostname -I 2>/dev/null | awk '{print $1}')
  echo "==> Готово: http://${IP:-localhost}:$PORT"
else
  echo "Сервис не ответил. Журнал: journalctl -u glasscad -n 50"; exit 1
fi
