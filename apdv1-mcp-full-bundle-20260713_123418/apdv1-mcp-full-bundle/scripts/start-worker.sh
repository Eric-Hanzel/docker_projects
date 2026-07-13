#!/usr/bin/env bash
set -euo pipefail

BUNDLE_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
APDV1_ROOT="$BUNDLE_ROOT/apdv1"
STATE_DIR="$APDV1_ROOT/.codex/state"
LOG_FILE="$STATE_DIR/app_server_runner.nohup.log"
PID_FILE="$STATE_DIR/app_server_runner.pid"

mkdir -p "$STATE_DIR"

if [[ -f "$PID_FILE" ]]; then
  PID="$(cat "$PID_FILE" || true)"
  if [[ -n "$PID" ]] && kill -0 "$PID" 2>/dev/null; then
    echo "APDv1 worker already running pid=$PID"
    exit 0
  fi
  rm -f "$PID_FILE"
fi

cd "$APDV1_ROOT"
nohup setsid python3 app_server/runner.py serve >"$LOG_FILE" 2>&1 &
PID="$!"
echo "$PID" >"$PID_FILE"

sleep 0.5
if ! kill -0 "$PID" 2>/dev/null; then
  rm -f "$PID_FILE"
  echo "FAIL: APDv1 worker exited during startup. Log: $LOG_FILE" >&2
  tail -n 80 "$LOG_FILE" >&2 || true
  exit 1
fi

echo "Started APDv1 worker pid=$PID log=$LOG_FILE"
