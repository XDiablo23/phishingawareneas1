#!/usr/bin/env bash
set -e
DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$DIR/portal"
PYEXE="$DIR/backend/.venv/bin/python"
if [ ! -f "$PYEXE" ]; then
  echo "[ERROR] Backend venv missing at backend/.venv"
  exit 1
fi
export PA_BASE_URL="${PA_BASE_URL:-http://127.0.0.1:8000}"
export PORTAL_AUTO_SYNC_SECONDS="${PORTAL_AUTO_SYNC_SECONDS:-300}"
echo "[i] Starting Remediation Portal on http://0.0.0.0:8100 ..."
exec "$PYEXE" -m uvicorn app.main:app --host 0.0.0.0 --port 8100
