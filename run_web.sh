#!/usr/bin/env bash
set -e
DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$DIR/frontend"
if [ ! -d "node_modules" ]; then
  echo "[i] Installing frontend dependencies..."
  npm install
fi
echo "[i] Starting Frontend console on http://0.0.0.0:5173 ..."
exec npm run dev -- --host 0.0.0.0
