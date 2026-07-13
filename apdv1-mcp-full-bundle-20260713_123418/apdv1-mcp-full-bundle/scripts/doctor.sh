#!/usr/bin/env bash
set -euo pipefail

BUNDLE_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
APDV1_ROOT="$BUNDLE_ROOT/apdv1"
API_BASE="${APDV1_API_BASE:-http://127.0.0.1:18084}"
export PYTHONPATH="$BUNDLE_ROOT/.deps:$BUNDLE_ROOT/mcp_server_apdv1/src:${PYTHONPATH:-}"

fail() {
  echo "FAIL: $*" >&2
  exit 1
}

echo "APDv1 MCP bundle doctor"
echo "bundle: $BUNDLE_ROOT"

[[ -d "$APDV1_ROOT/app_server" ]] || fail "missing bundled apdv1/app_server"
[[ -f "$APDV1_ROOT/AGENTS.md" ]] || fail "missing bundled AGENTS.md"

command -v python3 >/dev/null || fail "python3 not found"
command -v codex >/dev/null || echo "WARN: codex not found in PATH; deployments will fail until Codex CLI is installed"
command -v docker >/dev/null || echo "WARN: docker not found in PATH; Docker-based deployments will fail"

python3 - <<'PY' || fail "apdv1_mcp_server package is not importable; run: python3 -m pip install -e mcp_server_apdv1"
import apdv1_mcp_server
print("mcp package import: ok", apdv1_mcp_server.__version__)
PY

python3 - <<'PY' || fail "mcp SDK is not importable; run: python3 -m pip install -e mcp_server_apdv1"
import mcp
print("mcp sdk import: ok")
PY

echo "checking APDv1 HTTP API: $API_BASE/healthz"
python3 - "$API_BASE" <<'PY'
import json
import sys
import urllib.request

base = sys.argv[1].rstrip("/")
with urllib.request.urlopen(base + "/healthz", timeout=5) as response:
    payload = json.loads(response.read().decode("utf-8"))
if payload.get("ok") is not True:
    raise SystemExit(f"unexpected health payload: {payload}")
print("api health: ok")
PY

python3 - "$API_BASE" <<'PY'
import json
import sys
import urllib.request

base = sys.argv[1].rstrip("/")
with urllib.request.urlopen(base + "/status", timeout=5) as response:
    payload = json.loads(response.read().decode("utf-8"))
print("queue_counts:", json.dumps(payload.get("queue_counts", {}), sort_keys=True))
PY

echo "doctor: ok"
