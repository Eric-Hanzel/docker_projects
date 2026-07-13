#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
ARM="${1:-}"
TIMEOUT_MINUTES="${TIMEOUT_MINUTES:-60}"
TIMEOUT_SECONDS="${TIMEOUT_SECONDS:-$((TIMEOUT_MINUTES * 60))}"
CODEX_BIN="${CODEX_BIN:-codex}"
TASK_LIMIT="${TASK_LIMIT:-0}"

case "$ARM" in
  apdv1_local_run)
    TARGET_FILE="$ROOT_DIR/batch/eval/targets/apdv1_local_run_targets.jsonl"
    PROMPT_TEMPLATE="$ROOT_DIR/batch/eval/prompts/apdv1_local_run_prompt.md"
    CODEX_CWD="$ROOT_DIR"
    ;;
  apdv1_portable_bundle)
    TARGET_FILE="$ROOT_DIR/batch/eval/datasets/apdv1_portable_cost_balanced_6.jsonl"
    PROMPT_TEMPLATE="$ROOT_DIR/batch/eval/prompts/apdv1_portable_bundle_prompt.md"
    CODEX_CWD="$ROOT_DIR"
    ;;
  bare_codex)
    TARGET_FILE="$ROOT_DIR/batch/eval/targets/bare_codex_targets.jsonl"
    PROMPT_TEMPLATE="$ROOT_DIR/batch/eval/prompts/bare_codex_local_run_prompt.md"
    CODEX_CWD=""
    ;;
  *)
    echo "Usage: $0 apdv1_local_run|apdv1_portable_bundle|bare_codex" >&2
    exit 2
    ;;
esac

if [ -n "${EVAL_TARGET_FILE:-}" ]; then
  TARGET_FILE="$EVAL_TARGET_FILE"
fi
if [ -n "${EVAL_PROMPT_TEMPLATE:-}" ]; then
  PROMPT_TEMPLATE="$EVAL_PROMPT_TEMPLATE"
fi

RUN_ID="eval-${ARM}-$(date +%Y%m%d_%H%M%S)-$$"
RUN_DIR="$ROOT_DIR/batch/eval/runs/$RUN_ID"
RESULTS_DIR="$ROOT_DIR/batch/eval/results/$RUN_ID"
RAW_RESULTS_FILE="$RESULTS_DIR/${ARM}_raw_results.jsonl"
SUMMARY_FILE="$RESULTS_DIR/${ARM}_summary.json"
LOCK_FILE="$ROOT_DIR/.codex/state/eval_${ARM}.lock"
STATE_FILE="$ROOT_DIR/.codex/state/task_state.json"
HISTORY_FILE="$ROOT_DIR/.codex/state/task_history.jsonl"
STATE_ARCHIVE_DIR="$ROOT_DIR/.codex/state/archive"

CURRENT_CHILD_PID=""
CURRENT_OBSERVE_PID=""
CURRENT_TASK_MARKER=""
CURRENT_DOCKER_BEFORE=""
CURRENT_DOCKER_CLEANUP_REPORT=""
CURRENT_COMPOSE_PROJECT=""

stop_background_pid() {
  local pid="${1:-}"
  [ -n "$pid" ] || return 0
  kill -TERM "$pid" >/dev/null 2>&1 || true
  sleep 1
  kill -KILL "$pid" >/dev/null 2>&1 || true
}

cleanup_observer() {
  stop_background_pid "$CURRENT_OBSERVE_PID"
  CURRENT_OBSERVE_PID=""
}

wait_observer() {
  local pid="${CURRENT_OBSERVE_PID:-}"
  [ -n "$pid" ] || return 0
  wait "$pid" >/dev/null 2>&1 || true
  CURRENT_OBSERVE_PID=""
}

is_descendant_of() {
  local pid="$1"
  local ancestor="$2"
  local ppid=""
  while true; do
    [ "$pid" = "$ancestor" ] && return 0
    [ "$pid" -le 1 ] && return 1
    [ -r "/proc/$pid/status" ] || return 1
    ppid="$(awk '/^PPid:/ {print $2}' "/proc/$pid/status" 2>/dev/null || true)"
    [ -n "$ppid" ] || return 1
    [ "$ppid" = "$pid" ] && return 1
    pid="$ppid"
  done
}

cleanup_task_processes() {
  local marker="$1"
  local ancestor_pid="${2:-$$}"
  local -a pids=()
  local -a remain=()
  local p="" line="" cmd=""
  [ -n "$marker" ] || return 0
  while IFS= read -r line; do
    [ -n "$line" ] || continue
    p="${line%% *}"
    cmd="${line#* }"
    [[ "$cmd" == *"$marker"* ]] || continue
    [[ "$p" =~ ^[0-9]+$ ]] || continue
    [ "$p" = "$$" ] && continue
    [ "$p" = "$PPID" ] && continue
    if is_descendant_of "$p" "$ancestor_pid"; then
      pids+=("$p")
    fi
  done < <(ps -eo pid=,args= || true)
  [ "${#pids[@]}" -gt 0 ] || return 0
  kill -TERM "${pids[@]}" 2>/dev/null || true
  sleep 2
  for p in "${pids[@]}"; do
    if ps -p "$p" >/dev/null 2>&1; then
      remain+=("$p")
    fi
  done
  if [ "${#remain[@]}" -gt 0 ]; then
    kill -KILL "${remain[@]}" 2>/dev/null || true
  fi
}

snapshot_docker() {
  local out_dir="$1"
  mkdir -p "$out_dir"
  if ! command -v docker >/dev/null 2>&1 || ! docker info >/dev/null 2>&1; then
    : > "$out_dir/containers.txt"
    : > "$out_dir/networks.txt"
    : > "$out_dir/volumes.txt"
    return 0
  fi
  docker ps -aq | sort > "$out_dir/containers.txt" || true
  docker network ls -q | sort > "$out_dir/networks.txt" || true
  docker volume ls -q | sort > "$out_dir/volumes.txt" || true
}

cleanup_labelled_docker() {
  local project="$1"
  local label=""
  local filter=""
  local -a ids=()
  command -v docker >/dev/null 2>&1 || return 0
  docker info >/dev/null 2>&1 || return 0
  for label in "com.docker.compose.project=${project}" "codex.apdv1.cleanup_project=${project}"; do
    filter="label=${label}"
    mapfile -t ids < <(docker ps -aq --filter "$filter" || true)
    [ "${#ids[@]}" -eq 0 ] || docker rm -f "${ids[@]}" >/dev/null 2>&1 || true
    mapfile -t ids < <(docker network ls -q --filter "$filter" || true)
    [ "${#ids[@]}" -eq 0 ] || docker network rm "${ids[@]}" >/dev/null 2>&1 || true
    mapfile -t ids < <(docker volume ls -q --filter "$filter" || true)
    [ "${#ids[@]}" -eq 0 ] || docker volume rm -f "${ids[@]}" >/dev/null 2>&1 || true
  done
}

cleanup_snapshot_diff() {
  local before_dir="$1"
  local report_file="$2"
  local after_dir
  after_dir="$(mktemp -d)"
  snapshot_docker "$after_dir"
  {
    printf '{'
    printf '"containers":['
    comm -13 "$before_dir/containers.txt" "$after_dir/containers.txt" | python3 -c 'import json,sys; print(",".join(json.dumps(x.strip()) for x in sys.stdin if x.strip()))'
    printf '],"networks":['
    comm -13 "$before_dir/networks.txt" "$after_dir/networks.txt" | python3 -c 'import json,sys; print(",".join(json.dumps(x.strip()) for x in sys.stdin if x.strip()))'
    printf '],"volumes":['
    comm -13 "$before_dir/volumes.txt" "$after_dir/volumes.txt" | python3 -c 'import json,sys; print(",".join(json.dumps(x.strip()) for x in sys.stdin if x.strip()))'
    printf ']}'
    printf '\n'
  } > "$report_file"
  if command -v docker >/dev/null 2>&1 && docker info >/dev/null 2>&1; then
    mapfile -t new_containers < <(comm -13 "$before_dir/containers.txt" "$after_dir/containers.txt" || true)
    [ "${#new_containers[@]}" -eq 0 ] || docker rm -f "${new_containers[@]}" >/dev/null 2>&1 || true
    mapfile -t new_networks < <(comm -13 "$before_dir/networks.txt" "$after_dir/networks.txt" || true)
    [ "${#new_networks[@]}" -eq 0 ] || docker network rm "${new_networks[@]}" >/dev/null 2>&1 || true
    mapfile -t new_volumes < <(comm -13 "$before_dir/volumes.txt" "$after_dir/volumes.txt" || true)
    [ "${#new_volumes[@]}" -eq 0 ] || docker volume rm -f "${new_volumes[@]}" >/dev/null 2>&1 || true
  fi
  rm -rf "$after_dir"
}

read_apdv1_cleanup_projects() {
  python3 - <<PY "$STATE_FILE"
import json, re, sys
try:
    d = json.load(open(sys.argv[1], encoding="utf-8"))
except Exception:
    raise SystemExit(0)
keys = ["cleanup_project_names", "cleanup_compose_projects", "compose_project_names", "compose_project_name", "compose_project", "project_name", "resolved_project_name"]
seen = []
for key in keys:
    value = d.get(key)
    if isinstance(value, list):
        parts = value
    elif isinstance(value, str):
        parts = re.split(r"[,\\s]+", value)
    else:
        parts = []
    for part in parts:
        name = str(part).strip()
        if name and name not in seen and re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,127}", name):
            seen.append(name)
print("\\n".join(seen))
PY
}

read_current_status() {
  python3 - <<PY "$STATE_FILE"
import json, sys
try:
    print(json.load(open(sys.argv[1], encoding="utf-8")).get("status", ""))
except Exception:
    print("")
PY
}

is_apdv1_arm() {
  [ "$ARM" = "apdv1_local_run" ] || [ "$ARM" = "apdv1_portable_bundle" ]
}

update_apdv1_runner_terminal() {
  local status="$1"
  local message="$2"
  python3 "$ROOT_DIR/.codex/scripts/update_state.py" \
    --state-file "$STATE_FILE" \
    --history-file "$HISTORY_FILE" \
    --status "$status" \
    --batch-id "$RUN_ID" \
    --message "$message" \
    --set "result=$status" \
    --append-history
}

write_bare_agents_preflight() {
  local work_dir="$1"
  local out_file="$2"
  python3 - <<'PY' "$work_dir" "$out_file"
import json
import os
import sys
from pathlib import Path

work_dir = Path(sys.argv[1]).resolve()
out_file = Path(sys.argv[2])
paths = []
cur = work_dir
while True:
    candidate = cur / "AGENTS.md"
    if candidate.exists():
        paths.append(str(candidate))
    if cur.parent == cur:
        break
    cur = cur.parent

report = {
    "work_dir": str(work_dir),
    "checked_ancestor_chain": True,
    "agents_md_paths": paths,
    "apdv1_agents_exposed": any(str(p).startswith("/home/eric/APDv1/") for p in paths),
    "clean_for_bare_codex": len(paths) == 0,
}
out_file.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
if paths:
    print(f"Bare Codex AGENTS.md exposure detected: {paths}", file=sys.stderr)
    raise SystemExit(3)
PY
}

archive_and_reset_state_files() {
  local stamp="$1"
  mkdir -p "$STATE_ARCHIVE_DIR"
  if [ -f "$STATE_FILE" ]; then
    if [ -s "$STATE_FILE" ]; then
      mv "$STATE_FILE" "$STATE_ARCHIVE_DIR/task_state.${stamp}.json"
    else
      rm -f "$STATE_FILE"
    fi
  fi
  if [ -f "$HISTORY_FILE" ]; then
    if [ -s "$HISTORY_FILE" ]; then
      mv "$HISTORY_FILE" "$STATE_ARCHIVE_DIR/task_history.${stamp}.jsonl"
    else
      rm -f "$HISTORY_FILE"
    fi
  fi
}

update_apdv1_state_starting() {
  local task_id="$1"
  local idx="$2"
  local total="$3"
  local url="$4"
  local record="$5"
  local log_file="$6"
  local last_msg_file="$7"
  local task_dir="$8"
  local trajectory_file="$9"
  local trace_file="${10}"
  local session_path_file="${11}"
  local agents_dir="${12}"
  local delivery_mode="local-run"
  local portable_final_required="false"
  local message="Dispatching eval local-run target to Codex"

  if [ "$ARM" = "apdv1_portable_bundle" ]; then
    delivery_mode="portable-deliverable"
    portable_final_required="true"
    message="Dispatching eval portable-bundle target to Codex"
  fi

  python3 "$ROOT_DIR/.codex/scripts/update_state.py" \
    --state-file "$STATE_FILE" \
    --history-file "$HISTORY_FILE" \
    --status STARTING \
    --batch-id "$RUN_ID" \
    --task-id "$task_id" \
    --target-index "$idx" \
    --target-total "$total" \
    --target-url "$url" \
    --target-json "$record" \
    --log-file "$log_file" \
    --last-message-file "$last_msg_file" \
    --pid "$$" \
    --message "$message" \
    --set "task_dir=$task_dir" \
    --set "trajectory_file=$trajectory_file" \
    --set "trace_file=$trace_file" \
    --set "session_path_file=$session_path_file" \
    --set "agents_dir=$agents_dir" \
    --set "delivery_mode=$delivery_mode" \
    --set "portable_final_required=$portable_final_required" \
    --set result= \
    --set exit_code= \
    --set session_id= \
    --set session_file= \
    --set session_path= \
    --set docker_cleanup= \
    --set project_name= \
    --set resolved_project_name= \
    --set cleanup_project_names= \
    --set cleanup_compose_projects= \
    --set compose_project_names= \
    --set compose_project_name= \
    --set compose_project= \
    --set primary_audit_gate_required= \
    --set primary_audit_attempts= \
    --set primary_audit_verdict= \
    --set primary_audit_result_file= \
    --set primary_audit_subagent_mode= \
    --set primary_audit_subagent_fallback_reason= \
    --set audit_gate_required= \
    --set audit_attempts= \
    --set audit_verdict= \
    --set audit_result_file= \
    --set portable_subagent_mode= \
    --set portable_subagent_fallback_reason= \
    --set conditional_reason= \
    --set blocking_requirement= \
    --set result_warning= \
    --unset started_at \
    --unset finished_at \
    --append-history
}

update_apdv1_state_idle() {
  python3 "$ROOT_DIR/.codex/scripts/update_state.py" \
    --state-file "$STATE_FILE" \
    --history-file "$HISTORY_FILE" \
    --status IDLE \
    --batch-id "$RUN_ID" \
    --target-total "$TOTAL" \
    --message "Eval arm completed" \
    --unset task_id \
    --unset target_index \
    --unset target_url \
    --unset target \
    --unset log_file \
    --unset last_message_file \
    --unset result \
    --unset exit_code \
    --unset session_id \
    --unset session_file \
    --unset session_path \
    --unset task_dir \
    --unset trajectory_file \
    --unset trace_file \
    --unset session_path_file \
    --unset agents_dir \
    --unset docker_cleanup \
    --unset project_name \
    --unset resolved_project_name \
    --unset cleanup_project_names \
    --unset cleanup_compose_projects \
    --unset compose_project_names \
    --unset compose_project_name \
    --unset compose_project \
    --unset primary_audit_gate_required \
    --unset primary_audit_attempts \
    --unset primary_audit_verdict \
    --unset primary_audit_result_file \
    --unset primary_audit_subagent_mode \
    --unset primary_audit_subagent_fallback_reason \
    --unset audit_gate_required \
    --unset audit_attempts \
    --unset audit_verdict \
    --unset audit_result_file \
    --unset portable_subagent_mode \
    --unset portable_subagent_fallback_reason \
    --unset delivery_mode \
    --unset portable_final_required \
    --unset conditional_reason \
    --unset blocking_requirement \
    --unset result_warning \
    --unset started_at \
    --unset finished_at \
    --append-history
}

on_exit() {
  local rc=$?
  if [ -n "$CURRENT_CHILD_PID" ]; then
    kill -TERM "$CURRENT_CHILD_PID" >/dev/null 2>&1 || true
    sleep 1
    kill -KILL "$CURRENT_CHILD_PID" >/dev/null 2>&1 || true
  fi
  cleanup_observer
  [ -z "$CURRENT_TASK_MARKER" ] || cleanup_task_processes "$CURRENT_TASK_MARKER" "$$"
  if [ -n "$CURRENT_COMPOSE_PROJECT" ]; then
    cleanup_labelled_docker "$CURRENT_COMPOSE_PROJECT" || true
  fi
  if is_apdv1_arm; then
    mapfile -t cleanup_projects < <(read_apdv1_cleanup_projects || true)
    for p in "${cleanup_projects[@]}"; do
      cleanup_labelled_docker "$p" || true
    done
  fi
  if [ -n "$CURRENT_DOCKER_BEFORE" ] && [ -d "$CURRENT_DOCKER_BEFORE" ] && [ -n "$CURRENT_DOCKER_CLEANUP_REPORT" ]; then
    cleanup_snapshot_diff "$CURRENT_DOCKER_BEFORE" "$CURRENT_DOCKER_CLEANUP_REPORT" || true
  fi
  exit "$rc"
}
trap on_exit EXIT
trap 'exit 130' INT
trap 'exit 143' TERM

mkdir -p "$RUN_DIR" "$RESULTS_DIR" "$ROOT_DIR/.codex/state"
: > "$RAW_RESULTS_FILE"

exec 9>"$LOCK_FILE"
if ! flock -n 9; then
  echo "Another eval run for $ARM is active (lock: $LOCK_FILE)" >&2
  exit 1
fi

if [ ! -f "$TARGET_FILE" ]; then
  echo "Target file not found: $TARGET_FILE" >&2
  exit 1
fi
if [ ! -f "$PROMPT_TEMPLATE" ]; then
  echo "Prompt template not found: $PROMPT_TEMPLATE" >&2
  exit 1
fi

if is_apdv1_arm; then
  existing_running_check="$(python3 - <<PY "$STATE_FILE"
import json, sys
try:
    d = json.load(open(sys.argv[1], encoding="utf-8"))
except Exception:
    print("")
    raise SystemExit(0)
if d.get("status") == "RUNNING":
    print(f"RUNNING|{d.get('batch_id','')}|{d.get('task_id','')}|{d.get('pid','')}")
else:
    print("")
PY
)"
  if [ -n "$existing_running_check" ]; then
    IFS='|' read -r _ running_batch running_task running_pid <<< "$existing_running_check"
    echo "Refusing to start: existing active APDv1 task state detected (batch_id=${running_batch:-unknown}, task_id=${running_task:-unknown}, pid=${running_pid:-unknown})." >&2
    exit 1
  fi
  archive_and_reset_state_files "$RUN_ID"
  python3 "$ROOT_DIR/.codex/scripts/update_state.py" \
    --state-file "$STATE_FILE" \
    --history-file "$HISTORY_FILE" \
    --status INITIALIZING \
    --batch-id "$RUN_ID" \
    --target-total 0 \
    --pid "$$" \
    --message "APDv1 eval initializing" \
    --append-history
fi

mapfile -t TARGETS < <(python3 - "$TARGET_FILE" "$TASK_LIMIT" <<'PY'
import json, sys
path = sys.argv[1]
limit = int(sys.argv[2])
count = 0
with open(path, encoding="utf-8") as f:
    for n, line in enumerate(f, 1):
        s = line.strip()
        if not s or s.startswith("#"):
            continue
        obj = json.loads(s)
        if not isinstance(obj.get("url"), str) or not obj["url"].strip():
            raise SystemExit(f"Invalid target line {n}: missing url")
        print(json.dumps(obj, ensure_ascii=False, separators=(",", ":")))
        count += 1
        if limit > 0 and count >= limit:
            break
PY
)

TOTAL="${#TARGETS[@]}"
if [ "$TOTAL" -eq 0 ]; then
  echo "No targets to run in $TARGET_FILE" >&2
  exit 1
fi

for i in "${!TARGETS[@]}"; do
  idx=$((i + 1))
  record="${TARGETS[$i]}"
  url="$(python3 - <<PY "$record"
import json, sys
print(json.loads(sys.argv[1]).get("url", ""))
PY
)"
  task_id="task-$(printf '%03d' "$idx")"
  task_dir="$RUN_DIR/$task_id"
  mkdir -p "$task_dir/agents"
  prompt_file="$task_dir/prompt.txt"
  log_file="$task_dir/codex.log"
  last_msg_file="$task_dir/last_message.txt"
  session_file="$task_dir/session"
  session_path_file="$task_dir/session_path"
  trajectory_file="$task_dir/trajectory.jsonl"
  trace_file="$task_dir/trace.txt"
  trace_offset_file="$task_dir/trace.offset"
  trace_pid_file="$task_dir/trace.pid"
  agents_dir="$task_dir/agents"
  docker_before="$task_dir/docker_before"
  docker_cleanup_report="$task_dir/docker_cleanup_report.json"
  agents_preflight_file="$task_dir/agents_preflight.json"
  token_file="$task_dir/token_usage.json"
  result_file="$task_dir/result.json"
  work_dir="$CODEX_CWD"
  compose_project="eval-${ARM}-${RUN_ID}-${task_id}"
  compose_project="${compose_project//_/-}"
  compose_project="${compose_project:0:120}"

  if [ "$ARM" = "bare_codex" ]; then
    work_dir="${BARE_WORK_ROOT:-/tmp/apdv1-bare-codex-eval}/$RUN_ID/$task_id"
    mkdir -p "$work_dir"
    write_bare_agents_preflight "$work_dir" "$agents_preflight_file"
  fi
  printf '%s\n' "$work_dir" > "$task_dir/work_dir"

  {
    cat "$PROMPT_TEMPLATE"
    printf '\n## Target\n\n```json\n%s\n```\n' "$record"
  } > "$prompt_file"

  : > "$log_file"
  : > "$last_msg_file"
  : > "$session_file"
  : > "$session_path_file"
  : > "$trajectory_file"
  : > "$trace_file"
  : > "$trace_offset_file"
  : > "$trace_pid_file"
  printf '%s\n' "$record" > "$task_dir/target.json"
  snapshot_docker "$docker_before"
  CURRENT_DOCKER_BEFORE="$docker_before"
  CURRENT_DOCKER_CLEANUP_REPORT="$docker_cleanup_report"
  CURRENT_COMPOSE_PROJECT="$compose_project"
  started_at="$(date --iso-8601=seconds)"
  start_epoch="$(date +%s)"
  CURRENT_TASK_MARKER="$last_msg_file"

  if is_apdv1_arm; then
    update_apdv1_state_starting "$task_id" "$idx" "$TOTAL" "$url" "$record" "$log_file" "$last_msg_file" "$task_dir" "$trajectory_file" "$trace_file" "$session_path_file" "$agents_dir"
  fi

  set +e
  (
    exec 9>&-
    BATCH_RUN_ID="$RUN_ID" \
    BATCH_TASK_ID="$task_id" \
    EVAL_RUN_ID="$RUN_ID" \
    EVAL_ARM="$ARM" \
    EVAL_TASK_ID="$task_id" \
    COMPOSE_PROJECT_NAME="$compose_project" \
    CODEX_APDV1_CLEANUP_PROJECT="$compose_project" \
    timeout -k 10s "${TIMEOUT_SECONDS}s" \
      "$CODEX_BIN" exec \
      --cd "$work_dir" \
      --dangerously-bypass-approvals-and-sandbox \
      --skip-git-repo-check \
      --output-last-message "$last_msg_file" \
      "$(cat "$prompt_file")"
  ) > "$log_file" 2>&1 &
  CURRENT_CHILD_PID="$!"
  python3 "$ROOT_DIR/.codex/scripts/observe_rollout.py" \
    --log-file "$log_file" \
    --session-file "$session_file" \
    --session-path-file "$session_path_file" \
    --trajectory-file "$trajectory_file" \
    --trace-file "$trace_file" \
    --trace-offset-file "$trace_offset_file" \
    --trace-pid-file "$trace_pid_file" \
    --child-pid "$CURRENT_CHILD_PID" \
    --agents-dir "$agents_dir" &
  CURRENT_OBSERVE_PID="$!"
  wait "$CURRENT_CHILD_PID"
  rc=$?
  CURRENT_CHILD_PID=""
  set -e

  cleanup_task_processes "$last_msg_file" "$$"
  wait_observer

  if is_apdv1_arm; then
    mapfile -t cleanup_projects < <(read_apdv1_cleanup_projects || true)
    for p in "${cleanup_projects[@]}"; do
      cleanup_labelled_docker "$p"
    done
  fi
  cleanup_labelled_docker "$compose_project"
  cleanup_snapshot_diff "$docker_before" "$docker_cleanup_report"

  ended_at="$(date --iso-8601=seconds)"
  end_epoch="$(date +%s)"
  wall_time=$((end_epoch - start_epoch))

  status=""
  if is_apdv1_arm; then
    status="$(read_current_status)"
  fi
  if [[ ! "$status" =~ ^(COMPLETED_SUCCESS|COMPLETED_CONDITIONAL_SUCCESS|COMPLETED_FAILED)$ ]]; then
    if [ "$rc" -eq 124 ] || [ "$rc" -eq 137 ]; then
      status="TIMED_OUT"
    elif [ "$rc" -eq 0 ]; then
      status="RUNNER_COMPLETED"
    else
      status="ABORTED"
    fi
  fi
  if is_apdv1_arm && [[ "$status" =~ ^(TIMED_OUT|ABORTED)$ ]]; then
    update_apdv1_runner_terminal "$status" "Eval runner recorded $status because agent terminal state was missing"
  fi

  token_json="$(python3 "$ROOT_DIR/batch/eval/scripts/extract_token_usage.py" "$trajectory_file" "$agents_dir" || printf '{}')"
  printf '%s\n' "$token_json" > "$token_file"

  python3 - <<PY "$result_file" "$RAW_RESULTS_FILE" "$RUN_ID" "$ARM" "$task_id" "$idx" "$url" "$status" "$rc" "$started_at" "$ended_at" "$wall_time" "$task_dir" "$log_file" "$last_msg_file" "$trajectory_file" "$trace_file" "$agents_dir" "$docker_cleanup_report" "$token_json"
import json, sys
out, raw = sys.argv[1], sys.argv[2]
obj = {
    "run_id": sys.argv[3],
    "arm": sys.argv[4],
    "task_id": sys.argv[5],
    "target_index": int(sys.argv[6]),
    "url": sys.argv[7],
    "runtime_success": None,
    "conditional_success": None,
    "terminal_status": sys.argv[8],
    "failure_primary_label": None,
    "failure_secondary_labels": [],
    "exit_code": int(sys.argv[9]),
    "started_at": sys.argv[10],
    "ended_at": sys.argv[11],
    "wall_time_seconds": int(sys.argv[12]),
    "external_wait_seconds": None,
    "external_wait_evidence": [],
    "network_adjusted_seconds": None,
    "blocked_wait_seconds": None,
    "blocked_wait_evidence": [],
    "cache_condition": "unknown",
    "task_dir": sys.argv[13],
    "evidence_paths": [sys.argv[14], sys.argv[15], sys.argv[16], sys.argv[17], sys.argv[18], sys.argv[19]],
}
try:
    tok = json.loads(sys.argv[20])
except Exception:
    tok = {}
for key in ["input_tokens", "cached_input_tokens", "output_tokens", "reasoning_output_tokens", "total_tokens", "trajectory_count"]:
    obj[key] = tok.get(key)
with open(out, "w", encoding="utf-8") as f:
    json.dump(obj, f, ensure_ascii=False, indent=2)
    f.write("\\n")
with open(raw, "a", encoding="utf-8") as f:
    f.write(json.dumps(obj, ensure_ascii=False, separators=(",", ":")) + "\\n")
PY

  CURRENT_TASK_MARKER=""
  CURRENT_DOCKER_BEFORE=""
  CURRENT_DOCKER_CLEANUP_REPORT=""
  CURRENT_COMPOSE_PROJECT=""
done

python3 - <<PY "$SUMMARY_FILE" "$RAW_RESULTS_FILE" "$RUN_ID" "$ARM" "$TOTAL"
import json, sys, datetime
rows = []
with open(sys.argv[2], encoding="utf-8") as f:
    for line in f:
        if line.strip():
            rows.append(json.loads(line))
summary = {
    "run_id": sys.argv[3],
    "arm": sys.argv[4],
    "total": int(sys.argv[5]),
    "terminal_status_counts": {},
    "raw_results_file": sys.argv[2],
    "finished_at": datetime.datetime.now(datetime.timezone.utc).astimezone().replace(microsecond=0).isoformat(),
}
for row in rows:
    status = row.get("terminal_status") or ""
    summary["terminal_status_counts"][status] = summary["terminal_status_counts"].get(status, 0) + 1
with open(sys.argv[1], "w", encoding="utf-8") as f:
    json.dump(summary, f, ensure_ascii=False, indent=2)
    f.write("\\n")
print(json.dumps(summary, ensure_ascii=False))
PY

if is_apdv1_arm; then
  update_apdv1_state_idle
fi

echo "Eval arm completed. Run dir: $RUN_DIR"
echo "Results: $RAW_RESULTS_FILE"
