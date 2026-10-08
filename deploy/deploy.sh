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
  --exclude '.cursor/rules/local-context.mdc' \
  --exclude '*.session' \
  --exclude '*.session-journal' \
  --exclude 'login_state.json' \
  --exclude 'login_code' \
  --exclude 'login_password' \
  --exclude 'subscribers.json' \
  --exclude 'keyword_stats.json' \
  --exclude 'keyword_stats.json.tmp' \
  --exclude '__pycache__/' \
  --exclude '.venv/' \
  --exclude 'venv/' \
  "$ROOT/" "$HOST:$DEST/"

ssh -o BatchMode=yes -o ConnectTimeout=20 "$HOST" \
  "rm -f '$DEST/.DS_Store' && chown -R root:root '$DEST' && if [ -x '$DEST/.venv/bin/pip' ]; then '$DEST/.venv/bin/pip' install -q -r '$DEST/requirements.txt'; fi && if systemctl is-active --quiet kimparser; then systemctl restart kimparser; fi"
