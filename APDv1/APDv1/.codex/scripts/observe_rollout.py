#!/usr/bin/env python3
import argparse
import json
import os
import re
import shutil
import signal
import sys
import tempfile
import time
from pathlib import Path


SESSION_RE = re.compile(r"(?:session id:\s*|session_id[\":= ]+)([0-9a-f-]{36})", re.IGNORECASE)
STOP = False


def handle_signal(_signum, _frame):
    global STOP
    STOP = True


def atomic_write_text(path: str, text: str) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix=".observe.", dir=os.path.dirname(path))
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            fh.write(text)
        os.replace(tmp, path)
    finally:
        if os.path.exists(tmp):
            os.unlink(tmp)


def atomic_copy(src: str, dst: str) -> None:
    os.makedirs(os.path.dirname(dst), exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix=".trajectory.", dir=os.path.dirname(dst))
    os.close(fd)
    try:
        shutil.copyfile(src, tmp)
        os.replace(tmp, dst)
    finally:
        if os.path.exists(tmp):
            os.unlink(tmp)


def read_text(path: str) -> str:
    try:
        with open(path, "r", encoding="utf-8", errors="replace") as fh:
            return fh.read()
    except FileNotFoundError:
        return ""


def parse_json_maybe(value):
    if not isinstance(value, str):
        return value
    text = value.strip()
    if not text:
        return value
    try:
        return json.loads(text)
    except Exception:
        return value


def compact_text(value) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return " ".join(value.split())
    if isinstance(value, list):
        parts = [compact_text(item) for item in value]
        return " ".join(part for part in parts if part)
    if isinstance(value, dict):
        if isinstance(value.get("text"), str):
            return compact_text(value["text"])
        if isinstance(value.get("content"), list):
            return compact_text(value["content"])
        if isinstance(value.get("message"), str):
            return compact_text(value["message"])
        if isinstance(value.get("output_text"), str):
            return compact_text(value["output_text"])
    return compact_text(str(value))


def truncate(text: str, limit: int = 180) -> str:
    text = compact_text(text)
    if len(text) <= limit:
        return text
    return text[: limit - 3] + "..."


def extract_first_line(text: str) -> str:
    for line in str(text).splitlines():
        line = line.strip()
        if line:
            return line
    return ""


def safe_name(text: str) -> str:
    cleaned = re.sub(r"[^a-zA-Z0-9_.-]+", "-", text.strip())
    cleaned = cleaned.strip("-._")
    return cleaned or "agent"


def find_session_id(log_file: str) -> str:
    match = SESSION_RE.search(read_text(log_file))
    return match.group(1) if match else ""


def resolve_session_path(session_id: str, sessions_root: str) -> str:
    root = Path(sessions_root)
    if not session_id or not root.exists():
        return ""
    matches = sorted(root.rglob(f"rollout-*{session_id}.jsonl"), key=lambda p: p.stat().st_mtime)
    if matches:
        return str(matches[-1])
    return ""


def summarize_tool_call(name: str, arguments) -> str:
    args = parse_json_maybe(arguments)
    if name == "exec_command" and isinstance(args, dict):
        return truncate(args.get("cmd", ""))
    if name == "spawn_agent" and isinstance(args, dict):
        summary = args.get("message") or compact_text(args.get("items"))
        agent_type = args.get("agent_type") or "default"
        if summary:
            return truncate(f"{agent_type} :: {summary}")
        return agent_type
    if name == "wait_agent" and isinstance(args, dict):
        targets = args.get("targets") or []
        timeout_ms = args.get("timeout_ms")
        return truncate(f"targets={targets} timeout_ms={timeout_ms}")
    if name == "send_input" and isinstance(args, dict):
        target = args.get("target", "")
        summary = args.get("message") or compact_text(args.get("items"))
        return truncate(f"target={target} :: {summary}")
    if name == "apply_patch":
        patch_text = arguments if isinstance(arguments, str) else compact_text(arguments)
        return truncate(extract_first_line(patch_text))
    if isinstance(args, dict):
        for key in ("message", "query", "url", "cmd"):
            if key in args and args[key]:
                return truncate(str(args[key]))
        return truncate(json.dumps(args, ensure_ascii=False, sort_keys=True))
    return truncate(str(arguments))


def summarize_tool_output(name: str, output) -> str:
    data = parse_json_maybe(output)
    if name == "exec_command":
        if isinstance(data, dict):
            code = data.get("exit_code")
            if code is None:
                code = data.get("code")
            snippet = extract_first_line(
                data.get("stdout") or data.get("stderr") or data.get("output") or ""
            )
            base = f"exit={code}" if code is not None else "completed"
            if snippet:
                return truncate(f"{base} :: {snippet}")
            return base
        text = str(data)
        match = re.search(r"Process exited with code\s+(-?\d+)", text)
        if match:
            return f"exit={match.group(1)}"
        return truncate(extract_first_line(text) or "completed")
    if name == "spawn_agent":
        if isinstance(data, dict):
            agent_id = data.get("id") or data.get("agent_id") or "unknown"
            nickname = data.get("nickname") or data.get("user_facing_name") or ""
            return truncate(f"id={agent_id} {nickname}".strip())
        return truncate(str(data))
    if name == "wait_agent":
        return truncate(compact_text(data) or "completed")
    if name == "send_input":
        return truncate(compact_text(data) or "queued")
    if isinstance(data, dict):
        keys = ",".join(sorted(data.keys())[:6])
        return truncate(keys or "completed")
    return truncate(str(data) or "completed")


def append_trace(trace_file: str, line: str) -> None:
    os.makedirs(os.path.dirname(trace_file), exist_ok=True)
    with open(trace_file, "a", encoding="utf-8") as fh:
        fh.write(line.rstrip() + "\n")


def ensure_session_entry(sessions: dict, session_id: str, label: str, task_agents_dir: str) -> dict:
    entry = sessions.get(session_id)
    if entry:
        current_label = entry.get("label", "")
        if label and (
            current_label == session_id
            or current_label == ""
            or (":" in label and ":" not in current_label)
        ):
            entry["label"] = label
        return entry

    if session_id == "parent":
        raise ValueError("parent is a reserved label, not a session id")

    session_dir = os.path.join(task_agents_dir, safe_name(label))
    entry = {
        "session_id": session_id,
        "label": label or session_id,
        "path": "",
        "trajectory_file": os.path.join(session_dir, "trajectory.jsonl"),
        "offset_file": os.path.join(session_dir, "trace.offset"),
        "session_path_file": os.path.join(session_dir, "session_path"),
        "copied_signature": None,
        "call_map": {},
        "announced": False,
        "last_signature": None,
    }
    sessions[session_id] = entry
    return entry


def discover_spawned_agent(payload: dict, sessions: dict, task_agents_dir: str) -> None:
    payload_type = payload.get("type", "")
    if payload_type == "collab_agent_spawn_end":
        new_thread_id = payload.get("new_thread_id", "")
        role = payload.get("new_agent_role") or "agent"
        nickname = payload.get("new_agent_nickname") or ""
        label = role if not nickname else f"{role}:{nickname}"
        if new_thread_id:
            ensure_session_entry(sessions, new_thread_id, label, task_agents_dir)


def build_trace_lines(entry: dict, obj: dict, task_agents_dir: str, sessions: dict) -> list[str]:
    obj_type = obj.get("type", "")
    payload = obj.get("payload") or {}
    payload_type = payload.get("type", "")
    timestamp = obj.get("timestamp", "")
    prefix = f"{timestamp} [{entry['label']}]"
    emitted = []

    if obj_type == "event_msg":
        discover_spawned_agent(payload, sessions, task_agents_dir)
        if payload_type == "agent_message":
            message = truncate(payload.get("message", ""))
            if message:
                emitted.append(f"{prefix} [assistant] {message}")
    elif obj_type == "response_item" and payload_type == "function_call":
        name = payload.get("name", "tool")
        call_id = payload.get("call_id", "")
        if call_id:
            entry["call_map"][call_id] = name
        summary = summarize_tool_call(name, payload.get("arguments"))
        if name == "spawn_agent":
            emitted.append(f"{prefix} [subagent_start] {summary}")
        elif name == "wait_agent":
            emitted.append(f"{prefix} [subagent_wait] {summary}")
        elif name == "send_input":
            emitted.append(f"{prefix} [subagent_input] {summary}")
        else:
            emitted.append(f"{prefix} [tool_call] {name} :: {summary}")
    elif obj_type == "response_item" and payload_type == "function_call_output":
        call_id = payload.get("call_id", "")
        name = entry["call_map"].get(call_id, "tool")
        summary = summarize_tool_output(name, payload.get("output"))
        if name == "spawn_agent":
            output = parse_json_maybe(payload.get("output"))
            if isinstance(output, dict):
                agent_id = output.get("agent_id") or output.get("id") or ""
                nickname = output.get("nickname") or output.get("user_facing_name") or ""
                if agent_id:
                    label = nickname or agent_id
                    ensure_session_entry(sessions, agent_id, label, task_agents_dir)
            emitted.append(f"{prefix} [subagent_result] {summary}")
        elif name == "wait_agent":
            emitted.append(f"{prefix} [subagent_wait_result] {summary}")
        elif name == "send_input":
            emitted.append(f"{prefix} [subagent_input_result] {summary}")
        else:
            emitted.append(f"{prefix} [tool_result] {name} :: {summary}")
    elif obj_type == "response_item" and payload_type == "message":
        role = payload.get("role", "")
        content = truncate(compact_text(payload.get("content")))
        if role == "assistant" and content:
            emitted.append(f"{prefix} [assistant] {content}")

    return emitted


def render_session(entry: dict, trace_file: str, task_agents_dir: str, sessions: dict) -> None:
    try:
        with open(entry["trajectory_file"], "r", encoding="utf-8", errors="replace") as fh:
            raw_lines = fh.readlines()
    except FileNotFoundError:
        return

    try:
        processed = int(read_text(entry["offset_file"]).strip() or "0")
    except ValueError:
        processed = 0

    if processed < 0 or processed > len(raw_lines):
        processed = 0

    next_processed = processed
    for idx in range(processed, len(raw_lines)):
        raw = raw_lines[idx].strip()
        if not raw:
            next_processed = idx + 1
            continue
        try:
            obj = json.loads(raw)
        except json.JSONDecodeError:
            break

        for line in build_trace_lines(entry, obj, task_agents_dir, sessions):
            signature = (obj.get("timestamp", ""), line)
            if signature != entry.get("last_signature"):
                append_trace(trace_file, line)
                entry["last_signature"] = signature
        next_processed = idx + 1

    atomic_write_text(entry["offset_file"], f"{next_processed}\n")


def sync_session(entry: dict, sessions_root: str, trace_file: str, task_agents_dir: str, sessions: dict) -> None:
    if not entry.get("path"):
        entry["path"] = resolve_session_path(entry["session_id"], sessions_root)
        if entry["path"]:
            atomic_write_text(entry["session_path_file"], f"{entry['path']}\n")

    if not entry.get("path") or not os.path.exists(entry["path"]):
        return

    stat = os.stat(entry["path"])
    signature = (stat.st_mtime_ns, stat.st_size)
    if signature == entry.get("copied_signature"):
        return

    atomic_copy(entry["path"], entry["trajectory_file"])
    entry["copied_signature"] = signature

    if not entry["announced"]:
        append_trace(trace_file, f"{time.strftime('%Y-%m-%dT%H:%M:%S%z')} [{entry['label']}] [session] {entry['session_id']} :: {entry['path']}")
        entry["announced"] = True

    render_session(entry, trace_file, task_agents_dir, sessions)


def child_alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
        return True
    except ProcessLookupError:
        return False
    except PermissionError:
        return True


def main() -> int:
    ap = argparse.ArgumentParser(description="Mirror Codex rollouts and render a readable multi-agent trace")
    ap.add_argument("--log-file", required=True)
    ap.add_argument("--session-file", required=True)
    ap.add_argument("--session-path-file", required=True)
    ap.add_argument("--trajectory-file", required=True)
    ap.add_argument("--trace-file", required=True)
    ap.add_argument("--trace-offset-file", required=True)
    ap.add_argument("--trace-pid-file", required=True)
    ap.add_argument("--child-pid", type=int, required=True)
    ap.add_argument("--agents-dir", required=True)
    ap.add_argument("--sessions-root", default=os.path.expanduser("~/.codex/sessions"))
    ap.add_argument("--poll-interval", type=float, default=2.0)
    ap.add_argument("--settle-polls", type=int, default=3)
    args = ap.parse_args()

    signal.signal(signal.SIGTERM, handle_signal)
    signal.signal(signal.SIGINT, handle_signal)

    atomic_write_text(args.trace_pid_file, f"{os.getpid()}\n")
    for path in (
        args.session_file,
        args.session_path_file,
        args.trajectory_file,
        args.trace_file,
        args.trace_offset_file,
    ):
        os.makedirs(os.path.dirname(path), exist_ok=True)
        if not os.path.exists(path):
            atomic_write_text(path, "")
    os.makedirs(args.agents_dir, exist_ok=True)

    sessions = {
        "__parent__": {
            "session_id": "",
            "label": "parent",
            "path": "",
            "trajectory_file": args.trajectory_file,
            "offset_file": args.trace_offset_file,
            "session_path_file": args.session_path_file,
            "copied_signature": None,
            "call_map": {},
            "announced": False,
            "last_signature": None,
        }
    }
    child_done_polls = 0

    while not STOP:
        parent = sessions["__parent__"]
        if not parent["session_id"]:
            parent["session_id"] = find_session_id(args.log_file)
            if parent["session_id"]:
                atomic_write_text(args.session_file, f"{parent['session_id']}\n")

        if parent["session_id"]:
            sync_session(parent, args.sessions_root, args.trace_file, args.agents_dir, sessions)

        child_session_ids = [sid for sid in sessions.keys() if sid != "__parent__"]
        for session_id in child_session_ids:
            sync_session(sessions[session_id], args.sessions_root, args.trace_file, args.agents_dir, sessions)

        if child_alive(args.child_pid):
            child_done_polls = 0
        else:
            child_done_polls += 1
            if child_done_polls >= args.settle_polls:
                break

        time.sleep(args.poll_interval)

    parent = sessions["__parent__"]
    if parent["session_id"] and not read_text(args.session_file).strip():
        atomic_write_text(args.session_file, f"{parent['session_id']}\n")

    if parent["session_id"]:
        sync_session(parent, args.sessions_root, args.trace_file, args.agents_dir, sessions)
    child_session_ids = [sid for sid in sessions.keys() if sid != "__parent__"]
    for session_id in child_session_ids:
        sync_session(sessions[session_id], args.sessions_root, args.trace_file, args.agents_dir, sessions)

    return 0


if __name__ == "__main__":
    sys.exit(main())
