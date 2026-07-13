#!/usr/bin/env bash
set -euo pipefail

BUNDLE_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
OUT_DIR="${APDV1_MCP_PACKAGE_OUT_DIR:-$BUNDLE_ROOT/dist}"
STAMP="$(date +%Y%m%d_%H%M%S)"
ARCHIVE="$OUT_DIR/apdv1-mcp-full-bundle-$STAMP.tar.gz"

mkdir -p "$OUT_DIR"
cd "$BUNDLE_ROOT/.."
tar \
  --exclude='apdv1-mcp-full-bundle/dist' \
  --exclude='apdv1-mcp-full-bundle/.deps' \
  --exclude='apdv1-mcp-full-bundle/.venv' \
  --exclude='apdv1-mcp-full-bundle/apdv1/.codex/state' \
  --exclude='apdv1-mcp-full-bundle/apdv1/app_server/runs' \
  --exclude='apdv1-mcp-full-bundle/apdv1/app_server/results' \
  --exclude='apdv1-mcp-full-bundle/apdv1/Deliverable' \
  --exclude='apdv1-mcp-full-bundle/apdv1/DP_LOGS' \
  --exclude='apdv1-mcp-full-bundle/=1.0.0' \
  --exclude='__pycache__' \
  --exclude='.pytest_cache' \
  --exclude='.mypy_cache' \
  --exclude='.ruff_cache' \
  --exclude='*.pyc' \
  --exclude='*.pyo' \
  --exclude='*.log' \
  --exclude='*.pid' \
  --exclude='*.tmp' \
  -czf "$ARCHIVE" \
  apdv1-mcp-full-bundle

echo "$ARCHIVE"
