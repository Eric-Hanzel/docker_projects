#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
RAW_RESULTS_FILE="${1:-}"
CODEX_BIN="${CODEX_BIN:-codex}"
TIMEOUT_MINUTES="${JUDGE_TIMEOUT_MINUTES:-20}"
TIMEOUT_SECONDS="${JUDGE_TIMEOUT_SECONDS:-$((TIMEOUT_MINUTES * 60))}"

if [ -z "$RAW_RESULTS_FILE" ] || [ ! -f "$RAW_RESULTS_FILE" ]; then
  echo "Usage: $0 batch/eval/results/<run_id>/<arm>_raw_results.jsonl" >&2
  exit 2
fi

RAW_RESULTS_FILE="$(realpath "$RAW_RESULTS_FILE")"
RESULTS_DIR="$(dirname "$RAW_RESULTS_FILE")"
BASE_NAME="$(basename "$RAW_RESULTS_FILE" .jsonl)"
JUDGE_RUN_ID="judge-$(date +%Y%m%d_%H%M%S)-$$"
JUDGE_DIR="$RESULTS_DIR/$JUDGE_RUN_ID"
JUDGED_FILE="$RESULTS_DIR/${BASE_NAME}_judged.jsonl"
SUMMARY_FILE="$RESULTS_DIR/${BASE_NAME}_judged_summary.json"
PROMPT_TEMPLATE="$ROOT_DIR/batch/eval/prompts/local_run_judge_prompt.md"

mkdir -p "$JUDGE_DIR"
: > "$JUDGED_FILE"

idx=0
while IFS= read -r row; do
  [ -n "$row" ] || continue
  idx=$((idx + 1))
  task_id="$(python3 - "$row" "$idx" <<'PY'
import json, sys
print(json.loads(sys.argv[1]).get("task_id") or f"task-{int(sys.argv[2]):03d}")
PY
)"
  task_dir="$JUDGE_DIR/$task_id"
  mkdir -p "$task_dir"
  raw_json="$task_dir/raw_result.json"
  context_file="$task_dir/judge_context.md"
  prompt_file="$task_dir/judge_prompt.md"
  log_file="$task_dir/codex.log"
  last_msg_file="$task_dir/last_message.txt"
  judged_json="$task_dir/judged.json"

  printf '%s\n' "$row" | python3 -m json.tool > "$raw_json"
  python3 "$ROOT_DIR/batch/eval/scripts/build_judge_context.py" "$raw_json" --root "$ROOT_DIR" > "$context_file"
  {
    cat "$PROMPT_TEMPLATE"
    printf '\n\n# Evidence To Judge\n\n'
    cat "$context_file"
  } > "$prompt_file"

  set +e
  timeout -k 10s "${TIMEOUT_SECONDS}s" \
    "$CODEX_BIN" exec \
    --cd "$ROOT_DIR" \
    --dangerously-bypass-approvals-and-sandbox \
    --skip-git-repo-check \
    --output-last-message "$last_msg_file" \
    "$(cat "$prompt_file")" > "$log_file" 2>&1 < /dev/null
  rc=$?
  set -e

  if [ "$rc" -eq 0 ] && python3 "$ROOT_DIR/batch/eval/scripts/extract_judge_json.py" "$last_msg_file" > "$judged_json"; then
    python3 - <<PY "$raw_json" "$judged_json" "$JUDGED_FILE" "$rc"
import json, sys
raw = json.load(open(sys.argv[1], encoding="utf-8"))
judge = json.load(open(sys.argv[2], encoding="utf-8"))
out = sys.argv[3]
merged = dict(raw)
for key, value in judge.items():
    merged[key] = value
merged["judge_exit_code"] = int(sys.argv[4])
merged["judge_error"] = None
with open(out, "a", encoding="utf-8") as f:
    f.write(json.dumps(merged, ensure_ascii=False, separators=(",", ":")) + "\\n")
PY
  else
    python3 - <<PY "$raw_json" "$JUDGED_FILE" "$rc" "$log_file" "$last_msg_file"
import json, sys
raw = json.load(open(sys.argv[1], encoding="utf-8"))
raw.update({
    "runtime_success": False,
    "conditional_success": False,
    "failure_primary_label": "runner_or_tool_interrupt",
    "failure_secondary_labels": raw.get("failure_secondary_labels") or [],
    "confidence": "low",
    "selected_deploy_target_reasonable": None,
    "host_accessible_entrypoint_verified": None,
    "baseline_function_verified": None,
    "evidence_summary": [],
    "missing_or_weak_evidence": ["judge did not produce parseable JSON"],
    "judge_exit_code": int(sys.argv[3]),
    "judge_error": f"See {sys.argv[4]} and {sys.argv[5]}",
})
with open(sys.argv[2], "a", encoding="utf-8") as f:
    f.write(json.dumps(raw, ensure_ascii=False, separators=(",", ":")) + "\\n")
PY
  fi
done < "$RAW_RESULTS_FILE"

python3 "$ROOT_DIR/batch/eval/scripts/summarize_judged_results.py" "$JUDGED_FILE" "$SUMMARY_FILE" >/dev/null

echo "Judged results: $JUDGED_FILE"
echo "Judged summary: $SUMMARY_FILE"
echo "Judge artifacts: $JUDGE_DIR"
