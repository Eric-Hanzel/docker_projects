#!/usr/bin/env python3
import argparse
import json
import os
import re
import signal
import shutil
import subprocess
import sys
import tempfile
import time
import uuid
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from client import AppServerClient, AppServerError, TaskPaths

try:
    import tomllib
except ModuleNotFoundError:  # pragma: no cover
    tomllib = None


TERMINAL_STATUSES = {
    "COMPLETED_SUCCESS",
    "COMPLETED_CONDITIONAL_SUCCESS",
    "COMPLETED_FAILED",
    "TIMED_OUT",
    "ABORTED",
    "IDLE",
}

TASK_RUN_SCOPED_STATE_KEYS = [
    "result",
    "exit_code",
    "project_name",
    "resolved_project_name",
    "resolved_version",
    "cleanup_project_names",
    "cleanup_compose_projects",
    "compose_project_names",
    "compose_project_name",
    "compose_project",
    "primary_compose_project",
    "final_compose_project",
    "docker_cleanup",
    "deliverable_cleanup",
    "conditional_reason",
    "blocking_requirement",
    "thread_id",
    "started_at",
    "finished_at",
    "primary_audit_gate_required",
    "primary_audit_attempts",
    "primary_audit_verdict",
    "primary_audit_result_file",
    "primary_audit_subagent_mode",
    "primary_audit_subagent_fallback_reason",
    "audit_gate_required",
    "audit_attempts",
    "audit_verdict",
    "audit_result_file",
    "portable_subagent_mode",
    "portable_subagent_fallback_reason",
    "delivery_mode",
    "portable_final_required",
]


def now_iso() -> str:
    return datetime.now(timezone.utc).astimezone().replace(microsecond=0).isoformat()


def safe_name(text: str) -> str:
    cleaned = re.sub(r"[^a-zA-Z0-9_.-]+", "-", text.strip())
    cleaned = cleaned.strip("-._")
    return cleaned or "task"


def atomic_write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(prefix=".tmp.", dir=path.parent)
    tmp_path = Path(tmp_name)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(text)
        os.replace(tmp_path, path)
    finally:
        if tmp_path.exists():
            tmp_path.unlink()


def append_jsonl(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(payload, ensure_ascii=False) + "\n")


def load_json(path: Path) -> dict[str, Any]:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}


def read_text(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except FileNotFoundError:
        return ""


def load_jsonl_objects(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    try:
        with path.open("r", encoding="utf-8") as handle:
            for raw_line in handle:
                line = raw_line.strip()
                if not line:
                    continue
                rows.append(json.loads(line))
    except FileNotFoundError:
        return []
    return rows


def load_targets(target_file: Path) -> list[dict[str, Any]]:
    targets: list[dict[str, Any]] = []
    with target_file.open("r", encoding="utf-8") as handle:
        for lineno, raw_line in enumerate(handle, 1):
            line = raw_line.strip()
            if not line or line.startswith("#"):
                continue
            obj = json.loads(line)
            url = obj.get("url")
            if not isinstance(url, str) or not url.strip():
                raise ValueError(f"Invalid target line {lineno}: missing non-empty url")
            obj["delivery_mode"] = "portable-deliverable"
            targets.append(obj)
    if not targets:
        raise ValueError(f"No valid targets in {target_file}")
    return targets


def new_request_id(prefix: str = "req") -> str:
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    suffix = uuid.uuid4().hex[:8]
    return f"{prefix}-{stamp}-{suffix}"


def parse_config(root_dir: Path) -> dict[str, Any]:
    config_path = root_dir / ".codex" / "config.toml"
    if tomllib is None or not config_path.exists():
        return {}
    try:
        return tomllib.loads(config_path.read_text(encoding="utf-8"))
    except Exception:
        return {}


def archive_state_files(state_file: Path, history_file: Path, archive_dir: Path, stamp: str) -> None:
    archive_dir.mkdir(parents=True, exist_ok=True)
    if state_file.exists():
        if state_file.stat().st_size > 0:
            shutil.move(str(state_file), str(archive_dir / f"{state_file.stem}.{stamp}{state_file.suffix}"))
        else:
            state_file.unlink()
    if history_file.exists():
        if history_file.stat().st_size > 0:
            shutil.move(str(history_file), str(archive_dir / f"{history_file.stem}.{stamp}{history_file.suffix}"))
        else:
            history_file.unlink()


def read_state_status(state_file: Path) -> str:
    return str(load_json(state_file).get("status", ""))


def result_from_state(state: dict[str, Any]) -> str:
    result = str(state.get("result", "")).strip()
    if result:
        return result
    status = str(state.get("status", ""))
    if status in {"COMPLETED_SUCCESS", "COMPLETED_CONDITIONAL_SUCCESS"}:
        return "success"
    return "failed"


def summarize_json(value: Any, limit: int = 220) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        text = " ".join(value.split())
    else:
        text = " ".join(json.dumps(value, ensure_ascii=False, sort_keys=True).split())
    if len(text) <= limit:
        return text
    return text[: limit - 3] + "..."


def extract_text(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return value
    if isinstance(value, list):
        parts = [extract_text(item) for item in value]
        return "".join(part for part in parts if part)
    if isinstance(value, dict):
        for key in ("text", "delta", "output_text", "message"):
            if isinstance(value.get(key), str):
                return value[key]
        if "content" in value:
            return extract_text(value["content"])
    return ""


def state_value_args(mapping: dict[str, Any]) -> list[str]:
    args: list[str] = []
    for key, value in mapping.items():
        args.extend(["--set", f"{key}={value}"])
    return args


def update_state(
    root_dir: Path,
    state_file: Path,
    history_file: Path,
    *,
    status: str | None = None,
    append_history: bool = False,
    target_json: dict[str, Any] | None = None,
    set_values: dict[str, Any] | None = None,
    unset_values: list[str] | None = None,
    **kwargs: Any,
) -> None:
    cmd = [
        "python3",
        str(root_dir / ".codex" / "scripts" / "update_state.py"),
        "--state-file",
        str(state_file),
        "--history-file",
        str(history_file),
    ]
    if status is not None:
        cmd.extend(["--status", status])
    if append_history:
        cmd.append("--append-history")
    if target_json is not None:
        cmd.extend(["--target-json", json.dumps(target_json, ensure_ascii=False)])
    for key, value in kwargs.items():
        if value is None:
            continue
        flag = f"--{key.replace('_', '-')}"
        cmd.extend([flag, str(value)])
    if set_values:
        cmd.extend(state_value_args(set_values))
    for item in unset_values or []:
        cmd.extend(["--unset", item])
    subprocess.run(cmd, cwd=root_dir, check=True)


def read_cleanup_projects(state_file: Path) -> list[str]:
    data = load_json(state_file)
    keys = [
        "cleanup_project_names",
        "cleanup_compose_projects",
        "compose_project_names",
        "compose_project_name",
        "compose_project",
        "project_name",
        "resolved_project_name",
    ]
    seen: list[str] = []
    for key in keys:
        value = data.get(key)
        parts: list[str]
        if isinstance(value, list):
            parts = [str(item).strip() for item in value]
        elif isinstance(value, str):
            parts = [piece.strip() for piece in re.split(r"[,\s]+", value)]
        else:
            parts = []
        for part in parts:
            if not part or part in seen:
                continue
            if re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,127}", part):
                seen.append(part)
    return seen


def docker_available() -> bool:
    if shutil.which("docker") is None:
        return False
    result = subprocess.run(["docker", "info"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    return result.returncode == 0


def docker_ids(kind: str, label: str) -> list[str]:
    cmd = ["docker", kind, "ls" if kind != "ps" else "-aq"]  # placeholder
    raise RuntimeError("unreachable")


def cleanup_project_docker_resources(projects: list[str]) -> str:
    if not docker_available():
        return "skipped_project_scoped_cleanup:docker_unavailable"
    if not projects:
        return "skipped_project_scoped_cleanup:no_project_names"

    specs = [
        ("ps", ["docker", "ps", "-aq"]),
        ("network", ["docker", "network", "ls", "-q"]),
        ("volume", ["docker", "volume", "ls", "-q"]),
        ("image", ["docker", "image", "ls", "-q"]),
    ]
    removers = {
        "ps": ["docker", "rm", "-f"],
        "network": ["docker", "network", "rm"],
        "volume": ["docker", "volume", "rm", "-f"],
        "image": ["docker", "image", "rm", "-f"],
    }

    for project in projects:
        for raw_label in (
            f"com.docker.compose.project={project}",
            f"codex.apdv1.cleanup_project={project}",
        ):
            label_filter = f"label={raw_label}"
            for kind, base_cmd in specs:
                result = subprocess.run(
                    [*base_cmd, "--filter", label_filter],
                    capture_output=True,
                    text=True,
                    check=False,
                )
                ids = [line.strip() for line in result.stdout.splitlines() if line.strip()]
                if ids:
                    subprocess.run([*removers[kind], *ids], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    return "attempted_project_scoped_cleanup:" + ",".join(projects)


def cleanup_failed_deliverables(root_dir: Path, state_file: Path) -> str:
    state = load_json(state_file)
    deliverable_root = root_dir / "Deliverable"
    names: list[str] = []
    for key in ("project_name", "resolved_project_name"):
        value = str(state.get(key) or "").strip()
        if value and value not in names and re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,127}", value):
            names.append(value)

    targets: list[Path] = []
    for name in names:
        for candidate in (name, f"{name}-final", f"{name}-image-final"):
            path = deliverable_root / candidate
            if path.parent == deliverable_root and path.exists() and path not in targets:
                targets.append(path)

    def make_writable(func: Any, path: str, _exc_info: Any) -> None:
        os.chmod(path, 0o700)
        func(path)

    def remove_with_docker_helper(path: Path) -> None:
        result = subprocess.run(
            [
                "docker",
                "run",
                "--rm",
                "-v",
                f"{path.resolve()}:/target",
                "busybox:latest",
                "sh",
                "-c",
                "rm -rf /target/* /target/.[!.]* /target/..?*",
            ],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.PIPE,
            text=True,
            check=False,
        )
        if result.returncode != 0:
            raise RuntimeError((result.stderr or "docker helper cleanup failed").strip())
        path.rmdir()

    removed: list[str] = []
    failed: list[str] = []
    for path in targets:
        try:
            if path.is_dir():
                shutil.rmtree(path, onerror=make_writable)
            else:
                path.chmod(0o600)
                path.unlink()
            removed.append(path.name)
        except Exception as exc:
            if path.is_dir():
                try:
                    remove_with_docker_helper(path)
                    removed.append(path.name)
                    continue
                except Exception as helper_exc:
                    failed.append(
                        f"{path.name}:{type(exc).__name__}:{exc};"
                        f"docker_helper={type(helper_exc).__name__}:{helper_exc}"
                    )
            else:
                failed.append(f"{path.name}:{type(exc).__name__}:{exc}")

    if failed:
        prefix = "partial_failed_deliverable_cleanup"
        if removed:
            prefix += ":removed=" + ",".join(removed)
        return prefix + ":failed=" + ";".join(failed)
    if removed:
        return "removed_failed_deliverables:" + ",".join(removed)
    if names:
        return "skipped_failed_deliverable_cleanup:no_matching_outputs"
    return "skipped_failed_deliverable_cleanup:no_project_name"


def validate_successful_final_outputs(
    *,
    root_dir: Path,
    state_file: Path,
    history_file: Path,
    task_dir: Path,
    batch_id: str,
    task_id: str,
    idx: int,
    total: int,
    target: dict[str, Any],
    log_file: Path,
    last_message_file: Path,
) -> bool:
    state = load_json(state_file)
    terminal_status = str(state.get("status", ""))
    if terminal_status not in {"COMPLETED_SUCCESS", "COMPLETED_CONDITIONAL_SUCCESS"}:
        return True
    delivery_mode = str(state.get("delivery_mode", "portable-deliverable")).strip()
    if delivery_mode and delivery_mode != "portable-deliverable":
        return True
    project_name = str(state.get("project_name") or state.get("resolved_project_name") or "").strip()
    result_file = task_dir / "final_output_validation.json"
    if not project_name:
        payload = {"ok": False, "errors": ["missing project_name in task state"], "warnings": []}
        atomic_write_text(result_file, json.dumps(payload, ensure_ascii=False, indent=2) + "\n")
        validation_rc = 1
    else:
        cmd = [
            "python3",
            str(root_dir / ".codex" / "scripts" / "validate_final_outputs.py"),
            project_name,
            "--root",
            str(root_dir),
            "--terminal-status",
            terminal_status,
            "--require-audit",
            "--json",
        ]
        result = subprocess.run(cmd, cwd=root_dir, text=True, capture_output=True, check=False)
        output = result.stdout.strip() or json.dumps(
            {
                "ok": False,
                "errors": [result.stderr.strip() or "validate_final_outputs.py produced no output"],
                "warnings": [],
            },
            ensure_ascii=False,
        )
        atomic_write_text(result_file, output + "\n")
        validation_rc = result.returncode

    if validation_rc == 0:
        return True

    previous_warning = str(state.get("result_warning", "")).strip()
    warning = "final_output_validation_failed"
    if previous_warning:
        warning = f"{previous_warning},{warning}"
    update_state(
        root_dir,
        state_file,
        history_file,
        status="COMPLETED_FAILED",
        batch_id=batch_id,
        task_id=task_id,
        target_index=idx,
        target_total=total,
        target_url=target.get("url", ""),
        target_json=target,
        result="failed",
        exit_code=1,
        log_file=str(log_file),
        last_message_file=str(last_message_file),
        message="Runner downgraded success after final output validation failed",
        set_values={
            "result_warning": warning,
            "final_output_validation_file": str(result_file),
        },
        append_history=True,
    )
    return False


@contextmanager
def file_lock(path: Path):
    import fcntl

    path.parent.mkdir(parents=True, exist_ok=True)
    handle = path.open("w")
    try:
        fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        yield handle
    finally:
        try:
            fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
        except OSError:
            pass
        handle.close()


@dataclass
class ServicePaths:
    state_dir: Path
    service_state_file: Path
    service_history_file: Path
    service_log_file: Path
    service_lock_file: Path
    service_control_file: Path
    task_state_file: Path
    task_history_file: Path
    task_archive_dir: Path
    queue_root: Path
    queue_pending_dir: Path
    queue_active_dir: Path
    queue_completed_dir: Path
    queue_failed_dir: Path
    queue_canceled_dir: Path


def build_service_paths(root_dir: Path) -> ServicePaths:
    state_dir = root_dir / ".codex" / "state"
    queue_root = state_dir / "app_server_queue"
    return ServicePaths(
        state_dir=state_dir,
        service_state_file=state_dir / "app_server_service_state.json",
        service_history_file=state_dir / "app_server_service_history.jsonl",
        service_log_file=state_dir / "app_server_service.log",
        service_lock_file=state_dir / "app_server_batch.lock",
        service_control_file=state_dir / "app_server_service_control.json",
        task_state_file=state_dir / "app_server_task_state.json",
        task_history_file=state_dir / "app_server_task_history.jsonl",
        task_archive_dir=state_dir / "archive",
        queue_root=queue_root,
        queue_pending_dir=queue_root / "pending",
        queue_active_dir=queue_root / "active",
        queue_completed_dir=queue_root / "completed",
        queue_failed_dir=queue_root / "failed",
        queue_canceled_dir=queue_root / "canceled",
    )


def ensure_service_dirs(paths: ServicePaths) -> None:
    paths.state_dir.mkdir(parents=True, exist_ok=True)
    paths.queue_pending_dir.mkdir(parents=True, exist_ok=True)
    paths.queue_active_dir.mkdir(parents=True, exist_ok=True)
    paths.queue_completed_dir.mkdir(parents=True, exist_ok=True)
    paths.queue_failed_dir.mkdir(parents=True, exist_ok=True)
    paths.queue_canceled_dir.mkdir(parents=True, exist_ok=True)


def service_log(paths: ServicePaths, message: str) -> None:
    timestamped = f"[{now_iso()}] {message.rstrip()}\n"
    paths.service_log_file.parent.mkdir(parents=True, exist_ok=True)
    with paths.service_log_file.open("a", encoding="utf-8") as handle:
        handle.write(timestamped)


def update_service_state(
    paths: ServicePaths,
    *,
    status: str,
    append_history: bool = False,
    set_values: dict[str, Any] | None = None,
    unset_values: list[str] | None = None,
    **kwargs: Any,
) -> None:
    current = load_json(paths.service_state_file)
    payload: dict[str, Any] = {
        "version": 1,
        "status": status,
        "updated_at": now_iso(),
    }
    if not current:
        payload["created_at"] = payload["updated_at"]
    else:
        payload["created_at"] = current.get("created_at", payload["updated_at"])
        for key, value in current.items():
            if key not in {"version", "status", "updated_at"}:
                payload[key] = value
    for key, value in kwargs.items():
        if value is not None:
            payload[key] = value
    for key, value in (set_values or {}).items():
        payload[key] = value
    for key in unset_values or []:
        payload.pop(key, None)
    atomic_write_text(paths.service_state_file, json.dumps(payload, ensure_ascii=False, indent=2) + "\n")
    if append_history:
        append_jsonl(paths.service_history_file, payload)


def queue_counts(paths: ServicePaths) -> dict[str, int]:
    return {
        "pending": len(list(paths.queue_pending_dir.glob("*.json"))),
        "active": len(list(paths.queue_active_dir.glob("*.json"))),
        "completed": len(list(paths.queue_completed_dir.glob("*.json"))),
        "failed": len(list(paths.queue_failed_dir.glob("*.json"))),
        "canceled": len(list(paths.queue_canceled_dir.glob("*.json"))),
    }


def queue_record_path(base_dir: Path, request_id: str) -> Path:
    return base_dir / f"{request_id}.json"


def read_queue_record(path: Path) -> dict[str, Any]:
    return load_json(path)


def write_queue_record(path: Path, payload: dict[str, Any]) -> None:
    atomic_write_text(path, json.dumps(payload, ensure_ascii=False, indent=2) + "\n")


def move_queue_record(path: Path, dest_dir: Path, *, status: str, extra: dict[str, Any] | None = None) -> Path:
    payload = read_queue_record(path)
    payload["status"] = status
    payload["updated_at"] = now_iso()
    for key, value in (extra or {}).items():
        payload[key] = value
    dest_path = dest_dir / path.name
    write_queue_record(dest_path, payload)
    if path != dest_path and path.exists():
        path.unlink()
    return dest_path


def read_service_control(paths: ServicePaths) -> dict[str, Any]:
    return load_json(paths.service_control_file)


def write_service_control(paths: ServicePaths, payload: dict[str, Any]) -> None:
    atomic_write_text(paths.service_control_file, json.dumps(payload, ensure_ascii=False, indent=2) + "\n")


def clear_service_control(paths: ServicePaths) -> None:
    try:
        paths.service_control_file.unlink()
    except FileNotFoundError:
        pass


def list_queue_records(base_dir: Path, limit: int = 20) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for path in sorted(base_dir.glob("*.json"))[:limit]:
        payload = read_queue_record(path)
        if payload:
            payload["_path"] = str(path)
            rows.append(payload)
    return rows


def build_prompt(
    *,
    root_dir: Path,
    run_id: str,
    task_id: str,
    idx: int,
    total: int,
    target: dict[str, Any],
    state_file: Path,
    history_file: Path,
) -> str:
    target_json = json.dumps(target, ensure_ascii=False)
    state_rel = os.path.relpath(state_file, root_dir)
    history_rel = os.path.relpath(history_file, root_dir)
    lines = [
        "Target JSON:",
        target_json,
        "",
        "Task requirements:",
        "1. Process only this target end-to-end.",
        f"2. Mode: delivery_mode=portable-deliverable. Follow {root_dir / 'AGENTS.md'} as the workflow source of truth.",
        "3. Required portable workflow: main agent builds and verifies the final bundle using .codex/skills/post-deploy-portable-bundle/SKILL.md when needed, then runs portable_bundle_auditor / .codex/skills/portable-bundle-audit/SKILL.md. Do not run local-run audit.",
        "4. Update the app-server runner state file at actual task start with the exact command block below:",
        "   TARGET_JSON=$(cat <<'JSON'",
        target_json,
        "JSON",
        "   )",
        f"   python3 .codex/scripts/update_state.py --state-file {state_rel} --history-file {history_rel} --status RUNNING --batch-id {run_id} --task-id {task_id} --target-index {idx} --target-total {total} --target-json \"$TARGET_JSON\" --message \"Agent started\" --set delivery_mode=portable-deliverable --set portable_final_required=true --set audit_gate_required=portable_final --append-history",
        "5. At final completion, write exactly one terminal status to that same state file:",
        "   COMPLETED_SUCCESS / COMPLETED_CONDITIONAL_SUCCESS / COMPLETED_FAILED",
        "6. If terminal state is COMPLETED_CONDITIONAL_SUCCESS, also set: --set conditional_reason=<reason> --set blocking_requirement=<required external input/action>",
        "7. As soon as project/compose names are known, set: --set project_name=<resolved_name> --set cleanup_project_names=<comma-separated compose project names>",
        "8. Final terminal write must be the last task-state write, then exit cleanly.",
        "9. App-server runner bootstrap constraint: avoid broad recursive scans of the repository root during initial inspection.",
        "   Do not recursively scan Deliverable/, DP_LOGS/, verification_assignee_*/, runtime-data, or other archived/runtime output trees before you know the exact target path you need.",
        "   For initial inspection, limit yourself to AGENTS.md, .codex/, app_server/, batch/, and directly relevant scripts/files for this target.",
        "   Prefer targeted rg/ls/sed on known paths over root-wide searches.",
    ]
    return "\n".join(lines) + "\n"


def wait_for_turn_completion(
    client: AppServerClient,
    timeout_seconds: int,
    *,
    interrupt_check: Any | None = None,
) -> tuple[str, int]:
    expected_thread_id = client.thread_id
    expected_turn_id = client.turn_id
    deadline = time.monotonic() + timeout_seconds
    while True:
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            return "timeout", 124
        if interrupt_check is not None:
            action = interrupt_check()
            if action:
                return "aborted", 130
        msg = client.recv(timeout=min(remaining, 1.0), allow_idle=True)
        if msg is None:
            return "eof", client.proc.poll() or 1
        if msg.get("_idle"):
            continue
        if msg.get("method") == "turn/completed":
            params = msg.get("params", {})
            turn = params.get("turn", {})
            thread_id = str(params.get("threadId", ""))
            turn_id = str(turn.get("id", ""))
            client.handle_message(msg)
            if thread_id == expected_thread_id and turn_id == expected_turn_id:
                return "completed", 0
            continue
        client.handle_message(msg)


def run_single_task(
    *,
    root_dir: Path,
    codex_bin: str,
    model: str,
    approval_policy: str,
    sandbox_mode: str,
    run_id: str,
    idx: int,
    total: int,
    target: dict[str, Any],
    run_dir: Path,
    state_file: Path,
    history_file: Path,
    timeout_seconds: int,
    lifecycle_mode: str,
    shared_client: AppServerClient | None,
    interrupt_check: Any | None = None,
) -> tuple[str, int, str, AppServerClient | None, str | None]:
    task_id = f"task-{idx:03d}"
    task_dir = run_dir / task_id
    task_dir.mkdir(parents=True, exist_ok=True)
    paths = TaskPaths(
        task_dir=task_dir,
        prompt_file=task_dir / "prompt.txt",
        log_file=task_dir / "codex.log",
        events_file=task_dir / "events.jsonl",
        trace_file=task_dir / "trace.txt",
        last_message_file=task_dir / "last_message.txt",
        session_file=task_dir / "session.json",
        thread_file=task_dir / "thread_id",
        protocol_file=task_dir / "protocol.json",
    )

    prompt = build_prompt(
        root_dir=root_dir,
        run_id=run_id,
        task_id=task_id,
        idx=idx,
        total=total,
        target=target,
        state_file=state_file,
        history_file=history_file,
    )
    atomic_write_text(paths.prompt_file, prompt)
    atomic_write_text(paths.log_file, "")
    atomic_write_text(paths.events_file, "")
    atomic_write_text(paths.trace_file, "")
    atomic_write_text(paths.last_message_file, "")
    atomic_write_text(paths.session_file, "")
    atomic_write_text(paths.thread_file, "")
    atomic_write_text(paths.protocol_file, "")

    update_state(
        root_dir,
        state_file,
        history_file,
        status="STARTING",
        batch_id=run_id,
        task_id=task_id,
        target_index=idx,
        target_total=total,
        target_url=target.get("url", ""),
        target_json=target,
        log_file=str(paths.log_file),
        last_message_file=str(paths.last_message_file),
        message="Dispatching target to Codex app-server",
        set_values={
            "task_dir": str(task_dir),
            "events_file": str(paths.events_file),
            "trace_file": str(paths.trace_file),
            "session_file": str(paths.session_file),
            "delivery_mode": "portable-deliverable",
            "portable_final_required": "true",
            "audit_gate_required": "portable_final",
        },
        unset_values=TASK_RUN_SCOPED_STATE_KEYS,
        append_history=True,
    )

    rc = 0
    docker_cleanup = "not_attempted"
    final_status_written = False
    interrupted_by: str | None = None
    client: AppServerClient | None = shared_client
    max_start_attempts = 2
    keep_client = lifecycle_mode == "per-run"
    try:
        for attempt in range(1, max_start_attempts + 1):
            if client is None:
                client = AppServerClient(
                    root_dir=root_dir,
                    codex_bin=codex_bin,
                    model=model,
                    approval_policy=approval_policy,
                    sandbox_mode=sandbox_mode,
                    task_paths=paths,
                    lifecycle_label=lifecycle_mode,
                )
            else:
                if client.is_alive():
                    client.set_task_paths(paths)
                    client._append_task_log("runner_info: reusing existing app-server process for new task\n")
                else:
                    client.restart(paths)
            try:
                client.ensure_initialized()

                thread_result = client.request(
                    "thread/start",
                    {
                        "model": model,
                        "cwd": str(root_dir),
                        "serviceName": "apdv1_appserver_runner",
                    },
                    timeout=60.0,
                )
                thread = thread_result.get("thread", {})
                client.thread_id = str(thread.get("id", ""))
                session_payload = {
                    "thread_id": client.thread_id,
                    "session_id": thread.get("sessionId"),
                    "created_at": now_iso(),
                    "model": model,
                }
                atomic_write_text(paths.thread_file, client.thread_id + "\n")
                atomic_write_text(paths.session_file, json.dumps(session_payload, ensure_ascii=False, indent=2) + "\n")

                update_state(
                    root_dir,
                    state_file,
                    history_file,
                    batch_id=run_id,
                    task_id=task_id,
                    target_index=idx,
                    target_total=total,
                    target_url=target.get("url", ""),
                    message="Thread started; waiting for agent execution",
                    set_values={"thread_id": client.thread_id},
                    append_history=True,
                )

                turn_result = client.request(
                    "turn/start",
                    {
                        "threadId": client.thread_id,
                        "input": [{"type": "text", "text": prompt}],
                    },
                    timeout=60.0,
                )
                turn = turn_result.get("turn", {})
                client.turn_id = str(turn.get("id", ""))
                outcome, rc = wait_for_turn_completion(
                    client,
                    timeout_seconds=timeout_seconds,
                    interrupt_check=interrupt_check,
                )
                if outcome in {"timeout", "aborted"}:
                    try:
                        client.request(
                            "turn/interrupt",
                            {"threadId": client.thread_id, "turnId": client.turn_id},
                            timeout=10.0,
                        )
                    except AppServerError:
                        pass
                if outcome == "aborted" and interrupt_check is not None:
                    interrupted_by = interrupt_check()
                if outcome == "completed":
                    for _ in range(10):
                        state = load_json(state_file)
                        if str(state.get("status", "")) in {
                            "COMPLETED_SUCCESS",
                            "COMPLETED_CONDITIONAL_SUCCESS",
                            "COMPLETED_FAILED",
                        }:
                            break
                        time.sleep(0.5)
                state = load_json(state_file)
                current_status = str(state.get("status", ""))
                if current_status not in {
                    "COMPLETED_SUCCESS",
                    "COMPLETED_CONDITIONAL_SUCCESS",
                    "COMPLETED_FAILED",
                }:
                    if outcome == "timeout":
                        final_status = "TIMED_OUT"
                        result = "failed"
                    elif outcome == "aborted":
                        final_status = "ABORTED"
                        result = "failed"
                    else:
                        final_status = "ABORTED"
                        result = "failed"
                    update_state(
                        root_dir,
                        state_file,
                        history_file,
                        status=final_status,
                        batch_id=run_id,
                        task_id=task_id,
                        target_index=idx,
                        target_total=total,
                        target_url=target.get("url", ""),
                        target_json=target,
                        result=result,
                        exit_code=rc,
                        log_file=str(paths.log_file),
                        last_message_file=str(paths.last_message_file),
                        message=(
                            f"Task aborted by {interrupted_by}"
                            if outcome == "aborted" and interrupted_by
                            else f"Task finished with {final_status}"
                        ),
                        append_history=True,
                    )
                    final_status_written = True
                else:
                    final_status_written = True
                break
            except AppServerError as exc:
                if attempt >= max_start_attempts or client.thread_id:
                    raise
                client._append_task_log(f"runner_retry: app-server startup attempt {attempt} failed: {exc}\n")
                client.restart(paths)
                time.sleep(1.0)
    except Exception as exc:
        error_summary = summarize_json({"error": str(exc), "type": exc.__class__.__name__}, limit=500)
        if client is not None:
            client._append_task_log(f"runner_error: {error_summary}\n")
        else:
            with paths.log_file.open("a", encoding="utf-8") as handle:
                handle.write(f"runner_error: {error_summary}\n")
        current_status = str(load_json(state_file).get("status", ""))
        if current_status not in TERMINAL_STATUSES:
            update_state(
                root_dir,
                state_file,
                history_file,
                status="ABORTED",
                batch_id=run_id,
                task_id=task_id,
                target_index=idx,
                target_total=total,
                target_url=target.get("url", ""),
                target_json=target,
                result="failed",
                exit_code=1,
                log_file=str(paths.log_file),
                last_message_file=str(paths.last_message_file),
                message=f"Runner aborted: {error_summary}",
                append_history=True,
            )
            final_status_written = True
        rc = 1
    finally:
        if client is not None and not keep_client:
            client.close()
        if final_status_written:
            validate_successful_final_outputs(
                root_dir=root_dir,
                state_file=state_file,
                history_file=history_file,
                task_dir=task_dir,
                batch_id=run_id,
                task_id=task_id,
                idx=idx,
                total=total,
                target=target,
                log_file=paths.log_file,
                last_message_file=paths.last_message_file,
            )
        docker_cleanup = cleanup_project_docker_resources(read_cleanup_projects(state_file))
        deliverable_cleanup = "not_attempted"
        terminal_status = str(load_json(state_file).get("status", ""))
        if terminal_status not in {"COMPLETED_SUCCESS", "COMPLETED_CONDITIONAL_SUCCESS"}:
            deliverable_cleanup = cleanup_failed_deliverables(root_dir, state_file)
            update_state(
                root_dir,
                state_file,
                history_file,
                set_values={"deliverable_cleanup": deliverable_cleanup},
            )
        with paths.trace_file.open("a", encoding="utf-8") as handle:
            handle.write(f"[{now_iso()}] runner cleanup: {docker_cleanup}\n")
            handle.write(f"[{now_iso()}] runner deliverable cleanup: {deliverable_cleanup}\n")
        if not final_status_written:
            with paths.log_file.open("a", encoding="utf-8") as handle:
                handle.write("runner_warning: task exited without terminal state write\n")
    return task_id, rc, docker_cleanup, client if keep_client else None, interrupted_by


def summarize_run(
    *,
    run_dir: Path,
    run_id: str,
    total: int,
    success: int,
    conditional_success: int,
    failed: int,
    timed_out: int,
) -> None:
    payload = {
        "batch_id": run_id,
        "total": total,
        "success": success,
        "conditional_success": conditional_success,
        "failed": failed,
        "timed_out": timed_out,
        "run_dir": str(run_dir),
        "finished_at": now_iso(),
    }
    atomic_write_text(run_dir / "summary.json", json.dumps(payload, ensure_ascii=False, indent=2) + "\n")


def resolve_targets(root_dir: Path, target_json: str | None, target_file: str) -> list[dict[str, Any]]:
    if target_json:
        target = json.loads(target_json)
        url = target.get("url")
        if not isinstance(url, str) or not url.strip():
            raise SystemExit("--target-json must contain a non-empty url")
        target["delivery_mode"] = "portable-deliverable"
        return [target]
    target_path = Path(target_file)
    if not target_path.is_absolute():
        target_path = root_dir / target_path
    return load_targets(target_path)


def run_batch_mode(args: argparse.Namespace) -> int:
    root_dir = Path(__file__).resolve().parent.parent
    config = parse_config(root_dir)
    model = str(config.get("model", "gpt-5.4"))
    approval_policy = str(config.get("approval_policy", "never"))
    sandbox_mode = str(config.get("sandbox_mode", "danger-full-access"))
    service_paths = build_service_paths(root_dir)
    ensure_service_dirs(service_paths)

    run_id = f"{args.run_prefix}-{datetime.now().strftime('%Y%m%d_%H%M%S')}-{os.getpid()}"
    run_dir = root_dir / "app_server" / "runs" / run_id
    results_dir = root_dir / "app_server" / "results" / run_id
    run_dir.mkdir(parents=True, exist_ok=True)
    results_dir.mkdir(parents=True, exist_ok=True)
    targets = resolve_targets(root_dir, args.target_json, args.target_file)

    try:
        with file_lock(service_paths.service_lock_file):
            existing_status = read_state_status(service_paths.task_state_file)
            if existing_status == "RUNNING":
                raise SystemExit("Refusing to start: existing app-server runner state is RUNNING")

            archive_state_files(
                service_paths.task_state_file,
                service_paths.task_history_file,
                service_paths.task_archive_dir,
                run_id,
            )
            update_state(
                root_dir,
                service_paths.task_state_file,
                service_paths.task_history_file,
                status="INITIALIZING",
                batch_id=run_id,
                target_total=len(targets),
                pid=os.getpid(),
                message="App-server batch initializing",
                unset_values=[
                    "task_id",
                    "target_index",
                    "target_url",
                    "target",
                    *TASK_RUN_SCOPED_STATE_KEYS,
                ],
                append_history=True,
            )

            success = 0
            conditional_success = 0
            failed = 0
            timed_out = 0
            shared_client: AppServerClient | None = None

            try:
                for idx, target in enumerate(targets, 1):
                    if args.server_lifecycle == "per-task":
                        shared_client = None
                    append_jsonl(
                        results_dir / "results.jsonl",
                        {
                            "ts": now_iso(),
                            "task_id": f"task-{idx:03d}",
                            "server_lifecycle": args.server_lifecycle,
                            "server_reuse": "enabled" if args.server_lifecycle == "per-run" else "disabled",
                        },
                    )
                    _, _, _, shared_client, _ = run_single_task(
                        root_dir=root_dir,
                        codex_bin=args.codex_bin,
                        model=model,
                        approval_policy=approval_policy,
                        sandbox_mode=sandbox_mode,
                        run_id=run_id,
                        idx=idx,
                        total=len(targets),
                        target=target,
                        run_dir=run_dir,
                        state_file=service_paths.task_state_file,
                        history_file=service_paths.task_history_file,
                        timeout_seconds=args.timeout_seconds,
                        lifecycle_mode=args.server_lifecycle,
                        shared_client=shared_client,
                    )
                    if args.server_lifecycle == "per-run":
                        current_state = load_json(service_paths.task_state_file)
                        if str(current_state.get("status", "")) == "ABORTED":
                            if shared_client is not None:
                                shared_client.close()
                            shared_client = None
                        elif shared_client is not None and not shared_client.is_alive():
                            shared_client.close()
                            shared_client = None
                    state = load_json(service_paths.task_state_file)
                    status = str(state.get("status", ""))
                    target_result = result_from_state(state)
                    append_jsonl(
                        results_dir / "results.jsonl",
                        {
                            "ts": now_iso(),
                            "task_id": f"task-{idx:03d}",
                            "status": status,
                            "result": target_result,
                            "target": target,
                            "server_lifecycle": args.server_lifecycle,
                        },
                    )
                    if status == "COMPLETED_SUCCESS":
                        success += 1
                    elif status == "COMPLETED_CONDITIONAL_SUCCESS":
                        conditional_success += 1
                    else:
                        failed += 1
                        if status == "TIMED_OUT":
                            timed_out += 1
            finally:
                if shared_client is not None:
                    shared_client.close()

            summarize_run(
                run_dir=run_dir,
                run_id=run_id,
                total=len(targets),
                success=success,
                conditional_success=conditional_success,
                failed=failed,
                timed_out=timed_out,
            )
    except BlockingIOError:
        raise SystemExit(f"Another app-server batch run is active (lock: {service_paths.service_lock_file})")

    print(f"App-server batch completed. Run dir: {run_dir}")
    return 0


def enqueue_targets(root_dir: Path, service_paths: ServicePaths, targets: list[dict[str, Any]], source: str) -> list[str]:
    ensure_service_dirs(service_paths)
    request_ids: list[str] = []
    for target in targets:
        target = dict(target)
        target["delivery_mode"] = "portable-deliverable"
        request_id = new_request_id("req")
        payload = {
            "request_id": request_id,
            "status": "pending",
            "submitted_at": now_iso(),
            "updated_at": now_iso(),
            "source": source,
            "target": target,
        }
        write_queue_record(queue_record_path(service_paths.queue_pending_dir, request_id), payload)
        request_ids.append(request_id)
    return request_ids


def recover_active_queue(service_paths: ServicePaths) -> int:
    recovered = 0
    for path in sorted(service_paths.queue_active_dir.glob("*.json")):
        payload = read_queue_record(path)
        payload["status"] = "pending"
        payload["updated_at"] = now_iso()
        payload["recovered_from_active_at"] = now_iso()
        dest = queue_record_path(service_paths.queue_pending_dir, path.stem)
        write_queue_record(dest, payload)
        path.unlink()
        recovered += 1
    return recovered


def claim_next_request(service_paths: ServicePaths) -> tuple[Path, dict[str, Any]] | None:
    pending = sorted(service_paths.queue_pending_dir.glob("*.json"))
    if not pending:
        return None
    path = pending[0]
    payload = read_queue_record(path)
    payload["status"] = "active"
    payload["started_at"] = now_iso()
    payload["updated_at"] = now_iso()
    active_path = queue_record_path(service_paths.queue_active_dir, path.stem)
    write_queue_record(active_path, payload)
    path.unlink()
    return active_path, payload


def complete_request_record(
    service_paths: ServicePaths,
    active_path: Path,
    *,
    terminal_status: str,
    result: str,
    run_id: str,
    run_dir: Path,
    state: dict[str, Any],
) -> Path:
    dest_dir = (
        service_paths.queue_completed_dir
        if terminal_status in {"COMPLETED_SUCCESS", "COMPLETED_CONDITIONAL_SUCCESS"}
        else service_paths.queue_failed_dir
    )
    return move_queue_record(
        active_path,
        dest_dir,
        status=terminal_status,
        extra={
            "result": result,
            "completed_at": now_iso(),
            "run_id": run_id,
            "run_dir": str(run_dir),
            "task_state": state,
        },
    )


def service_process_request(
    *,
    root_dir: Path,
    service_paths: ServicePaths,
    config: dict[str, Any],
    request_path: Path,
    request: dict[str, Any],
    shared_client: AppServerClient | None,
    server_lifecycle: str,
    timeout_seconds: int,
) -> AppServerClient | None:
    model = str(config.get("model", "gpt-5.4"))
    approval_policy = str(config.get("approval_policy", "never"))
    sandbox_mode = str(config.get("sandbox_mode", "danger-full-access"))
    run_id = f"service-{request['request_id']}"
    run_dir = root_dir / "app_server" / "runs" / run_id
    results_dir = root_dir / "app_server" / "results" / run_id
    run_dir.mkdir(parents=True, exist_ok=True)
    results_dir.mkdir(parents=True, exist_ok=True)
    archive_state_files(
        service_paths.task_state_file,
        service_paths.task_history_file,
        service_paths.task_archive_dir,
        request["request_id"],
    )
    update_service_state(
        service_paths,
        status="PROCESSING",
        append_history=True,
        current_request_id=request["request_id"],
        current_target_url=request["target"].get("url", ""),
        current_run_id=run_id,
        current_run_dir=str(run_dir),
        heartbeat_at=now_iso(),
        queue=queue_counts(service_paths),
    )
    service_log(service_paths, f"processing request {request['request_id']} target={request['target'].get('url', '')}")
    observed_control: dict[str, str | None] = {"action": None}

    def interrupt_check() -> str | None:
        control = read_service_control(service_paths)
        action = str(control.get("action", "")).strip()
        if action not in {"abort_current", "stop_service"}:
            return None
        target_request = str(control.get("request_id", "")).strip()
        if target_request and target_request != request["request_id"]:
            return None
        observed_control["action"] = action
        return action

    _, _, _, shared_client, interrupted_by = run_single_task(
        root_dir=root_dir,
        codex_bin=os.environ.get("CODEX_BIN", "codex"),
        model=model,
        approval_policy=approval_policy,
        sandbox_mode=sandbox_mode,
        run_id=run_id,
        idx=1,
        total=1,
        target=request["target"],
        run_dir=run_dir,
        state_file=service_paths.task_state_file,
        history_file=service_paths.task_history_file,
        timeout_seconds=timeout_seconds,
        lifecycle_mode=server_lifecycle,
        shared_client=shared_client,
        interrupt_check=interrupt_check,
    )
    state = load_json(service_paths.task_state_file)
    terminal_status = str(state.get("status", "ABORTED"))
    result = result_from_state(state)
    append_jsonl(
        results_dir / "results.jsonl",
        {
            "ts": now_iso(),
            "task_id": "task-001",
            "status": terminal_status,
            "result": result,
            "target": request["target"],
            "request_id": request["request_id"],
            "server_lifecycle": server_lifecycle,
        },
    )
    summarize_run(
        run_dir=run_dir,
        run_id=run_id,
        total=1,
        success=1 if terminal_status == "COMPLETED_SUCCESS" else 0,
        conditional_success=1 if terminal_status == "COMPLETED_CONDITIONAL_SUCCESS" else 0,
        failed=0 if terminal_status in {"COMPLETED_SUCCESS", "COMPLETED_CONDITIONAL_SUCCESS"} else 1,
        timed_out=1 if terminal_status == "TIMED_OUT" else 0,
    )
    complete_request_record(
        service_paths,
        request_path,
        terminal_status=terminal_status,
        result=result,
        run_id=run_id,
        run_dir=run_dir,
        state=state,
    )
    if observed_control["action"] is not None:
        service_log(
            service_paths,
            f"applied control action {observed_control['action']} to request {request['request_id']}",
        )
        clear_service_control(service_paths)
    update_service_state(
        service_paths,
        status="IDLE",
        append_history=True,
        last_request_id=request["request_id"],
        last_terminal_status=terminal_status,
        last_result=result,
        last_run_id=run_id,
        last_run_dir=str(run_dir),
        heartbeat_at=now_iso(),
        queue=queue_counts(service_paths),
        unset_values=["current_request_id", "current_target_url", "current_run_id", "current_run_dir"],
    )
    service_log(service_paths, f"completed request {request['request_id']} status={terminal_status} result={result}")
    if server_lifecycle == "per-run" and shared_client is not None and not shared_client.is_alive():
        shared_client.close()
        shared_client = None
    if server_lifecycle == "per-task" and shared_client is not None:
        shared_client.close()
        shared_client = None
    if interrupted_by == "stop_service":
        write_service_control(
            service_paths,
            {
                "action": "stop_after_current",
                "request_id": request["request_id"],
                "created_at": now_iso(),
                "source": "service",
            },
        )
    return shared_client


def run_service(args: argparse.Namespace) -> int:
    root_dir = Path(__file__).resolve().parent.parent
    service_paths = build_service_paths(root_dir)
    ensure_service_dirs(service_paths)
    config = parse_config(root_dir)
    recovered = recover_active_queue(service_paths)

    stop_requested = {"value": False}

    def handle_stop(signum: int, _frame: Any) -> None:
        stop_requested["value"] = True
        service_log(service_paths, f"received signal {signum}, stopping after current loop")

    signal.signal(signal.SIGTERM, handle_stop)
    signal.signal(signal.SIGINT, handle_stop)

    try:
        with file_lock(service_paths.service_lock_file):
            service_log(
                service_paths,
                f"service starting pid={os.getpid()} lifecycle={args.server_lifecycle} recovered_active={recovered}",
            )
            update_service_state(
                service_paths,
                status="IDLE",
                append_history=True,
                pid=os.getpid(),
                started_at=now_iso(),
                heartbeat_at=now_iso(),
                server_lifecycle=args.server_lifecycle,
                queue=queue_counts(service_paths),
            )
            shared_client: AppServerClient | None = None
            while not stop_requested["value"]:
                control = read_service_control(service_paths)
                if str(control.get("action", "")).strip() == "stop_after_current":
                    clear_service_control(service_paths)
                    stop_requested["value"] = True
                    service_log(service_paths, "stopping after current request due to control action")
                    continue
                claimed = claim_next_request(service_paths)
                update_service_state(
                    service_paths,
                    status="IDLE" if claimed is None else "PROCESSING",
                    queue=queue_counts(service_paths),
                    heartbeat_at=now_iso(),
                )
                if claimed is None:
                    time.sleep(args.poll_interval)
                    continue
                request_path, request = claimed
                try:
                    shared_client = service_process_request(
                        root_dir=root_dir,
                        service_paths=service_paths,
                        config=config,
                        request_path=request_path,
                        request=request,
                        shared_client=shared_client,
                        server_lifecycle=args.server_lifecycle,
                        timeout_seconds=args.timeout_seconds,
                    )
                except Exception as exc:
                    service_log(service_paths, f"request {request['request_id']} crashed: {exc}")
                    move_queue_record(
                        request_path,
                        service_paths.queue_failed_dir,
                        status="ABORTED",
                        extra={"result": "failed", "error": str(exc), "completed_at": now_iso()},
                    )
                    update_service_state(
                        service_paths,
                        status="IDLE",
                        append_history=True,
                        last_request_id=request["request_id"],
                        last_terminal_status="ABORTED",
                        last_result="failed",
                        heartbeat_at=now_iso(),
                        queue=queue_counts(service_paths),
                        unset_values=["current_request_id", "current_target_url", "current_run_id", "current_run_dir"],
                    )
                    if shared_client is not None:
                        shared_client.close()
                        shared_client = None
            if shared_client is not None:
                shared_client.close()
            clear_service_control(service_paths)
            update_service_state(
                service_paths,
                status="STOPPED",
                append_history=True,
                stopped_at=now_iso(),
                heartbeat_at=now_iso(),
                queue=queue_counts(service_paths),
                unset_values=["current_request_id", "current_target_url", "current_run_id", "current_run_dir"],
            )
            service_log(service_paths, f"service stopped pid={os.getpid()}")
    except BlockingIOError:
        raise SystemExit(f"App-server service already running (lock: {service_paths.service_lock_file})")
    return 0


def run_submit(args: argparse.Namespace) -> int:
    root_dir = Path(__file__).resolve().parent.parent
    service_paths = build_service_paths(root_dir)
    targets = resolve_targets(root_dir, args.target_json, args.target_file)
    request_ids = enqueue_targets(root_dir, service_paths, targets, source=args.source)
    for request_id in request_ids:
        print(request_id)
    return 0


def find_request_record(service_paths: ServicePaths, request_id: str) -> tuple[Path | None, dict[str, Any] | None]:
    for base_dir in (
        service_paths.queue_pending_dir,
        service_paths.queue_active_dir,
        service_paths.queue_completed_dir,
        service_paths.queue_failed_dir,
        service_paths.queue_canceled_dir,
    ):
        path = queue_record_path(base_dir, request_id)
        if path.exists():
            return path, read_queue_record(path)
    return None, None


def run_status(args: argparse.Namespace) -> int:
    root_dir = Path(__file__).resolve().parent.parent
    service_paths = build_service_paths(root_dir)
    ensure_service_dirs(service_paths)
    payload = {
        "service_state": load_json(service_paths.service_state_file),
        "queue_counts": queue_counts(service_paths),
        "pending": list_queue_records(service_paths.queue_pending_dir, limit=args.limit),
        "active": list_queue_records(service_paths.queue_active_dir, limit=args.limit),
        "recent_failed": list_queue_records(service_paths.queue_failed_dir, limit=args.limit),
        "recent_completed": list_queue_records(service_paths.queue_completed_dir, limit=args.limit),
        "recent_canceled": list_queue_records(service_paths.queue_canceled_dir, limit=args.limit),
    }
    if args.json:
        print(json.dumps(payload, ensure_ascii=False, indent=2))
        return 0
    service_state = payload["service_state"] or {}
    print(f"service_status: {service_state.get('status', 'unknown')}")
    print(f"service_pid: {service_state.get('pid', '')}")
    print(f"server_lifecycle: {service_state.get('server_lifecycle', '')}")
    print(f"heartbeat_at: {service_state.get('heartbeat_at', '')}")
    print(f"current_request_id: {service_state.get('current_request_id', '')}")
    print(f"last_request_id: {service_state.get('last_request_id', '')}")
    print("queue_counts:")
    for key, value in payload["queue_counts"].items():
        print(f"  {key}: {value}")
    for section in ("active", "pending", "recent_failed", "recent_completed", "recent_canceled"):
        rows = payload[section]
        print(f"{section}: {len(rows)}")
        for row in rows[: args.limit]:
            print(
                f"  {row.get('request_id','')} status={row.get('status','')} "
                f"url={row.get('target',{}).get('url','')} updated_at={row.get('updated_at','')}"
            )
    return 0


def run_cancel(args: argparse.Namespace) -> int:
    root_dir = Path(__file__).resolve().parent.parent
    service_paths = build_service_paths(root_dir)
    ensure_service_dirs(service_paths)
    path, record = find_request_record(service_paths, args.request_id)
    if path is None or record is None:
        raise SystemExit(f"Unknown request_id: {args.request_id}")
    if str(record.get("status", "")) == "pending":
        move_queue_record(
            path,
            service_paths.queue_canceled_dir,
            status="CANCELLED",
            extra={"result": "canceled", "canceled_at": now_iso(), "cancel_source": args.source},
        )
        service_log(service_paths, f"canceled pending request {args.request_id} source={args.source}")
        print(f"Canceled pending request {args.request_id}")
        return 0
    if str(record.get("status", "")) == "active":
        write_service_control(
            service_paths,
            {
                "action": "abort_current",
                "request_id": args.request_id,
                "created_at": now_iso(),
                "source": args.source,
            },
        )
        service_log(service_paths, f"requested abort for active request {args.request_id} source={args.source}")
        print(f"Abort requested for active request {args.request_id}")
        return 0
    print(f"Request {args.request_id} is already in terminal state {record.get('status', '')}")
    return 0


def run_abort_current(args: argparse.Namespace) -> int:
    root_dir = Path(__file__).resolve().parent.parent
    service_paths = build_service_paths(root_dir)
    service_state = load_json(service_paths.service_state_file)
    current_request_id = str(service_state.get("current_request_id", "")).strip()
    if not current_request_id:
        raise SystemExit("No active request to abort")
    write_service_control(
        service_paths,
        {
            "action": "abort_current",
            "request_id": current_request_id,
            "created_at": now_iso(),
            "source": args.source,
        },
    )
    service_log(service_paths, f"requested abort-current for request {current_request_id} source={args.source}")
    print(f"Abort requested for current request {current_request_id}")
    return 0


def run_stop(args: argparse.Namespace) -> int:
    root_dir = Path(__file__).resolve().parent.parent
    service_paths = build_service_paths(root_dir)
    service_state = load_json(service_paths.service_state_file)
    pid = service_state.get("pid")
    if not isinstance(pid, int):
        raise SystemExit("Service pid not available; service may not be running")
    write_service_control(
        service_paths,
        {
            "action": "stop_service",
            "request_id": str(service_state.get("current_request_id", "")).strip() or None,
            "created_at": now_iso(),
            "source": args.source,
        },
    )
    try:
        os.kill(pid, signal.SIGTERM)
    except ProcessLookupError:
        raise SystemExit(f"Service pid {pid} is not running")
    service_log(service_paths, f"requested service stop pid={pid} source={args.source}")
    print(f"Stop requested for service pid {pid}")
    return 0


def tail_file(path: Path, lines: int) -> str:
    text = read_text(path)
    if not text:
        return ""
    return "\n".join(text.splitlines()[-lines:])


def run_tail(args: argparse.Namespace) -> int:
    root_dir = Path(__file__).resolve().parent.parent
    service_paths = build_service_paths(root_dir)
    if args.request_id is None:
        output = tail_file(service_paths.service_log_file, args.lines)
        if output:
            print(output)
        return 0
    path, record = find_request_record(service_paths, args.request_id)
    if path is None or record is None:
        raise SystemExit(f"Unknown request_id: {args.request_id}")
    if args.file == "record":
        print(json.dumps(record, ensure_ascii=False, indent=2))
        return 0
    run_dir = record.get("run_dir")
    if not run_dir:
        print(json.dumps(record, ensure_ascii=False, indent=2))
        return 0
    task_dir = Path(run_dir) / "task-001"
    file_map = {
        "log": task_dir / "codex.log",
        "trace": task_dir / "trace.txt",
        "events": task_dir / "events.jsonl",
        "last-message": task_dir / "last_message.txt",
        "protocol": task_dir / "protocol.json",
    }
    output = tail_file(file_map[args.file], args.lines)
    if output:
        print(output)
    return 0


def run_doctor(args: argparse.Namespace) -> int:
    root_dir = Path(__file__).resolve().parent.parent
    config = parse_config(root_dir)
    model = str(config.get("model", "gpt-5.4"))
    approval_policy = str(config.get("approval_policy", "never"))
    sandbox_mode = str(config.get("sandbox_mode", "danger-full-access"))
    run_id = f"doctor-{datetime.now().strftime('%Y%m%d_%H%M%S')}-{os.getpid()}"
    task_dir = root_dir / "app_server" / "runs" / run_id / "protocol-smoke"
    task_dir.mkdir(parents=True, exist_ok=True)
    paths = TaskPaths(
        task_dir=task_dir,
        prompt_file=task_dir / "prompt.txt",
        log_file=task_dir / "codex.log",
        events_file=task_dir / "events.jsonl",
        trace_file=task_dir / "trace.txt",
        last_message_file=task_dir / "last_message.txt",
        session_file=task_dir / "session.json",
        thread_file=task_dir / "thread_id",
        protocol_file=task_dir / "protocol.json",
    )
    for path in (
        paths.prompt_file,
        paths.log_file,
        paths.events_file,
        paths.trace_file,
        paths.last_message_file,
        paths.session_file,
        paths.thread_file,
        paths.protocol_file,
    ):
        atomic_write_text(path, "")

    schema_dir = task_dir / "schema"
    try:
        schema_result = subprocess.run(
            [
                args.codex_bin,
                "app-server",
                "generate-json-schema",
                "--experimental",
                "--out",
                str(schema_dir),
            ],
            cwd=root_dir,
            capture_output=True,
            text=True,
            timeout=60,
            check=False,
        )
        schema_check = {
            "ok": schema_result.returncode == 0,
            "returncode": schema_result.returncode,
            "stderr": summarize_json(schema_result.stderr, limit=500),
        }
    except Exception as exc:
        schema_check = {"ok": False, "error": f"{exc.__class__.__name__}: {exc}"}

    client: AppServerClient | None = None
    checks: dict[str, Any] = {
        "run_id": run_id,
        "task_dir": str(task_dir),
        "schema_generation": schema_check,
        "initialize": {"ok": False},
        "thread_loaded_list": {"ok": False},
        "thread_start": {"ok": False},
        "thread_unsubscribe": {"ok": False},
    }
    try:
        client = AppServerClient(
            root_dir=root_dir,
            codex_bin=args.codex_bin,
            model=model,
            approval_policy=approval_policy,
            sandbox_mode=sandbox_mode,
            task_paths=paths,
            lifecycle_label="doctor",
        )
        init_result = client.ensure_initialized()
        checks["initialize"] = {"ok": True, "result_keys": sorted(init_result.keys())}
        loaded = client.request("thread/loaded/list", {}, timeout=30.0)
        checks["thread_loaded_list"] = {"ok": True, "count": len(loaded.get("data", []))}
        thread_result = client.request(
            "thread/start",
            {
                "model": model,
                "cwd": str(root_dir),
                "approvalPolicy": approval_policy,
                "serviceName": "apdv1_appserver_runner_doctor",
            },
            timeout=60.0,
        )
        thread = thread_result.get("thread", {})
        thread_id = str(thread.get("id", ""))
        checks["thread_start"] = {
            "ok": bool(thread_id),
            "thread_id": thread_id,
            "session_id": thread.get("sessionId"),
        }
        if thread_id:
            unsub = client.request("thread/unsubscribe", {"threadId": thread_id}, timeout=30.0)
            checks["thread_unsubscribe"] = {"ok": True, "status": unsub.get("status", "")}
    except Exception as exc:
        checks["error"] = {"type": exc.__class__.__name__, "message": str(exc)}
    finally:
        if client is not None:
            client.close()

    ok = all(value.get("ok", False) for key, value in checks.items() if isinstance(value, dict) and key != "error")
    checks["ok"] = ok
    atomic_write_text(task_dir / "doctor_result.json", json.dumps(checks, ensure_ascii=False, indent=2) + "\n")
    if args.json:
        print(json.dumps(checks, ensure_ascii=False, indent=2))
    else:
        print(f"doctor_ok: {ok}")
        print(f"task_dir: {task_dir}")
        print(f"schema_generation: {checks['schema_generation']['ok']}")
        print(f"initialize: {checks['initialize']['ok']}")
        print(f"thread_loaded_list: {checks['thread_loaded_list']['ok']}")
        print(f"thread_start: {checks['thread_start']['ok']}")
        print(f"thread_unsubscribe: {checks['thread_unsubscribe']['ok']}")
        if "error" in checks:
            print(f"error: {checks['error']['type']}: {checks['error']['message']}")
    return 0 if ok else 1


def build_legacy_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Parallel app-server-based Codex deployment runner")
    parser.add_argument("--target-file", default="batch/target.txt")
    parser.add_argument("--target-json", help="Run a single JSON target instead of a JSONL file")
    parser.add_argument("--timeout-seconds", type=int, default=int(os.environ.get("TIMEOUT_SECONDS", "3000")))
    parser.add_argument("--codex-bin", default=os.environ.get("CODEX_BIN", "codex"))
    parser.add_argument("--run-prefix", default="appserver-batch")
    parser.add_argument(
        "--server-lifecycle",
        choices=("per-run", "per-task"),
        default=os.environ.get("APP_SERVER_LIFECYCLE", "per-run"),
        help="Reuse one codex app-server process across the whole run, or start a fresh process per task.",
    )
    return parser


def build_service_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="App-server manual service and queue controls")
    subparsers = parser.add_subparsers(dest="command", required=True)

    serve = subparsers.add_parser("serve", help="Run a single-worker app-server service and process queued tasks")
    serve.add_argument("--timeout-seconds", type=int, default=int(os.environ.get("TIMEOUT_SECONDS", "3000")))
    serve.add_argument("--poll-interval", type=float, default=2.0)
    serve.add_argument(
        "--server-lifecycle",
        choices=("per-run", "per-task"),
        default=os.environ.get("APP_SERVER_LIFECYCLE", "per-run"),
    )

    submit = subparsers.add_parser("submit", help="Queue one or more targets for the app-server service")
    submit.add_argument("--target-file", default="batch/target.txt")
    submit.add_argument("--target-json")
    submit.add_argument("--source", default="manual")

    status = subparsers.add_parser("status", help="Show service state and queue status")
    status.add_argument("--json", action="store_true")
    status.add_argument("--limit", type=int, default=10)

    tail = subparsers.add_parser("tail", help="Tail service log or task logs for a specific request")
    tail.add_argument("--request-id")
    tail.add_argument("--file", choices=("log", "trace", "events", "last-message", "protocol", "record"), default="trace")
    tail.add_argument("-n", "--lines", type=int, default=40)

    cancel = subparsers.add_parser("cancel", help="Cancel a pending request or abort a matching active request")
    cancel.add_argument("--request-id", required=True)
    cancel.add_argument("--source", default="manual")

    abort_current = subparsers.add_parser("abort-current", help="Abort the currently active request but keep the service available")
    abort_current.add_argument("--source", default="manual")

    stop = subparsers.add_parser("stop", help="Stop the service and abort the current request if one is active")
    stop.add_argument("--source", default="manual")

    doctor = subparsers.add_parser("doctor", help="Run app-server protocol smoke checks without starting a model turn")
    doctor.add_argument("--codex-bin", default=os.environ.get("CODEX_BIN", "codex"))
    doctor.add_argument("--json", action="store_true")
    return parser


def main() -> int:
    if len(sys.argv) > 1 and sys.argv[1] in {
        "serve",
        "submit",
        "status",
        "tail",
        "cancel",
        "abort-current",
        "stop",
        "doctor",
    }:
        parser = build_service_parser()
        args = parser.parse_args()
        if args.command == "serve":
            return run_service(args)
        if args.command == "submit":
            return run_submit(args)
        if args.command == "status":
            return run_status(args)
        if args.command == "tail":
            return run_tail(args)
        if args.command == "cancel":
            return run_cancel(args)
        if args.command == "abort-current":
            return run_abort_current(args)
        if args.command == "stop":
            return run_stop(args)
        if args.command == "doctor":
            return run_doctor(args)
        raise SystemExit(f"Unsupported command: {args.command}")
    parser = build_legacy_parser()
    args = parser.parse_args()
    return run_batch_mode(args)


if __name__ == "__main__":
    raise SystemExit(main())
