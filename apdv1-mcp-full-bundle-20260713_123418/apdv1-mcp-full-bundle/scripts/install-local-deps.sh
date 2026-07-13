#!/usr/bin/env bash
set -euo pipefail

BUNDLE_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

cd "$BUNDLE_ROOT"
python3 -m pip install --break-system-packages --target .deps 'mcp==1.27.2'

echo "Installed MCP runtime dependencies into $BUNDLE_ROOT/.deps"
echo "Use ./scripts/start-mcp-stdio.sh for stdio MCP clients."

