#!/bin/sh
set -eu

ROOT=$(CDPATH= cd -- "$(dirname "$0")/.." && pwd)
cd "$ROOT"

if [ ! -x .venv/bin/python ]; then
  if ! python3 -m venv .venv; then
    DEBIAN_FRONTEND=noninteractive apt-get update
    DEBIAN_FRONTEND=noninteractive apt-get install -y python3-venv
    python3 -m venv .venv
  fi
fi

.venv/bin/pip install -r requirements.txt
