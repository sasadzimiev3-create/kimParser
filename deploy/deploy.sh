#!/bin/sh
set -eu

HOST=root@31.76.53.4
DEST=/opt/kimparser
ROOT=$(CDPATH= cd -- "$(dirname "$0")/.." && pwd)

ssh -o BatchMode=yes -o ConnectTimeout=20 "$HOST" "mkdir -p '$DEST'"

rsync -az --delete --timeout=60 \
  --exclude '.git/' \
  --exclude '.DS_Store' \
  --exclude '.env' \
  --exclude '*.session' \
  --exclude '__pycache__/' \
  --exclude '.venv/' \
  --exclude 'venv/' \
  "$ROOT/" "$HOST:$DEST/"

ssh -o BatchMode=yes -o ConnectTimeout=20 "$HOST" \
  "rm -f '$DEST/.DS_Store' && chown -R root:root '$DEST' && if systemctl cat kimparser.service >/dev/null 2>&1; then systemctl restart kimparser; fi"
