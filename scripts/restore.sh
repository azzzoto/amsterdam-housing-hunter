#!/bin/sh
set -eu

if [ "$#" -ne 1 ]; then
  echo "Usage: scripts/restore.sh /path/to/housing-backup.sqlite3" >&2
  exit 2
fi
backup="$1"
target="${DATA_DIR:-./data}/housing.db"
if [ ! -f "$backup" ]; then
  echo "Backup file not found: $backup" >&2
  exit 1
fi
mkdir -p "$(dirname "$target")"
if [ -f "$target" ]; then
  cp "$target" "${target}.before-restore"
fi
cp "$backup" "$target"
python3 -m app.main --healthcheck
echo "Restored $target"
