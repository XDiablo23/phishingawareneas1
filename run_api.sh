#!/usr/bin/env bash
set -e
DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$DIR/backend"
if [ ! -f ".venv/bin/python" ]; then
  echo "[ERROR] Backend venv missing at backend/.venv"
  exit 1
fi
echo "[i] Starting PhishAwareness API on http://0.0.0.0:8000 ..."
exec .venv/bin/uvicorn app.main:app --host 0.0.0.0 --port 8000
