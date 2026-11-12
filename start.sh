#!/usr/bin/env bash
set -e
DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$DIR"

echo "============================================================"
echo "  PhishAwareness - One-Click Launcher (Linux)"
echo "============================================================"

cleanup() {
  echo ""
  echo "Shutting down PhishAwareness services..."
  kill "$PID_API" "$PID_PORTAL" "$PID_WEB" 2>/dev/null || true
  wait "$PID_API" "$PID_PORTAL" "$PID_WEB" 2>/dev/null || true
  echo "All services stopped."
  exit 0
}
trap cleanup SIGINT SIGTERM

# Start API
echo "[1/3] Starting PhishAwareness API on port 8000..."
"$DIR/run_api.sh" > /tmp/phishawareness_api.log 2>&1 &
PID_API=$!

# Start Portal
echo "[2/3] Starting Remediation Portal on port 8100..."
"$DIR/run_portal.sh" > /tmp/phishawareness_portal.log 2>&1 &
PID_PORTAL=$!

# Start Web Frontend
echo "[3/3] Starting Operator Console (Web UI) on port 5173..."
"$DIR/run_web.sh" > /tmp/phishawareness_web.log 2>&1 &
PID_WEB=$!

sleep 3

echo ""
echo "============================================================"
echo "  All services started successfully!"
echo "    - Operator Console (Web UI): http://localhost:5173"
echo "    - Remediation Portal:        http://localhost:8100"
echo "    - Backend API:               http://localhost:8000"
echo "    - Interactive API Docs:      http://localhost:8000/docs"
echo ""
echo "  Logs:"
echo "    - API:     tail -f /tmp/phishawareness_api.log"
echo "    - Portal:  tail -f /tmp/phishawareness_portal.log"
echo "    - Console: tail -f /tmp/phishawareness_web.log"
echo ""
echo "  Quick Start:"
echo "    1. Open http://localhost:5173 in your browser."
echo "    2. Click 'Create demo organization' to seed synthetic employees & campaigns."
echo "    3. Sign in with the generated demo operator credentials."
echo "============================================================"
echo "Press Ctrl+C to stop all services."

wait "$PID_API" "$PID_PORTAL" "$PID_WEB"
