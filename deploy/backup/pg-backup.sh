#!/usr/bin/env bash
# Ежедневный бэкап базы. Запуск из cron от root (см. deploy/README.md):
#   30 3 * * * bash /opt/detailing/deploy/backup/pg-backup.sh >> /var/log/detailing-backup.log 2>&1
#
# Делает дамп в формате custom (сжатый, восстанавливается pg_restore),
# хранит последние KEEP_DAYS дней. Если задан RCLONE_REMOTE (например,
# "s3:detailing-backups") и установлен rclone, копирует дамп ещё и туда:
# бэкап на том же сервере не спасёт, если сервер пропадёт целиком.

set -Eeuo pipefail

PROJECT_DIR="${PROJECT_DIR:-/opt/detailing}"
BACKUP_DIR="${BACKUP_DIR:-/var/backups/detailing}"
KEEP_DAYS="${KEEP_DAYS:-14}"
RCLONE_REMOTE="${RCLONE_REMOTE:-}"

timestamp="$(date +%Y%m%d-%H%M%S)"
target="$BACKUP_DIR/db-$timestamp.dump"

install -d -m 0700 "$BACKUP_DIR"
cd "$PROJECT_DIR"

# Пишем во временный файл: оборванный дамп не должен выглядеть как готовый.
docker compose exec -T postgres sh -c \
  'pg_dump -U "$POSTGRES_USER" -d "$POSTGRES_DB" --format=custom --compress=9' \
  >"$target.part"
mv "$target.part" "$target"
chmod 0600 "$target"
echo "$(date -Is) бэкап готов: $target ($(du -h "$target" | cut -f1))"

find "$BACKUP_DIR" -name 'db-*.dump' -mtime +"$KEEP_DAYS" -delete
find "$BACKUP_DIR" -name 'db-*.dump.part' -mmin +60 -delete

if [[ -n "$RCLONE_REMOTE" ]] && command -v rclone >/dev/null; then
  rclone copy "$target" "$RCLONE_REMOTE/" --quiet
  echo "$(date -Is) скопирован в $RCLONE_REMOTE"
fi
