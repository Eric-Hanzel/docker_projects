#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
if [ "$#" -eq 0 ]; then
  exec python3 "$ROOT_DIR/app_server/runner.py" --target-file "$ROOT_DIR/batch/target.txt"
fi

if [[ "${1:-}" == --* ]]; then
  exec python3 "$ROOT_DIR/app_server/runner.py" "$@"
fi

TARGET_FILE="$1"
shift || true
exec python3 "$ROOT_DIR/app_server/runner.py" --target-file "$TARGET_FILE" "$@"
