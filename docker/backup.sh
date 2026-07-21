#!/bin/sh
# Runs daily at 3:00 AM UTC via crontab
# Crontab entry: 0 3 * * * /backup.sh >> /var/log/backup.log 2>&1
BACKUP_DIR="/backups"
DATE=$(date +%Y%m%d_%H%M%S)
FILENAME="$BACKUP_DIR/stf_backup_$DATE.sql.gz"

pg_dump -h db -U "$POSTGRES_USER" "$POSTGRES_DB" | gzip > "$FILENAME"

# Keep only last 7 backups
ls -t "$BACKUP_DIR"/stf_backup_*.sql.gz | tail -n +8 | xargs rm -f

echo "Backup completed: $FILENAME"
