#!/usr/bin/env bash
# Starts the API, worker, and frontend together for local testing.
# All three need to be running for an upload to actually complete, and
# it's easy to forget one after a restart — this starts (or stops) them
# as a unit instead.
#
# Usage:
#   ./dev.sh        start all three, block until Ctrl+C
#   ./dev.sh stop   stop anything left running from a previous run

set -e

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PID_DIR="/tmp/resume-parser-dev"
mkdir -p "$PID_DIR"

stop_all() {
  [ -f "$PID_DIR/api.pid" ] && { kill "$(cat "$PID_DIR/api.pid")" 2>/dev/null || true; }
  [ -f "$PID_DIR/worker.pid" ] && { kill "$(cat "$PID_DIR/worker.pid")" 2>/dev/null || true; }
  # npm run dev's child next-server process doesn't get SIGTERM'd via its
  # parent, so free the port directly instead. fuser, not lsof — lsof
  # didn't reliably see the listening socket in testing. Exits non-zero
  # when a port's already free, which is fine, not an error.
  fuser -k -TERM 3000/tcp 2>/dev/null || true
  fuser -k -TERM 8000/tcp 2>/dev/null || true
  rm -f "$PID_DIR"/*.pid
}

if [ "${1:-}" = "stop" ]; then
  echo "Stopping dev servers..."
  stop_all
  echo "Stopped."
  exit 0
fi

trap 'echo; echo "Stopping dev servers..."; stop_all; exit 0' INT TERM

cd "$ROOT_DIR"

echo "Starting API on :8000..."
uv run uvicorn api.main:app --port 8000 > "$PID_DIR/api.log" 2>&1 &
echo $! > "$PID_DIR/api.pid"

echo "Starting worker..."
uv run python -m worker.run > "$PID_DIR/worker.log" 2>&1 &
echo $! > "$PID_DIR/worker.pid"

echo "Starting frontend on :3000..."
(cd web && npm run dev > "$PID_DIR/web.log" 2>&1) &
echo $! > "$PID_DIR/web.pid"

echo "Waiting for servers to come up..."
timeout 30 bash -c 'until curl -sf http://localhost:8000/docs >/dev/null; do sleep 1; done'
echo "  API ready      http://localhost:8000 (docs at /docs)"
timeout 30 bash -c 'until curl -sf http://localhost:3000 >/dev/null; do sleep 1; done'
echo "  Frontend ready http://localhost:3000"

echo
echo "Logs: $PID_DIR/{api,worker,web}.log"
echo "Press Ctrl+C to stop everything (or run './dev.sh stop' from another shell)."

wait
