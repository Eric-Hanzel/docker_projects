#!/usr/bin/env python3
import argparse
import json
import os
import subprocess
import sys
import tempfile
import time
from datetime import datetime
from pathlib import Path
from typing import Any

try:
    import tomllib
except ModuleNotFoundError:  # pragma: no cover
    tomllib = None

from client import AppServerClient, TaskPaths, UnixSocketAppServerClient, WebSocketAppServerClient
from client.schemas import generate_schema, read_method_index, validate_method


def parse_config(root_dir: Path) -> dict[str, Any]:
    config_path = root_dir / ".codex" / "config.toml"
    if tomllib is None or not config_path.exists():
        return {}
    try:
        return tomllib.loads(config_path.read_text(encoding="utf-8"))
    except Exception:
        return {}


def write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def make_paths(root_dir: Path, label: str) -> TaskPaths:
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    task_dir = root_dir / "app_server" / "runs" / f"client-{label}-{stamp}-{os.getpid()}"
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
        write_text(path, "")
    return paths


def make_client(args: argparse.Namespace, root_dir: Path, label: str) -> tuple[AppServerClient, TaskPaths, dict[str, Any]]:
    config = parse_config(root_dir)
    model = args.model or str(config.get("model", "gpt-5.4"))
    approval_policy = args.approval_policy or str(config.get("approval_policy", "never"))
    sandbox_mode = args.sandbox_mode or str(config.get("sandbox_mode", "danger-full-access"))
    paths = make_paths(root_dir, label)
    client = AppServerClient(
        root_dir=root_dir,
        codex_bin=args.codex_bin,
        model=model,
        approval_policy=approval_policy,
        sandbox_mode=sandbox_mode,
        task_paths=paths,
        lifecycle_label=f"generic-cli:{label}",
        client_info={
            "name": "apdv1_generic_appserver_client",
            "title": "APDv1 Generic App Server Client",
            "version": "0.1.0",
        },
    )
    return client, paths, {"model": model, "approval_policy": approval_policy, "sandbox_mode": sandbox_mode}


def print_payload(payload: Any, *, as_json: bool = True) -> None:
    if as_json:
        print(json.dumps(payload, ensure_ascii=False, indent=2))
    else:
        print(payload)


def cmd_schema(args: argparse.Namespace) -> int:
    root_dir = Path(args.root).resolve()
    out_dir = Path(args.out) if args.out else root_dir / "app_server" / "schemas" / "latest"
    if not out_dir.is_absolute():
        out_dir = root_dir / out_dir
    result = generate_schema(codex_bin=args.codex_bin, root_dir=root_dir, out_dir=out_dir, experimental=args.experimental)
    if result["ok"]:
        try:
            result["methods"] = read_method_index(out_dir)
        except Exception as exc:
            result["method_index_error"] = str(exc)
    print_payload(result)
    return 0 if result["ok"] else 1


def cmd_methods(args: argparse.Namespace) -> int:
    root_dir = Path(args.root).resolve()
    with tempfile.TemporaryDirectory(prefix="codex-app-schema.") as tmp:
        out_dir = Path(tmp)
        result = generate_schema(codex_bin=args.codex_bin, root_dir=root_dir, out_dir=out_dir, experimental=True)
        if not result["ok"]:
            print_payload(result)
            return 1
        methods = read_method_index(out_dir)
    print_payload(methods)
    return 0


def cmd_validate_method(args: argparse.Namespace) -> int:
    root_dir = Path(args.root).resolve()
    with tempfile.TemporaryDirectory(prefix="codex-app-schema.") as tmp:
        out_dir = Path(tmp)
        result = generate_schema(codex_bin=args.codex_bin, root_dir=root_dir, out_dir=out_dir, experimental=True)
        if not result["ok"]:
            print_payload(result)
            return 1
        methods = read_method_index(out_dir)
    payload = validate_method(methods, direction=args.direction, method=args.method)
    print_payload(payload)
    return 0 if payload["ok"] else 1


def cmd_doctor(args: argparse.Namespace) -> int:
    root_dir = Path(args.root).resolve()
    with tempfile.TemporaryDirectory(prefix="codex-app-schema.") as tmp:
        schema_result = generate_schema(
            codex_bin=args.codex_bin,
            root_dir=root_dir,
            out_dir=Path(tmp),
            experimental=True,
        )
        method_index = read_method_index(Path(tmp)) if schema_result["ok"] else {}
    client: AppServerClient | None = None
    checks: dict[str, Any] = {
        "schema_generation": {k: v for k, v in schema_result.items() if k in {"ok", "returncode", "stderr", "out_dir"}},
        "method_counts": {
            "client_requests": len(method_index.get("client_requests", [])),
            "server_requests": len(method_index.get("server_requests", [])),
        },
        "initialize": {"ok": False},
        "thread_loaded_list": {"ok": False},
        "thread_start": {"ok": False},
        "thread_unsubscribe": {"ok": False},
    }
    try:
        client, paths, resolved = make_client(args, root_dir, "doctor")
        init_result = client.ensure_initialized()
        checks["initialize"] = {"ok": True, "result_keys": sorted(init_result.keys())}
        loaded = client.request("thread/loaded/list", {}, timeout=30)
        checks["thread_loaded_list"] = {"ok": True, "count": len(loaded.get("data", []))}
        thread_result = client.start_thread(
            {
                "model": resolved["model"],
                "cwd": str(root_dir),
                "approvalPolicy": resolved["approval_policy"],
                "serviceName": "apdv1_generic_appserver_client",
            },
            timeout=60,
        )
        thread = thread_result.get("thread", {})
        thread_id = str(thread.get("id", ""))
        checks["thread_start"] = {"ok": bool(thread_id), "thread_id": thread_id, "session_id": thread.get("sessionId")}
        if thread_id:
            unsub = client.request("thread/unsubscribe", {"threadId": thread_id}, timeout=30)
            checks["thread_unsubscribe"] = {"ok": True, "status": unsub.get("status", "")}
        checks["paths"] = {"task_dir": str(paths.task_dir)}
    except Exception as exc:
        checks["error"] = {"type": exc.__class__.__name__, "message": str(exc)}
    finally:
        if client is not None:
            client.close()
    checks["ok"] = all(value.get("ok", False) for key, value in checks.items() if key != "error" and isinstance(value, dict) and "ok" in value)
    print_payload(checks)
    return 0 if checks["ok"] else 1


def cmd_request(args: argparse.Namespace) -> int:
    root_dir = Path(args.root).resolve()
    params = json.loads(args.params) if args.params else {}
    client: AppServerClient | None = None
    try:
        client, paths, _ = make_client(args, root_dir, "request")
        if not args.no_initialize:
            client.ensure_initialized()
        result = client.request(args.method, params, timeout=args.timeout)
        print_payload({"ok": True, "result": result, "paths": {"task_dir": str(paths.task_dir)}})
        return 0
    finally:
        if client is not None:
            client.close()


def cmd_unix_request(args: argparse.Namespace) -> int:
    params = json.loads(args.params) if args.params else {}
    client = UnixSocketAppServerClient(Path(args.socket))
    try:
        if not args.no_initialize:
            init_result = client.request(
                "initialize",
                {
                    "clientInfo": {
                        "name": "apdv1_generic_unix_appserver_client",
                        "title": "APDv1 Generic Unix App Server Client",
                        "version": "0.1.0",
                    },
                    "capabilities": {"experimentalApi": True},
                },
                timeout=args.timeout,
            )
            client.send({"method": "initialized", "params": {}})
        else:
            init_result = None
        result = client.request(args.method, params, timeout=args.timeout)
        print_payload({"ok": True, "initialize": init_result, "result": result})
        return 0
    finally:
        client.close()


def cmd_ws_request(args: argparse.Namespace) -> int:
    params = json.loads(args.params) if args.params else {}
    headers = {}
    if args.authorization:
        headers["Authorization"] = args.authorization
    client = WebSocketAppServerClient(args.url, headers=headers)
    try:
        if not args.no_initialize:
            init_result = client.request(
                "initialize",
                {
                    "clientInfo": {
                        "name": "apdv1_generic_ws_appserver_client",
                        "title": "APDv1 Generic WebSocket App Server Client",
                        "version": "0.1.0",
                    },
                    "capabilities": {"experimentalApi": True},
                },
                timeout=args.timeout,
            )
            client.send({"method": "initialized", "params": {}})
        else:
            init_result = None
        result = client.request(args.method, params, timeout=args.timeout)
        print_payload({"ok": True, "initialize": init_result, "result": result})
        return 0
    finally:
        client.close()


def cmd_thread_start(args: argparse.Namespace) -> int:
    root_dir = Path(args.root).resolve()
    client: AppServerClient | None = None
    try:
        client, paths, resolved = make_client(args, root_dir, "thread-start")
        client.ensure_initialized()
        cwd = str(Path(args.cwd).resolve()) if args.cwd else str(root_dir)
        result = client.start_thread(
            {
                "model": resolved["model"],
                "cwd": cwd,
                "approvalPolicy": resolved["approval_policy"],
                "serviceName": args.service_name,
            },
            timeout=args.timeout,
        )
        print_payload({"ok": True, "result": result, "paths": {"task_dir": str(paths.task_dir)}})
        return 0
    finally:
        if client is not None:
            client.close()


def cmd_thread_list(args: argparse.Namespace) -> int:
    root_dir = Path(args.root).resolve()
    client: AppServerClient | None = None
    try:
        client, paths, _ = make_client(args, root_dir, "thread-list")
        client.ensure_initialized()
        result = client.request("thread/loaded/list", {}, timeout=args.timeout)
        print_payload({"ok": True, "result": result, "paths": {"task_dir": str(paths.task_dir)}})
        return 0
    finally:
        if client is not None:
            client.close()


def cmd_thread_read(args: argparse.Namespace) -> int:
    root_dir = Path(args.root).resolve()
    client: AppServerClient | None = None
    try:
        client, paths, _ = make_client(args, root_dir, "thread-read")
        client.ensure_initialized()
        result = client.request("thread/read", {"threadId": args.thread_id}, timeout=args.timeout)
        print_payload({"ok": True, "result": result, "paths": {"task_dir": str(paths.task_dir)}})
        return 0
    finally:
        if client is not None:
            client.close()


def cmd_thread_unsubscribe(args: argparse.Namespace) -> int:
    root_dir = Path(args.root).resolve()
    client: AppServerClient | None = None
    try:
        client, paths, _ = make_client(args, root_dir, "thread-unsubscribe")
        client.ensure_initialized()
        result = client.request("thread/unsubscribe", {"threadId": args.thread_id}, timeout=args.timeout)
        print_payload({"ok": True, "result": result, "paths": {"task_dir": str(paths.task_dir)}})
        return 0
    finally:
        if client is not None:
            client.close()


def _read_prompt(args: argparse.Namespace) -> str:
    if args.prompt_file:
        return Path(args.prompt_file).read_text(encoding="utf-8")
    if args.text:
        return args.text
    if not sys.stdin.isatty():
        return sys.stdin.read()
    raise SystemExit("turn start requires --text, --prompt-file, or stdin")


def cmd_turn_start(args: argparse.Namespace) -> int:
    root_dir = Path(args.root).resolve()
    client: AppServerClient | None = None
    try:
        client, paths, resolved = make_client(args, root_dir, "turn-start")
        client.ensure_initialized()
        thread_id = args.thread_id
        if not thread_id:
            thread_result = client.start_thread(
                {
                    "model": resolved["model"],
                    "cwd": str(Path(args.cwd).resolve()) if args.cwd else str(root_dir),
                    "approvalPolicy": resolved["approval_policy"],
                    "serviceName": args.service_name,
                },
                timeout=args.timeout,
            )
            thread_id = str(thread_result.get("thread", {}).get("id", ""))
        prompt = _read_prompt(args)
        write_text(paths.prompt_file, prompt)
        result = client.start_turn(thread_id, [{"type": "text", "text": prompt}], timeout=args.timeout)
        turn_id = str(result.get("turn", {}).get("id", ""))
        wait_result: dict[str, Any] | None = None
        if args.wait:
            deadline = time.monotonic() + args.wait_timeout
            while True:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    wait_result = {"status": "timeout"}
                    break
                msg = client.recv(timeout=min(remaining, 1.0), allow_idle=True)
                if msg is None:
                    wait_result = {"status": "eof", "returncode": client.proc.poll() if client.proc else None}
                    break
                if msg.get("_idle"):
                    continue
                client.handle_message(msg)
                if msg.get("method") == "turn/completed":
                    wait_result = {"status": "completed", "turn": msg.get("params", {}).get("turn", {})}
                    break
        print_payload(
            {
                "ok": True,
                "thread_id": thread_id,
                "turn_id": turn_id,
                "result": result,
                "wait": wait_result,
                "paths": {"task_dir": str(paths.task_dir)},
            }
        )
        return 0
    finally:
        if client is not None:
            client.close()


def cmd_turn_interrupt(args: argparse.Namespace) -> int:
    root_dir = Path(args.root).resolve()
    client: AppServerClient | None = None
    try:
        client, paths, _ = make_client(args, root_dir, "turn-interrupt")
        client.ensure_initialized()
        result = client.interrupt_turn(args.thread_id, args.turn_id, timeout=args.timeout)
        print_payload({"ok": True, "result": result, "paths": {"task_dir": str(paths.task_dir)}})
        return 0
    finally:
        if client is not None:
            client.close()


def cmd_simple_request(args: argparse.Namespace) -> int:
    method = args.method_name
    params = json.loads(args.params) if getattr(args, "params", None) else {}
    root_dir = Path(args.root).resolve()
    client: AppServerClient | None = None
    try:
        client, paths, _ = make_client(args, root_dir, method.replace("/", "-"))
        client.ensure_initialized()
        result = client.request(method, params, timeout=args.timeout)
        print_payload({"ok": True, "result": result, "paths": {"task_dir": str(paths.task_dir)}})
        return 0
    finally:
        if client is not None:
            client.close()


def add_common(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--root", default=str(Path(__file__).resolve().parent.parent))
    parser.add_argument("--codex-bin", default=os.environ.get("CODEX_BIN", "codex"))
    parser.add_argument("--model")
    parser.add_argument("--approval-policy")
    parser.add_argument("--sandbox-mode")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Generic Codex App Server client CLI")
    sub = parser.add_subparsers(dest="command", required=True)

    schema = sub.add_parser("schema", help="Generate official app-server JSON schemas")
    add_common(schema)
    schema.add_argument("--out")
    schema.add_argument("--experimental", action="store_true", default=True)
    schema.set_defaults(func=cmd_schema)

    methods = sub.add_parser("methods", help="Print client/server method index from generated schemas")
    add_common(methods)
    methods.set_defaults(func=cmd_methods)

    validate = sub.add_parser("validate-method", help="Check whether a method exists in the generated protocol schema")
    add_common(validate)
    validate.add_argument("--direction", choices=("client", "server"), default="client")
    validate.add_argument("method")
    validate.set_defaults(func=cmd_validate_method)

    doctor = sub.add_parser("doctor", help="Run protocol smoke checks")
    add_common(doctor)
    doctor.set_defaults(func=cmd_doctor)

    request = sub.add_parser("request", help="Send a raw JSON-RPC request after initialize")
    add_common(request)
    request.add_argument("method")
    request.add_argument("--params", default="{}")
    request.add_argument("--timeout", type=float, default=30.0)
    request.add_argument("--no-initialize", action="store_true")
    request.set_defaults(func=cmd_request)

    unix_request = sub.add_parser("unix-request", help="Send a raw JSON-RPC request to an existing unix:// app-server")
    unix_request.add_argument("--socket", required=True)
    unix_request.add_argument("method")
    unix_request.add_argument("--params", default="{}")
    unix_request.add_argument("--timeout", type=float, default=30.0)
    unix_request.add_argument("--no-initialize", action="store_true")
    unix_request.set_defaults(func=cmd_unix_request)

    ws_request = sub.add_parser("ws-request", help="Send a raw JSON-RPC request to an existing ws:// app-server")
    ws_request.add_argument("--url", required=True)
    ws_request.add_argument("method")
    ws_request.add_argument("--params", default="{}")
    ws_request.add_argument("--timeout", type=float, default=30.0)
    ws_request.add_argument("--authorization", help="Optional Authorization header value")
    ws_request.add_argument("--no-initialize", action="store_true")
    ws_request.set_defaults(func=cmd_ws_request)

    thread = sub.add_parser("thread", help="Thread operations")
    thread_sub = thread.add_subparsers(dest="thread_command", required=True)

    thread_start = thread_sub.add_parser("start")
    add_common(thread_start)
    thread_start.add_argument("--cwd")
    thread_start.add_argument("--service-name", default="apdv1_generic_appserver_client")
    thread_start.add_argument("--timeout", type=float, default=60.0)
    thread_start.set_defaults(func=cmd_thread_start)

    thread_list = thread_sub.add_parser("list")
    add_common(thread_list)
    thread_list.add_argument("--timeout", type=float, default=30.0)
    thread_list.set_defaults(func=cmd_thread_list)

    thread_read = thread_sub.add_parser("read")
    add_common(thread_read)
    thread_read.add_argument("--thread-id", required=True)
    thread_read.add_argument("--timeout", type=float, default=30.0)
    thread_read.set_defaults(func=cmd_thread_read)

    thread_unsub = thread_sub.add_parser("unsubscribe")
    add_common(thread_unsub)
    thread_unsub.add_argument("--thread-id", required=True)
    thread_unsub.add_argument("--timeout", type=float, default=30.0)
    thread_unsub.set_defaults(func=cmd_thread_unsubscribe)

    turn = sub.add_parser("turn", help="Turn operations")
    turn_sub = turn.add_subparsers(dest="turn_command", required=True)

    turn_start = turn_sub.add_parser("start")
    add_common(turn_start)
    turn_start.add_argument("--thread-id")
    turn_start.add_argument("--cwd")
    turn_start.add_argument("--service-name", default="apdv1_generic_appserver_client")
    turn_start.add_argument("--text")
    turn_start.add_argument("--prompt-file")
    turn_start.add_argument("--wait", action="store_true")
    turn_start.add_argument("--wait-timeout", type=float, default=600.0)
    turn_start.add_argument("--timeout", type=float, default=60.0)
    turn_start.set_defaults(func=cmd_turn_start)

    turn_interrupt = turn_sub.add_parser("interrupt")
    add_common(turn_interrupt)
    turn_interrupt.add_argument("--thread-id", required=True)
    turn_interrupt.add_argument("--turn-id", required=True)
    turn_interrupt.add_argument("--timeout", type=float, default=10.0)
    turn_interrupt.set_defaults(func=cmd_turn_interrupt)

    model = sub.add_parser("model", help="Model operations")
    model_sub = model.add_subparsers(dest="model_command", required=True)
    model_list = model_sub.add_parser("list")
    add_common(model_list)
    model_list.add_argument("--timeout", type=float, default=30.0)
    model_list.set_defaults(func=cmd_simple_request, method_name="model/list", params="{}")

    account = sub.add_parser("account", help="Account operations")
    account_sub = account.add_subparsers(dest="account_command", required=True)
    account_read = account_sub.add_parser("read")
    add_common(account_read)
    account_read.add_argument("--timeout", type=float, default=30.0)
    account_read.set_defaults(func=cmd_simple_request, method_name="account/read", params="{}")
    account_limits = account_sub.add_parser("rate-limits")
    add_common(account_limits)
    account_limits.add_argument("--timeout", type=float, default=30.0)
    account_limits.set_defaults(func=cmd_simple_request, method_name="account/rateLimits/read", params="{}")

    config = sub.add_parser("config", help="Config operations")
    config_sub = config.add_subparsers(dest="config_command", required=True)
    config_read = config_sub.add_parser("read")
    add_common(config_read)
    config_read.add_argument("--timeout", type=float, default=30.0)
    config_read.set_defaults(func=cmd_simple_request, method_name="config/read", params="{}")

    skills = sub.add_parser("skills", help="Skills operations")
    skills_sub = skills.add_subparsers(dest="skills_command", required=True)
    skills_list = skills_sub.add_parser("list")
    add_common(skills_list)
    skills_list.add_argument("--timeout", type=float, default=30.0)
    skills_list.set_defaults(func=cmd_simple_request, method_name="skills/list", params="{}")

    return parser


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
