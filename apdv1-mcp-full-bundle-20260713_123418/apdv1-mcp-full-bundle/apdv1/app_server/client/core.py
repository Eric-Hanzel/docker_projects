import json
import os
import queue
import subprocess
import threading
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .handlers import SafeDefaultServerRequestHandler, ServerRequestHandler


class AppServerError(RuntimeError):
    pass


@dataclass
class ClientPaths:
    log_file: Path
    events_file: Path
    trace_file: Path
    last_message_file: Path
    protocol_file: Path


@dataclass
class TaskPaths(ClientPaths):
    task_dir: Path
    prompt_file: Path
    session_file: Path
    thread_file: Path


def now_iso() -> str:
    return datetime.now(timezone.utc).astimezone().replace(microsecond=0).isoformat()


def atomic_write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = path.with_name(f".tmp.{os.getpid()}.{threading.get_ident()}.{path.name}")
    try:
        tmp_path.write_text(text, encoding="utf-8")
        os.replace(tmp_path, path)
    finally:
        try:
            tmp_path.unlink()
        except FileNotFoundError:
            pass


def append_jsonl(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(payload, ensure_ascii=False) + "\n")


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


class AppServerClient:
    """Reusable JSON-RPC client for the official `codex app-server` stdio transport.

    This class intentionally keeps runner-specific persistence optional and file-based.
    Higher-level services can wrap it for queues, HTTP APIs, or interactive UIs without
    duplicating app-server handshake and event handling.
    """

    def __init__(
        self,
        *,
        root_dir: Path,
        codex_bin: str,
        model: str,
        approval_policy: str,
        sandbox_mode: str,
        task_paths: ClientPaths,
        lifecycle_label: str,
        client_info: dict[str, Any] | None = None,
        auto_approval_decision: str | None = None,
        server_request_handler: ServerRequestHandler | None = None,
    ):
        self.root_dir = root_dir
        self.task_paths = task_paths
        self.lifecycle_label = lifecycle_label
        self.codex_bin = codex_bin
        self.model = model
        self.approval_policy = approval_policy
        self.sandbox_mode = sandbox_mode
        self.auto_approval_decision = auto_approval_decision
        self.server_request_handler = server_request_handler or SafeDefaultServerRequestHandler(
            approval_decision=auto_approval_decision
        )
        self.proc: subprocess.Popen[str] | None = None
        self.stdout_queue: queue.Queue[Any] = queue.Queue()
        self.stderr_lines: list[str] = []
        self.request_id = 0
        self.thread_id = ""
        self.turn_id = ""
        self.last_message_chunks: list[str] = []
        self.initialized = False
        self.protocol_stats: dict[str, Any] = self._new_protocol_stats()
        self.client_info = client_info or {
            "name": "apdv1_appserver_runner",
            "title": "APDv1 App Server Runner",
            "version": "0.1.0",
        }
        self._stdout_thread: threading.Thread | None = None
        self._stderr_thread: threading.Thread | None = None
        self._start_process()

    def _start_process(self) -> None:
        cmd = [
            self.codex_bin,
            "app-server",
            "-c",
            f'model="{self.model}"',
            "-c",
            f'approval_policy="{self.approval_policy}"',
            "-c",
            f'sandbox_mode="{self.sandbox_mode}"',
        ]
        self.proc = subprocess.Popen(
            cmd,
            cwd=self.root_dir,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            bufsize=1,
        )
        if self.proc.stdin is None or self.proc.stdout is None or self.proc.stderr is None:
            raise AppServerError("Failed to start codex app-server stdio transport")
        self.stdout_queue = queue.Queue()
        self.stderr_lines = []
        self.thread_id = ""
        self.turn_id = ""
        self.last_message_chunks = []
        self.initialized = False
        self.protocol_stats["process_pid"] = self.proc.pid
        self._write_protocol_summary()
        self._stdout_thread = threading.Thread(target=self._read_stdout, daemon=True)
        self._stderr_thread = threading.Thread(target=self._read_stderr, daemon=True)
        self._stdout_thread.start()
        self._stderr_thread.start()
        self._append_task_log(
            f"client_info: started app-server process pid={self.proc.pid} lifecycle={self.lifecycle_label}\n"
        )

    def set_task_paths(self, task_paths: ClientPaths) -> None:
        self.task_paths = task_paths
        self.thread_id = ""
        self.turn_id = ""
        self.last_message_chunks = []
        self.protocol_stats = self._new_protocol_stats()
        if self.proc is not None:
            self.protocol_stats["process_pid"] = self.proc.pid
        self._write_protocol_summary()

    def is_alive(self) -> bool:
        return self.proc is not None and self.proc.poll() is None

    def _append_task_log(self, text: str) -> None:
        self.task_paths.log_file.parent.mkdir(parents=True, exist_ok=True)
        with self.task_paths.log_file.open("a", encoding="utf-8") as handle:
            handle.write(text)

    def _read_stdout(self) -> None:
        assert self.proc is not None and self.proc.stdout is not None
        for raw_line in self.proc.stdout:
            line = raw_line.rstrip("\n")
            payload: dict[str, Any]
            try:
                payload = json.loads(line)
            except json.JSONDecodeError:
                payload = {"_raw": line, "_parse_error": True}
            self.stdout_queue.put(payload)
        self.stdout_queue.put(None)

    def _read_stderr(self) -> None:
        assert self.proc is not None and self.proc.stderr is not None
        for raw_line in self.proc.stderr:
            self.stderr_lines.append(raw_line)
            self._append_task_log(raw_line)

    def close(self) -> None:
        if self.proc is not None and self.proc.poll() is None:
            self.proc.terminate()
            try:
                self.proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                self.proc.kill()
                self.proc.wait(timeout=5)
        self.proc = None

    def restart(self, task_paths: ClientPaths) -> None:
        self.close()
        self.set_task_paths(task_paths)
        self._start_process()

    def ensure_initialized(self) -> dict[str, Any]:
        if not self.is_alive():
            raise AppServerError("app-server process is not running")
        if self.initialized:
            return {"reused": True}
        init_result = self.request(
            "initialize",
            {
                "clientInfo": self.client_info,
                "capabilities": {"experimentalApi": True},
            },
            timeout=60.0,
        )
        self.handle_message({"method": "client/info", "params": {"initialize": init_result}})
        self.send({"method": "initialized", "params": {}})
        self.initialized = True
        return init_result

    def send(self, payload: dict[str, Any]) -> None:
        assert self.proc is not None and self.proc.stdin is not None
        line = json.dumps(payload, ensure_ascii=False)
        self._append_task_log(f">>> {line}\n")
        self.proc.stdin.write(line + "\n")
        self.proc.stdin.flush()

    def request(self, method: str, params: dict[str, Any] | None = None, timeout: float = 30.0) -> dict[str, Any]:
        self.request_id += 1
        message = {"method": method, "id": self.request_id, "params": params or {}}
        self.send(message)
        deadline = time.monotonic() + timeout
        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise AppServerError(f"Timed out waiting for response to {method}")
            msg = self.recv(timeout=remaining)
            if msg is None:
                raise AppServerError(f"app-server exited while waiting for response to {method}")
            if self._is_server_request(msg):
                self.handle_message(msg)
                continue
            if msg.get("id") == self.request_id and "method" not in msg:
                self.handle_message(msg)
                if "error" in msg:
                    raise AppServerError(f"{method} failed: {summarize_json(msg['error'])}")
                return msg.get("result", {})
            self.handle_message(msg)

    def recv(self, timeout: float, *, allow_idle: bool = False) -> dict[str, Any] | None:
        try:
            msg = self.stdout_queue.get(timeout=timeout)
        except queue.Empty as exc:
            if allow_idle:
                return {"_idle": True}
            raise AppServerError("Timed out waiting for app-server output") from exc
        if msg is None:
            return None
        return msg

    def handle_message(self, msg: dict[str, Any]) -> None:
        event = {"ts": now_iso(), "message": msg}
        append_jsonl(self.task_paths.events_file, event)
        summary = self._message_summary(msg)
        if summary:
            with self.task_paths.trace_file.open("a", encoding="utf-8") as handle:
                handle.write(f"[{event['ts']}] {summary}\n")

        if "_raw" in msg:
            return
        if self._is_server_request(msg):
            self._handle_server_request(msg)
            return
        if msg.get("method") == "error":
            error_payload = msg.get("params", {}).get("error", msg.get("params", {}))
            self.protocol_stats.setdefault("errors", []).append({"ts": event["ts"], "error": error_payload})
            self._write_protocol_summary()
        if msg.get("method") == "thread/started" and not self.thread_id:
            self.thread_id = str(msg.get("params", {}).get("thread", {}).get("id", self.thread_id))
        if msg.get("method") == "turn/completed":
            params = msg.get("params", {})
            if str(params.get("threadId", "")) == self.thread_id:
                self.turn_id = str(params.get("turn", {}).get("id", self.turn_id))
            turn = params.get("turn", {})
            self.protocol_stats.setdefault("turn_statuses", []).append(
                {"ts": event["ts"], "turn_id": turn.get("id"), "status": turn.get("status"), "error": turn.get("error")}
            )
            self._write_protocol_summary()

        text = self._extract_delta_text(msg)
        if text:
            self.last_message_chunks.append(text)
            atomic_write_text(self.task_paths.last_message_file, "".join(self.last_message_chunks))
        if msg.get("method") == "item/completed":
            item = msg.get("params", {}).get("item", {})
            if item.get("type") == "agentMessage":
                full_text = extract_text(item)
                current_text = "".join(self.last_message_chunks)
                if full_text and full_text != current_text:
                    self.last_message_chunks = [full_text]
                    atomic_write_text(self.task_paths.last_message_file, full_text)

    def start_thread(self, params: dict[str, Any], timeout: float = 60.0) -> dict[str, Any]:
        return self.request("thread/start", params, timeout=timeout)

    def start_turn(self, thread_id: str, input_items: list[dict[str, Any]], timeout: float = 60.0) -> dict[str, Any]:
        return self.request("turn/start", {"threadId": thread_id, "input": input_items}, timeout=timeout)

    def interrupt_turn(self, thread_id: str, turn_id: str, timeout: float = 10.0) -> dict[str, Any]:
        return self.request("turn/interrupt", {"threadId": thread_id, "turnId": turn_id}, timeout=timeout)

    def _new_protocol_stats(self) -> dict[str, Any]:
        return {
            "started_at": now_iso(),
            "server_requests": 0,
            "auto_responses": 0,
            "unsupported_server_requests": 0,
            "server_request_methods": {},
            "errors": [],
            "turn_statuses": [],
            "last_updated_at": now_iso(),
        }

    def _write_protocol_summary(self) -> None:
        self.protocol_stats["last_updated_at"] = now_iso()
        atomic_write_text(
            self.task_paths.protocol_file,
            json.dumps(self.protocol_stats, ensure_ascii=False, indent=2) + "\n",
        )

    def _send_response(self, request_id: Any, result: Any) -> None:
        self.send({"id": request_id, "result": result})

    def _send_error(self, request_id: Any, code: int, message: str) -> None:
        self.send({"id": request_id, "error": {"code": code, "message": message}})

    def _is_server_request(self, msg: dict[str, Any]) -> bool:
        return "id" in msg and "method" in msg

    def _handle_server_request(self, msg: dict[str, Any]) -> None:
        method = str(msg.get("method", ""))
        request_id = msg.get("id")
        params = msg.get("params", {}) if isinstance(msg.get("params", {}), dict) else {}
        self.protocol_stats["server_requests"] = int(self.protocol_stats.get("server_requests", 0)) + 1
        methods = self.protocol_stats.setdefault("server_request_methods", {})
        methods[method] = int(methods.get(method, 0)) + 1

        action = self.server_request_handler.handle(method, params, self.client_info)
        if action.handled:
            if action.error is not None:
                self._send_error(request_id, int(action.error.get("code", -32603)), str(action.error.get("message", "")))
            else:
                self._send_response(request_id, action.result)
            self.protocol_stats["auto_responses"] = int(self.protocol_stats.get("auto_responses", 0)) + 1
            self._append_task_log(f"client_protocol: handled {method} id={request_id} note={action.note}\n")
            self._write_protocol_summary()
            return

        self._send_error(request_id, -32601, f"Unsupported app-server server request: {method}")
        self.protocol_stats["unsupported_server_requests"] = int(
            self.protocol_stats.get("unsupported_server_requests", 0)
        ) + 1
        self._append_task_log(f"client_protocol: rejected unsupported server request {method} id={request_id}\n")
        self._write_protocol_summary()

    def _extract_delta_text(self, msg: dict[str, Any]) -> str:
        method = msg.get("method")
        params = msg.get("params", {})
        if method == "item/agentMessage/delta":
            return extract_text(params)
        return ""

    def _message_summary(self, msg: dict[str, Any]) -> str:
        if "_raw" in msg:
            return f"raw {summarize_json(msg.get('_raw'))}"
        if "id" in msg and "method" in msg:
            return f"server_request#{msg['id']} {msg.get('method')} {summarize_json(msg.get('params', {}))}"
        if "id" in msg:
            if "error" in msg:
                return f"response#{msg['id']} error {summarize_json(msg['error'])}"
            result = msg.get("result", {})
            keys = ",".join(sorted(result.keys())[:6]) if isinstance(result, dict) else ""
            suffix = f" {keys}" if keys else ""
            return f"response#{msg['id']}{suffix}"

        method = str(msg.get("method", "notify"))
        params = msg.get("params", {})
        if method == "item/agentMessage/delta":
            text = extract_text(params)
            if text:
                return f"{method} {summarize_json(text)}"
        if method == "item/started":
            item = params.get("item", {})
            return f"{method} type={item.get('type', 'unknown')}"
        if method == "item/completed":
            item = params.get("item", {})
            suffix = f"type={item.get('type', 'unknown')} status={item.get('status', '')}".strip()
            return f"{method} {suffix}".strip()
        if method == "turn/completed":
            turn = params.get("turn", {})
            return f"{method} status={turn.get('status', '')}".strip()
        return f"{method} {summarize_json(params)}".strip()
