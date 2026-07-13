#!/usr/bin/env bash
set -euo pipefail

BUNDLE_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
APDV1_ROOT="$BUNDLE_ROOT/apdv1"
STATE_DIR="$APDV1_ROOT/.codex/state"
LOG_FILE="$STATE_DIR/app_server_deploy_api.nohup.log"
PID_FILE="$STATE_DIR/app_server_deploy_api.pid"
HOST="${APDV1_API_HOST:-127.0.0.1}"
PORT="${APP_DEPLOY_API_PORT:-18084}"

mkdir -p "$STATE_DIR"

if [[ -f "$PID_FILE" ]]; then
  PID="$(cat "$PID_FILE" || true)"
  if [[ -n "$PID" ]] && kill -0 "$PID" 2>/dev/null; then
    echo "APDv1 HTTP API already running pid=$PID http://$HOST:$PORT"
    exit 0
  fi
  rm -f "$PID_FILE"
fi

cd "$APDV1_ROOT"
nohup setsid python3 app_server/deploy_api.py --host "$HOST" --port "$PORT" >"$LOG_FILE" 2>&1 &
PID="$!"
echo "$PID" >"$PID_FILE"

for _ in {1..30}; do
  if ! kill -0 "$PID" 2>/dev/null; then
    rm -f "$PID_FILE"
    echo "FAIL: APDv1 HTTP API exited during startup. Log: $LOG_FILE" >&2
    tail -n 80 "$LOG_FILE" >&2 || true
    exit 1
  fi
  if python3 - "$HOST" "$PORT" <<'PY' >/dev/null 2>&1
import json
import sys
import urllib.request

host, port = sys.argv[1], sys.argv[2]
with urllib.request.urlopen(f"http://{host}:{port}/healthz", timeout=1) as response:
    payload = json.loads(response.read().decode("utf-8"))
raise SystemExit(0 if payload.get("ok") is True else 1)
PY
  then
    echo "Started APDv1 HTTP API pid=$PID url=http://$HOST:$PORT log=$LOG_FILE"
    exit 0
  fi
  sleep 0.2
done

rm -f "$PID_FILE"
echo "FAIL: APDv1 HTTP API did not become healthy at http://$HOST:$PORT. Log: $LOG_FILE" >&2
tail -n 80 "$LOG_FILE" >&2 || true
exit 1
