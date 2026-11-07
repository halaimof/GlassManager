#!/usr/bin/env bash
# Резервная копия БД (безопасна при работающем сервисе — sqlite .backup).
#   ./deploy/backup.sh [метка]
# Для ежедневной копии: echo '30 2 * * * root /opt/glasscad/deploy/backup.sh daily' > /etc/cron.d/glasscad
set -euo pipefail
DATA_DIR=${DATA_DIR:-/var/lib/glasscad}
DB="$DATA_DIR/glasscad.db"
LABEL=${1:-manual}
mkdir -p "$DATA_DIR/backups"
if [[ ! -f "$DB" ]]; then echo "БД ещё не создана ($DB) — копировать нечего"; exit 0; fi
OUT="$DATA_DIR/backups/glasscad-$(date +%Y%m%d-%H%M%S)-$LABEL.db"
if command -v sqlite3 >/dev/null 2>&1; then
  sqlite3 "$DB" ".backup '$OUT'"
else
  python3 -c "import sqlite3,sys; s=sqlite3.connect(sys.argv[1]); d=sqlite3.connect(sys.argv[2]); s.backup(d); d.close()" "$DB" "$OUT"
fi
# DXF и логотип — архивом рядом (без перезаписи)
tar -czf "${OUT%.db}-uploads.tar.gz" -C "$DATA_DIR" uploads 2>/dev/null || true
chown --reference="$DATA_DIR" "$OUT" "${OUT%.db}-uploads.tar.gz" 2>/dev/null || true
# хранить последние 60 копий
ls -1t "$DATA_DIR"/backups/glasscad-*.db 2>/dev/null | tail -n +61 | while read -r f; do rm -f "$f" "${f%.db}-uploads.tar.gz"; done
echo "$OUT"
