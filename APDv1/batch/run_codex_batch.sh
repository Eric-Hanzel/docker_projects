#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
TARGET_FILE="${1:-$ROOT_DIR/batch/target.txt}"
TIMEOUT_MINUTES="${TIMEOUT_MINUTES:-60}"
TIMEOUT_SECONDS="${TIMEOUT_SECONDS:-$((TIMEOUT_MINUTES * 60))}"
CODEX_BIN="${CODEX_BIN:-codex}"

STATE_DIR="$ROOT_DIR/.codex/state"
STATE_FILE="$STATE_DIR/task_state.json"
HISTORY_FILE="$STATE_DIR/task_history.jsonl"
STATE_ARCHIVE_DIR="$STATE_DIR/archive"
LOCK_FILE="$STATE_DIR/batch.lock"
RUN_ID="batch-$(date +%Y%m%d_%H%M%S)-$$"
RUN_DIR="$ROOT_DIR/batch/runs/$RUN_ID"
RESULTS_DIR="$ROOT_DIR/batch/results"
RUN_RESULTS_DIR="$RESULTS_DIR/$RUN_ID"
RUN_SUCCESS_FILE="$RUN_RESULTS_DIR/success.txt"
RUN_CONDITIONAL_SUCCESS_FILE="$RUN_RESULTS_DIR/conditional_success.txt"
RUN_FAILURE_FILE="$RUN_RESULTS_DIR/failure.txt"
LATEST_SUCCESS_FILE="$ROOT_DIR/batch/success.txt"
LATEST_CONDITIONAL_SUCCESS_FILE="$ROOT_DIR/batch/conditional_success.txt"
LATEST_FAILURE_FILE="$ROOT_DIR/batch/failure.txt"
TOTAL=0

BATCH_INITIALIZED=0
BATCH_FINALIZED=0
TRAP_REASON=""

CURRENT_TASK_ID=""
CURRENT_TASK_DIR=""
CURRENT_TARGET_INDEX=""
CURRENT_TARGET_URL=""
CURRENT_TARGET_JSON=""
CURRENT_LOG_FILE=""
CURRENT_LAST_MESSAGE_FILE=""
CURRENT_SESSION_FILE=""
CURRENT_SESSION_PATH_FILE=""
CURRENT_TRAJECTORY_FILE=""
CURRENT_TRACE_FILE=""
CURRENT_TRACE_OFFSET_FILE=""
CURRENT_TRACE_PID_FILE=""
CURRENT_AGENTS_DIR=""
CURRENT_CHILD_PID=""
CURRENT_OBSERVE_PID=""

stop_background_pid() {
  local pid="${1:-}"
  [ -n "$pid" ] || return 0
  kill -TERM "$pid" >/dev/null 2>&1 || true
  sleep 1
  kill -KILL "$pid" >/dev/null 2>&1 || true
}

cleanup_current_observability() {
  stop_background_pid "$CURRENT_OBSERVE_PID"
  CURRENT_OBSERVE_PID=""
}

wait_current_observability() {
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
  local p=""
  local line=""
  local cmd=""

  [ -n "$marker" ] || return 0

  # Use literal substring matching against full command lines to avoid regex surprises from pgrep -f.
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

read_cleanup_projects() {
  python3 - <<PY "$STATE_FILE"
import json, re, sys
p = sys.argv[1]
try:
    d = json.load(open(p, encoding="utf-8"))
except Exception:
    raise SystemExit(0)

keys = [
    "cleanup_project_names",
    "cleanup_compose_projects",
    "compose_project_names",
    "compose_project_name",
    "compose_project",
    "project_name",
    "resolved_project_name",
]
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
        if not name or name in seen:
            continue
        if re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,127}", name):
            seen.append(name)

print("\\n".join(seen))
PY
}

cleanup_project_docker_resources() {
  local -a projects=("$@")
  local -a labels=()
  local -a ids=()
  local project=""
  local filter=""

  command -v docker >/dev/null 2>&1 || return 0
  docker info >/dev/null 2>&1 || return 0

  if [ "${#projects[@]}" -eq 0 ]; then
    return 2
  fi

  for project in "${projects[@]}"; do
    labels=(
      "com.docker.compose.project=${project}"
      "codex.apdv1.cleanup_project=${project}"
    )

    for filter in "${labels[@]}"; do
      filter="label=${filter}"

      mapfile -t ids < <(docker ps -aq --filter "$filter" || true)
      if [ "${#ids[@]}" -gt 0 ]; then
        docker rm -f "${ids[@]}" >/dev/null 2>&1 || true
      fi

      mapfile -t ids < <(docker network ls -q --filter "$filter" || true)
      if [ "${#ids[@]}" -gt 0 ]; then
        docker network rm "${ids[@]}" >/dev/null 2>&1 || true
      fi

      mapfile -t ids < <(docker volume ls -q --filter "$filter" || true)
      if [ "${#ids[@]}" -gt 0 ]; then
        docker volume rm -f "${ids[@]}" >/dev/null 2>&1 || true
      fi

      mapfile -t ids < <(docker image ls -q --filter "$filter" || true)
      if [ "${#ids[@]}" -gt 0 ]; then
        docker image rm -f "${ids[@]}" >/dev/null 2>&1 || true
      fi
    done
  done
}

cleanup_current_task_docker_resources() {
  local -a projects=()

  if ! command -v docker >/dev/null 2>&1; then
    printf 'skipped_project_scoped_cleanup:docker_unavailable\n'
    return 0
  fi
  if ! docker info >/dev/null 2>&1; then
    printf 'skipped_project_scoped_cleanup:docker_unavailable\n'
    return 0
  fi

  mapfile -t projects < <(read_cleanup_projects)
  if cleanup_project_docker_resources "${projects[@]}"; then
    if [ "${#projects[@]}" -gt 0 ]; then
      printf 'attempted_project_scoped_cleanup:%s\n' "$(IFS=,; printf '%s' "${projects[*]}")"
    else
      printf 'skipped_project_scoped_cleanup:no_project_names\n'
    fi
  else
    printf 'skipped_project_scoped_cleanup:no_project_names\n'
  fi
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

read_current_status() {
  python3 - <<PY "$STATE_FILE"
import json,sys
p=sys.argv[1]
try:
  print(json.load(open(p,encoding='utf-8')).get('status',''))
except Exception:
  print('')
PY
}

is_terminal_status() {
  case "$1" in
    COMPLETED_SUCCESS|COMPLETED_CONDITIONAL_SUCCESS|COMPLETED_FAILED|TIMED_OUT|ABORTED|IDLE) return 0 ;;
    *) return 1 ;;
  esac
}

handle_unexpected_exit() {
  local rc="$1"
  set +e

  [ "$BATCH_FINALIZED" -eq 1 ] && return 0
  [ "$BATCH_INITIALIZED" -eq 1 ] || return 0

  local current_status=""
  current_status="$(read_current_status)"

  if [ -n "$CURRENT_LAST_MESSAGE_FILE" ]; then
    cleanup_task_processes "$CURRENT_LAST_MESSAGE_FILE" "$$"
  fi
  if [ -n "$CURRENT_CHILD_PID" ]; then
    kill -TERM "$CURRENT_CHILD_PID" >/dev/null 2>&1 || true
    sleep 1
    kill -KILL "$CURRENT_CHILD_PID" >/dev/null 2>&1 || true
    CURRENT_CHILD_PID=""
  fi
  wait_current_observability
  cleanup_current_observability
  cleanup_current_task_docker_resources >/dev/null

  if is_terminal_status "$current_status"; then
    return 0
  fi

  local reason="${TRAP_REASON:-Batch exited unexpectedly (rc=$rc)}"
  local -a state_args=(
    --state-file "$STATE_FILE"
    --history-file "$HISTORY_FILE"
    --status ABORTED
    --batch-id "$RUN_ID"
    --target-total "$TOTAL"
    --result failed
    --exit-code "$rc"
    --message "$reason"
    --append-history
  )

  [ -n "$CURRENT_TASK_ID" ] && state_args+=(--task-id "$CURRENT_TASK_ID")
  [ -n "$CURRENT_TARGET_INDEX" ] && state_args+=(--target-index "$CURRENT_TARGET_INDEX")
  [ -n "$CURRENT_TARGET_URL" ] && state_args+=(--target-url "$CURRENT_TARGET_URL")
  [ -n "$CURRENT_TARGET_JSON" ] && state_args+=(--target-json "$CURRENT_TARGET_JSON")
  [ -n "$CURRENT_LOG_FILE" ] && state_args+=(--log-file "$CURRENT_LOG_FILE")
  [ -n "$CURRENT_LAST_MESSAGE_FILE" ] && state_args+=(--last-message-file "$CURRENT_LAST_MESSAGE_FILE")
  [ -n "$CURRENT_SESSION_FILE" ] && state_args+=(--set "session_file=$CURRENT_SESSION_FILE")
  [ -n "$CURRENT_SESSION_PATH_FILE" ] && state_args+=(--set "session_path_file=$CURRENT_SESSION_PATH_FILE")
  [ -n "$CURRENT_TRACE_FILE" ] && state_args+=(--set "trace_file=$CURRENT_TRACE_FILE")
  [ -n "$CURRENT_TRAJECTORY_FILE" ] && state_args+=(--set "trajectory_file=$CURRENT_TRAJECTORY_FILE")
  [ -n "$CURRENT_AGENTS_DIR" ] && state_args+=(--set "agents_dir=$CURRENT_AGENTS_DIR")

  python3 "$ROOT_DIR/.codex/scripts/update_state.py" "${state_args[@]}" || true
}

handle_signal() {
  local sig="$1"
  set +e
  TRAP_REASON="Batch interrupted by ${sig}"
  local current_status=""
  current_status="$(read_current_status)"

  if [ -n "$CURRENT_CHILD_PID" ]; then
    kill -TERM "$CURRENT_CHILD_PID" >/dev/null 2>&1 || true
    sleep 1
    kill -KILL "$CURRENT_CHILD_PID" >/dev/null 2>&1 || true
    CURRENT_CHILD_PID=""
  fi
  wait_current_observability
  cleanup_current_observability
  if [ -n "$CURRENT_LAST_MESSAGE_FILE" ]; then
    cleanup_task_processes "$CURRENT_LAST_MESSAGE_FILE" "$$"
  fi
  cleanup_current_task_docker_resources >/dev/null

  case "$sig" in
    INT) exit 130 ;;
    TERM) exit 143 ;;
    *) exit 1 ;;
  esac
}

on_exit() {
  local rc=$?
  handle_unexpected_exit "$rc"
}

trap on_exit EXIT
trap 'handle_signal INT' INT
trap 'handle_signal TERM' TERM

mkdir -p "$STATE_DIR" "$RUN_DIR" "$RESULTS_DIR" "$RUN_RESULTS_DIR"

exec 9>"$LOCK_FILE"
if ! flock -n 9; then
  echo "Another batch run is active (lock: $LOCK_FILE)" >&2
  exit 1
fi

if [ ! -f "$TARGET_FILE" ]; then
  echo "Target file not found: $TARGET_FILE" >&2
  exit 1
fi

existing_running_check="$(python3 - <<PY "$STATE_FILE"
import json,sys
p=sys.argv[1]
try:
  d=json.load(open(p,encoding='utf-8'))
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
  echo "Refusing to start: existing active task state detected (status=RUNNING, batch_id=${running_batch:-unknown}, task_id=${running_task:-unknown}, pid=${running_pid:-unknown})." >&2
  exit 1
fi

targets_tmp="$(mktemp)"
set +e
python3 - "$TARGET_FILE" > "$targets_tmp" <<'PY'
import json,sys
p=sys.argv[1]
with open(p,'r',encoding='utf-8') as f:
    for n,line in enumerate(f,1):
        s=line.strip()
        if not s or s.startswith('#'):
            continue
        obj=json.loads(s)
        url=obj.get('url')
        if not isinstance(url,str) or not url.strip():
            raise SystemExit(f"Invalid target line {n}: missing non-empty 'url'")
        print(json.dumps(obj,ensure_ascii=False,separators=(',',':')))
PY
parse_rc=$?
set -e
if [ "$parse_rc" -ne 0 ]; then
  rm -f "$targets_tmp"
  echo "Invalid target file: $TARGET_FILE" >&2
  exit "$parse_rc"
fi
mapfile -t TARGETS < "$targets_tmp"
rm -f "$targets_tmp"

TOTAL="${#TARGETS[@]}"
if [ "$TOTAL" -eq 0 ]; then
  echo "No valid targets in $TARGET_FILE" >&2
  exit 1
fi

archive_and_reset_state_files "$RUN_ID"

python3 "$ROOT_DIR/.codex/scripts/update_state.py" \
  --state-file "$STATE_FILE" \
  --history-file "$HISTORY_FILE" \
  --status INITIALIZING \
  --batch-id "$RUN_ID" \
  --target-total "$TOTAL" \
  --pid "$$" \
  --message "Batch initializing" \
  --set task_id= \
  --set target_index= \
  --set target_url= \
  --set log_file= \
  --set last_message_file= \
  --set session_id= \
  --set session_file= \
  --set session_path= \
  --set task_dir= \
  --set trajectory_file= \
  --set trace_file= \
  --set session_path_file= \
  --set agents_dir= \
  --set primary_audit_subagent_mode= \
  --set primary_audit_subagent_fallback_reason= \
  --set phase6_subagent_mode= \
  --set phase6_subagent_fallback_reason= \
  --set result= \
  --set exit_code= \
  --set target= \
  --set docker_cleanup= \
  --set project_name= \
  --set resolved_project_name= \
  --set cleanup_project_names= \
  --set cleanup_compose_projects= \
  --set compose_project_names= \
  --set compose_project_name= \
  --set compose_project= \
  --unset started_at \
  --unset finished_at \
  --unset session_id_file \
  --append-history

BATCH_INITIALIZED=1

{
  printf '# run_id=%s generated_at=%s\n' "$RUN_ID" "$(date --iso-8601=seconds)"
} > "$RUN_SUCCESS_FILE"
{
  printf '# run_id=%s generated_at=%s\n' "$RUN_ID" "$(date --iso-8601=seconds)"
} > "$RUN_CONDITIONAL_SUCCESS_FILE"
{
  printf '# run_id=%s generated_at=%s\n' "$RUN_ID" "$(date --iso-8601=seconds)"
} > "$RUN_FAILURE_FILE"

SUCCESS_COUNT=0
CONDITIONAL_SUCCESS_COUNT=0
FAIL_COUNT=0
TIMEOUT_COUNT=0
WARNING_COUNT=0
RC_MISMATCH_COUNT=0
CONDITIONAL_METADATA_MISSING_COUNT=0

for i in "${!TARGETS[@]}"; do
  idx=$((i + 1))
  record="${TARGETS[$i]}"
  url="$(python3 - <<PY "$record"
import json,sys
print(json.loads(sys.argv[1]).get('url',''))
PY
)"

  task_id="task-$(printf '%03d' "$idx")"
  task_dir="$RUN_DIR/$task_id"
  mkdir -p "$task_dir"
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
  mkdir -p "$agents_dir"

  CURRENT_TASK_ID="$task_id"
  CURRENT_TASK_DIR="$task_dir"
  CURRENT_TARGET_INDEX="$idx"
  CURRENT_TARGET_URL="$url"
  CURRENT_TARGET_JSON="$record"
  CURRENT_LOG_FILE="$log_file"
  CURRENT_LAST_MESSAGE_FILE="$last_msg_file"
  CURRENT_SESSION_FILE="$session_file"
  CURRENT_SESSION_PATH_FILE="$session_path_file"
  CURRENT_TRAJECTORY_FILE="$trajectory_file"
  CURRENT_TRACE_FILE="$trace_file"
  CURRENT_TRACE_OFFSET_FILE="$trace_offset_file"
  CURRENT_TRACE_PID_FILE="$trace_pid_file"
  CURRENT_AGENTS_DIR="$agents_dir"

  printf -v codex_prompt '%s\n' \
    "Target JSON:" \
    "$record" \
    "" \
    "Task requirements:" \
    "1. Process only this target end-to-end." \
    "2. Follow /home/eric/APDv1/AGENTS.md and applicable skills (including Phase 6 spawn delegation and audit requirements)." \
    "3. Update state at actual task start:" \
    "   TARGET_JSON=\$(cat <<'JSON'" \
    "$record" \
    "JSON" \
    ")" \
    "   python3 .codex/scripts/update_state.py --status RUNNING --batch-id \"$RUN_ID\" --task-id \"$task_id\" --target-index \"$idx\" --target-total \"$TOTAL\" --target-json \"\$TARGET_JSON\" --message \"Agent started\"" \
    "4. At final completion, agent must set one terminal state:" \
    "   COMPLETED_SUCCESS / COMPLETED_CONDITIONAL_SUCCESS / COMPLETED_FAILED" \
    "5. If terminal state is COMPLETED_CONDITIONAL_SUCCESS, also set: --set conditional_reason=<reason> --set blocking_requirement=<required external input/action>" \
    "6. As soon as project/compose names are known, set: --set project_name=<resolved_name> --set cleanup_project_names=<comma-separated compose project names>" \
    "7. Final terminal write must be the last task-state write, then exit with rc=0."

  python3 "$ROOT_DIR/.codex/scripts/update_state.py" \
    --state-file "$STATE_FILE" \
    --history-file "$HISTORY_FILE" \
    --status STARTING \
    --batch-id "$RUN_ID" \
    --task-id "$task_id" \
    --target-index "$idx" \
    --target-total "$TOTAL" \
    --target-url "$url" \
    --target-json "$record" \
    --log-file "$log_file" \
    --last-message-file "$last_msg_file" \
    --pid "$$" \
    --message "Dispatching target to Codex" \
    --set "task_dir=$task_dir" \
    --set "trajectory_file=$trajectory_file" \
    --set "trace_file=$trace_file" \
    --set "session_path_file=$session_path_file" \
    --set "agents_dir=$agents_dir" \
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
    --set primary_audit_gate_required=phase5_5 \
    --set primary_audit_attempts= \
    --set primary_audit_verdict= \
    --set primary_audit_result_file= \
    --set primary_audit_subagent_mode= \
    --set primary_audit_subagent_fallback_reason= \
    --set audit_gate_required=phase6 \
    --set audit_attempts= \
    --set audit_verdict= \
    --set audit_result_file= \
    --set phase6_subagent_mode= \
    --set phase6_subagent_fallback_reason= \
    --set conditional_reason= \
    --set blocking_requirement= \
    --set result_warning= \
    --unset started_at \
    --unset finished_at \
    --append-history

  printf '%s\n' "$codex_prompt" > "$prompt_file"
  : > "$session_file"
  : > "$session_path_file"
  : > "$trajectory_file"
  : > "$trace_file"
  : > "$trace_offset_file"
  : > "$trace_pid_file"

  set +e
  (
    # Prevent lock fd inheritance to child process tree.
    exec 9>&-
    BATCH_RUN_ID="$RUN_ID" \
    BATCH_TASK_ID="$task_id" \
    timeout -k 10s "${TIMEOUT_SECONDS}s" \
      "$CODEX_BIN" exec \
      --cd "$ROOT_DIR" \
      --dangerously-bypass-approvals-and-sandbox \
      --skip-git-repo-check \
      --output-last-message "$last_msg_file" \
      "$codex_prompt"
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
  wait_current_observability

  session_id="$(tr -d '\r' < "$session_file" | head -n1 || true)"
  if [ -z "$session_id" ]; then
    session_id="$(grep -m1 -Eo 'session id: [0-9a-f-]+|session_id[\":= ]+[0-9a-f-]+' "$log_file" | grep -Eo '[0-9a-f-]{36}' | head -n1 || true)"
    if [ -n "$session_id" ]; then
      printf '%s\n' "$session_id" > "$session_file"
    else
      : > "$session_file"
    fi
  fi
  session_path="$(tr -d '\r' < "$session_path_file" | head -n1 || true)"

  state_snapshot="$(python3 - <<PY "$STATE_FILE"
import json,sys
p=sys.argv[1]
try:
  d=json.load(open(p,encoding='utf-8'))
except Exception:
  print("\t\t")
  raise SystemExit(0)
status = "" if d.get("status") is None else str(d.get("status"))
conditional_reason = "" if d.get("conditional_reason") is None else str(d.get("conditional_reason"))
blocking_requirement = "" if d.get("blocking_requirement") is None else str(d.get("blocking_requirement"))
print("\t".join([status, conditional_reason, blocking_requirement]))
PY
)"
  IFS=$'\t' read -r current_status conditional_reason blocking_requirement <<< "$state_snapshot"

  final_status=""
  script_writes_status=0
  final_result=""
  result_warning=""
  if [[ "$current_status" =~ ^(COMPLETED_SUCCESS|COMPLETED_CONDITIONAL_SUCCESS|COMPLETED_FAILED)$ ]]; then
    # Agent terminal state is source of truth for task business outcome.
    final_status="$current_status"
  elif [ "$rc" -eq 124 ] || [ "$rc" -eq 137 ]; then
    # timeout: TERM handled (124) or force-killed after grace period (137)
    final_status="TIMED_OUT"
    script_writes_status=1
  else
    # Agent did not persist terminal state; classify as abnormal runtime failure.
    final_status="ABORTED"
    script_writes_status=1
  fi

  if [ "$rc" -ne 0 ] && [[ "$final_status" =~ ^(COMPLETED_SUCCESS|COMPLETED_CONDITIONAL_SUCCESS)$ ]]; then
    result_warning="runner_rc_nonzero_after_agent_terminal"
    WARNING_COUNT=$((WARNING_COUNT + 1))
    RC_MISMATCH_COUNT=$((RC_MISMATCH_COUNT + 1))
  fi

  if [ "$final_status" = "COMPLETED_CONDITIONAL_SUCCESS" ]; then
    if [ -z "$conditional_reason" ] || [ -z "$blocking_requirement" ]; then
      if [ -n "$result_warning" ]; then
        result_warning="${result_warning},missing_conditional_metadata"
      else
        result_warning="missing_conditional_metadata"
      fi
      WARNING_COUNT=$((WARNING_COUNT + 1))
      CONDITIONAL_METADATA_MISSING_COUNT=$((CONDITIONAL_METADATA_MISSING_COUNT + 1))
    fi
  fi

  case "$final_status" in
    COMPLETED_SUCCESS)
      final_result="success"
      SUCCESS_COUNT=$((SUCCESS_COUNT + 1))
      ;;
    COMPLETED_CONDITIONAL_SUCCESS)
      final_result="conditional_success"
      CONDITIONAL_SUCCESS_COUNT=$((CONDITIONAL_SUCCESS_COUNT + 1))
      ;;
    TIMED_OUT)
      final_result="failed"
      FAIL_COUNT=$((FAIL_COUNT + 1))
      TIMEOUT_COUNT=$((TIMEOUT_COUNT + 1))
      ;;
    *)
      final_result="failed"
      FAIL_COUNT=$((FAIL_COUNT + 1))
      ;;
  esac

  docker_cleanup="$(cleanup_current_task_docker_resources)"

  case "$final_result" in
    success) result_file="$RUN_SUCCESS_FILE" ;;
    conditional_success) result_file="$RUN_CONDITIONAL_SUCCESS_FILE" ;;
    *) result_file="$RUN_FAILURE_FILE" ;;
  esac
  printf '%s\ttask_id=%s\tidx=%s\tstatus=%s\tresult=%s\trc=%s\turl=%s\ttarget_json=%s\n' \
    "$(date --iso-8601=seconds)" "$task_id" "$idx" "$final_status" "$final_result" "$rc" "$url" "$record" >> "$result_file"
  if [ -n "$result_warning" ]; then
    printf '%s\ttask_id=%s\twarning=%s\n' \
      "$(date --iso-8601=seconds)" "$task_id" "$result_warning" >> "$result_file"
  fi

  if [ "$script_writes_status" -eq 1 ]; then
    python3 "$ROOT_DIR/.codex/scripts/update_state.py" \
      --state-file "$STATE_FILE" \
      --history-file "$HISTORY_FILE" \
      --status "$final_status" \
      --batch-id "$RUN_ID" \
      --task-id "$task_id" \
      --target-index "$idx" \
      --target-total "$TOTAL" \
      --target-url "$url" \
      --target-json "$record" \
      --result "$final_result" \
      --exit-code "$rc" \
      --log-file "$log_file" \
      --last-message-file "$last_msg_file" \
      --set "session_id=$session_id" \
      --set "session_file=$session_file" \
      --set "session_path=$session_path" \
      --set "docker_cleanup=$docker_cleanup" \
      --set "result_warning=$result_warning" \
      --message "Task finished with $final_status" \
      --append-history
  else
    python3 "$ROOT_DIR/.codex/scripts/update_state.py" \
      --state-file "$STATE_FILE" \
      --history-file "$HISTORY_FILE" \
      --batch-id "$RUN_ID" \
      --task-id "$task_id" \
      --target-index "$idx" \
      --target-total "$TOTAL" \
      --target-url "$url" \
      --target-json "$record" \
      --result "$final_result" \
      --exit-code "$rc" \
      --log-file "$log_file" \
      --last-message-file "$last_msg_file" \
      --set "session_id=$session_id" \
      --set "session_file=$session_file" \
      --set "session_path=$session_path" \
      --set "docker_cleanup=$docker_cleanup" \
      --set "result_warning=$result_warning" \
      --message "Task metadata recorded (agent terminal preserved)" \
      --append-history
  fi

done

summary_file="$RUN_DIR/summary.json"
python3 - <<PY "$summary_file" "$RUN_ID" "$TOTAL" "$SUCCESS_COUNT" "$CONDITIONAL_SUCCESS_COUNT" "$FAIL_COUNT" "$TIMEOUT_COUNT" "$WARNING_COUNT" "$RC_MISMATCH_COUNT" "$CONDITIONAL_METADATA_MISSING_COUNT" "$RUN_DIR" "$RUN_SUCCESS_FILE" "$RUN_CONDITIONAL_SUCCESS_FILE" "$RUN_FAILURE_FILE"
import json,sys,datetime
out=sys.argv[1]
obj={
  "batch_id":sys.argv[2],
  "total":int(sys.argv[3]),
  "success":int(sys.argv[4]),
  "conditional_success":int(sys.argv[5]),
  "failed":int(sys.argv[6]),
  "timed_out":int(sys.argv[7]),
  "warnings":{
    "total":int(sys.argv[8]),
    "rc_mismatch_after_agent_terminal":int(sys.argv[9]),
    "conditional_missing_metadata":int(sys.argv[10])
  },
  "run_dir":sys.argv[11],
  "result_files":{
    "success":sys.argv[12],
    "conditional_success":sys.argv[13],
    "failed":sys.argv[14]
  },
  "finished_at":datetime.datetime.now(datetime.timezone.utc).astimezone().replace(microsecond=0).isoformat()
}
with open(out,'w',encoding='utf-8') as f:
  json.dump(obj,f,ensure_ascii=False,indent=2)
  f.write('\n')
print(json.dumps(obj,ensure_ascii=False))
PY

cp "$RUN_SUCCESS_FILE" "$LATEST_SUCCESS_FILE"
cp "$RUN_CONDITIONAL_SUCCESS_FILE" "$LATEST_CONDITIONAL_SUCCESS_FILE"
cp "$RUN_FAILURE_FILE" "$LATEST_FAILURE_FILE"

python3 "$ROOT_DIR/.codex/scripts/update_state.py" \
  --state-file "$STATE_FILE" \
  --history-file "$HISTORY_FILE" \
  --status IDLE \
  --batch-id "$RUN_ID" \
  --target-total "$TOTAL" \
  --message "Batch completed" \
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
  --unset phase6_subagent_mode \
  --unset phase6_subagent_fallback_reason \
  --unset conditional_reason \
  --unset blocking_requirement \
  --unset result_warning \
  --unset started_at \
  --unset finished_at \
  --append-history

BATCH_FINALIZED=1

echo "Batch completed. Run dir: $RUN_DIR"
