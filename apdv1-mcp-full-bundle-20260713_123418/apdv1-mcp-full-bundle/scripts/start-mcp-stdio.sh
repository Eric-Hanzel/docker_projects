#!/usr/bin/env bash
set -euo pipefail

BUNDLE_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
export APDV1_API_BASE="${APDV1_API_BASE:-http://127.0.0.1:18084}"

cd "$BUNDLE_ROOT"
if [[ -d "$BUNDLE_ROOT/.deps" ]]; then
  export PYTHONPATH="$BUNDLE_ROOT/.deps:$BUNDLE_ROOT/mcp_server_apdv1/src:${PYTHONPATH:-}"
fi

if command -v apdv1-mcp-server >/dev/null 2>&1; then
  exec apdv1-mcp-server
fi

export PYTHONPATH="$BUNDLE_ROOT/mcp_server_apdv1/src:${PYTHONPATH:-}"
exec python3 -m apdv1_mcp_server.server
