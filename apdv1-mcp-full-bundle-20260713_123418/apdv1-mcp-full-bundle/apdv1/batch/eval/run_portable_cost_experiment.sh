#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
TARGET_FILE="${EVAL_TARGET_FILE:-$ROOT_DIR/batch/eval/datasets/apdv1_portable_cost_balanced_6.jsonl}"
TIMEOUT_MINUTES="${TIMEOUT_MINUTES:-120}"

echo "Cleaning existing portable-cost target outputs"
bash "$ROOT_DIR/batch/eval/scripts/clean_portable_cost_targets.sh" --apply

echo "Running APDv1 portable bundle cost eval"
EVAL_TARGET_FILE="$TARGET_FILE" \
TIMEOUT_MINUTES="$TIMEOUT_MINUTES" \
bash "$ROOT_DIR/batch/eval/run_eval_arm.sh" apdv1_portable_bundle

latest_results_dir="$(ls -1dt "$ROOT_DIR"/batch/eval/results/eval-apdv1_portable_bundle-* | head -n 1)"
raw_results="$latest_results_dir/apdv1_portable_bundle_raw_results.jsonl"

echo "Summarizing cost results"
python3 "$ROOT_DIR/batch/eval/scripts/summarize_portable_cost.py" "$raw_results" "$latest_results_dir"

echo "Raw results: $raw_results"
echo "Summary: $latest_results_dir/portable_cost_summary.md"
