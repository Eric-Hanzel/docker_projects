#!/usr/bin/env python3
import argparse
import json
import os
import tempfile
from datetime import datetime, timezone

TERMINAL = {
    "COMPLETED_SUCCESS",
    "COMPLETED_CONDITIONAL_SUCCESS",
    "COMPLETED_FAILED",
    "TIMED_OUT",
    "ABORTED",
    "IDLE",
}


def now_iso() -> str:
    return datetime.now(timezone.utc).astimezone().replace(microsecond=0).isoformat()


def load_json(path: str):
    if not os.path.exists(path):
        return {}
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def atomic_write(path: str, data):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix=".state.", dir=os.path.dirname(path))
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
            f.write("\n")
        os.replace(tmp, path)
    finally:
        if os.path.exists(tmp):
            os.unlink(tmp)


def parse_set(pairs):
    out = {}
    for kv in pairs or []:
        if "=" not in kv:
            continue
        k, v = kv.split("=", 1)
        out[k.strip()] = v
    return out


def main():
    ap = argparse.ArgumentParser(description="Update Codex task state JSON atomically")
    ap.add_argument("--state-file", default=".codex/state/task_state.json")
    ap.add_argument("--history-file", default=".codex/state/task_history.jsonl")
    ap.add_argument("--status", default=None)
    ap.add_argument("--batch-id", default=None)
    ap.add_argument("--task-id", default=None)
    ap.add_argument("--target-index", type=int, default=None)
    ap.add_argument("--target-total", type=int, default=None)
    ap.add_argument("--target-url", default=None)
    ap.add_argument("--target-json", default=None)
    ap.add_argument("--message", default=None)
    ap.add_argument("--phase", default=None)
    ap.add_argument("--result", default=None)
    ap.add_argument("--exit-code", type=int, default=None)
    ap.add_argument("--pid", type=int, default=None)
    ap.add_argument("--log-file", default=None)
    ap.add_argument("--last-message-file", default=None)
    ap.add_argument("--append-history", action="store_true")
    ap.add_argument("--set", action="append", default=[])
    ap.add_argument("--unset", action="append", default=[])
    args = ap.parse_args()

    state = load_json(args.state_file)
    ts = now_iso()

    if not state:
        state = {
            "version": 1,
            "status": "IDLE",
            "created_at": ts,
            "updated_at": ts,
        }

    if args.status is not None:
        state["status"] = args.status

    if args.batch_id is not None:
        state["batch_id"] = args.batch_id
    if args.task_id is not None:
        state["task_id"] = args.task_id
    if args.target_index is not None:
        state["target_index"] = args.target_index
    if args.target_total is not None:
        state["target_total"] = args.target_total
    if args.target_url is not None:
        state["target_url"] = args.target_url
    if args.message is not None:
        state["message"] = args.message
    if args.phase is not None:
        state["phase"] = args.phase
    if args.result is not None:
        state["result"] = args.result
    if args.exit_code is not None:
        state["exit_code"] = args.exit_code
    if args.pid is not None:
        state["pid"] = args.pid
    if args.log_file is not None:
        state["log_file"] = args.log_file
    if args.last_message_file is not None:
        state["last_message_file"] = args.last_message_file

    if args.target_json is not None:
        try:
            state["target"] = json.loads(args.target_json)
        except Exception:
            state["target"] = {"raw": args.target_json}

    state.update(parse_set(args.set))
    for key in args.unset or []:
        if key:
            state.pop(key, None)

    if state.get("status") == "RUNNING" and "started_at" not in state:
        state["started_at"] = ts

    if state.get("status") in TERMINAL:
        state["finished_at"] = ts

    state["updated_at"] = ts

    atomic_write(args.state_file, state)

    if args.append_history:
        os.makedirs(os.path.dirname(args.history_file), exist_ok=True)
        with open(args.history_file, "a", encoding="utf-8") as f:
            f.write(json.dumps(state, ensure_ascii=False) + "\n")


if __name__ == "__main__":
    main()
