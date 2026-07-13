#!/usr/bin/env python3
import argparse
import json
import os
import signal
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

import runner


def json_response(handler: BaseHTTPRequestHandler, status: int, payload: dict[str, Any]) -> None:
    body = json.dumps(payload, ensure_ascii=False, indent=2).encode("utf-8")
    handler.send_response(status)
    handler.send_header("Content-Type", "application/json; charset=utf-8")
    handler.send_header("Content-Length", str(len(body)))
    handler.end_headers()
    handler.wfile.write(body)


def text_response(handler: BaseHTTPRequestHandler, status: int, text: str) -> None:
    body = text.encode("utf-8")
    handler.send_response(status)
    handler.send_header("Content-Type", "text/plain; charset=utf-8")
    handler.send_header("Content-Length", str(len(body)))
    handler.end_headers()
    handler.wfile.write(body)


def read_json(handler: BaseHTTPRequestHandler) -> dict[str, Any]:
    size = int(handler.headers.get("Content-Length", "0"))
    if size <= 0:
        return {}
    return json.loads(handler.rfile.read(size).decode("utf-8"))


def service_running(service_state: dict[str, Any]) -> bool:
    pid = service_state.get("pid")
    if not isinstance(pid, int):
        return False
    try:
        os.kill(pid, 0)
    except OSError:
        return False
    return str(service_state.get("status", "")) != "STOPPED"


class DeployApi:
    def __init__(self, args: argparse.Namespace):
        self.args = args
        self.root_dir = Path(args.root).resolve()
        self.service_paths = runner.build_service_paths(self.root_dir)
        runner.ensure_service_dirs(self.service_paths)

    def status_payload(self, limit: int = 10) -> dict[str, Any]:
        return {
            "service_state": runner.load_json(self.service_paths.service_state_file),
            "service_running": service_running(runner.load_json(self.service_paths.service_state_file)),
            "queue_counts": runner.queue_counts(self.service_paths),
            "pending": runner.list_queue_records(self.service_paths.queue_pending_dir, limit=limit),
            "active": runner.list_queue_records(self.service_paths.queue_active_dir, limit=limit),
            "recent_failed": runner.list_queue_records(self.service_paths.queue_failed_dir, limit=limit),
            "recent_completed": runner.list_queue_records(self.service_paths.queue_completed_dir, limit=limit),
            "recent_canceled": runner.list_queue_records(self.service_paths.queue_canceled_dir, limit=limit),
        }

    def submit(self, payload: dict[str, Any]) -> dict[str, Any]:
        if "target" in payload:
            target = payload["target"]
            if not isinstance(target, dict):
                raise ValueError("target must be an object")
            targets = [target]
        elif "targets" in payload:
            targets = payload["targets"]
            if not isinstance(targets, list) or not all(isinstance(item, dict) for item in targets):
                raise ValueError("targets must be a list of objects")
        else:
            url = payload.get("url")
            if not isinstance(url, str) or not url.strip():
                raise ValueError("submit requires url, target, or targets")
            target = dict(payload.get("extras", {})) if isinstance(payload.get("extras"), dict) else {}
            target["url"] = url
            targets = [target]

        source = str(payload.get("source", "http"))
        request_ids = runner.enqueue_targets(self.root_dir, self.service_paths, targets, source=source)
        return {"ok": True, "request_ids": request_ids, "queue_counts": runner.queue_counts(self.service_paths)}

    def cancel(self, request_id: str, source: str = "http") -> dict[str, Any]:
        path, record = runner.find_request_record(self.service_paths, request_id)
        if path is None or record is None:
            raise KeyError(f"Unknown request_id: {request_id}")
        status = str(record.get("status", ""))
        if status == "pending":
            dest = runner.move_queue_record(
                path,
                self.service_paths.queue_canceled_dir,
                status="CANCELLED",
                extra={"result": "canceled", "canceled_at": runner.now_iso(), "cancel_source": source},
            )
            runner.service_log(self.service_paths, f"http canceled pending request {request_id} source={source}")
            return {"ok": True, "action": "canceled", "request_id": request_id, "record_path": str(dest)}
        if status == "active":
            runner.write_service_control(
                self.service_paths,
                {"action": "abort_current", "request_id": request_id, "created_at": runner.now_iso(), "source": source},
            )
            runner.service_log(self.service_paths, f"http requested abort for active request {request_id} source={source}")
            return {"ok": True, "action": "abort_requested", "request_id": request_id}
        return {"ok": True, "action": "already_terminal", "request_id": request_id, "status": status}

    def abort_current(self, source: str = "http") -> dict[str, Any]:
        service_state = runner.load_json(self.service_paths.service_state_file)
        current_request_id = str(service_state.get("current_request_id", "")).strip()
        if not current_request_id:
            raise ValueError("No active request to abort")
        runner.write_service_control(
            self.service_paths,
            {"action": "abort_current", "request_id": current_request_id, "created_at": runner.now_iso(), "source": source},
        )
        runner.service_log(self.service_paths, f"http requested abort-current for request {current_request_id}")
        return {"ok": True, "request_id": current_request_id, "action": "abort_requested"}

    def stop_service(self, source: str = "http") -> dict[str, Any]:
        service_state = runner.load_json(self.service_paths.service_state_file)
        pid = service_state.get("pid")
        if not isinstance(pid, int):
            raise ValueError("Service pid not available; service may not be running")
        runner.write_service_control(
            self.service_paths,
            {
                "action": "stop_service",
                "request_id": str(service_state.get("current_request_id", "")).strip() or None,
                "created_at": runner.now_iso(),
                "source": source,
            },
        )
        os.kill(pid, signal.SIGTERM)
        runner.service_log(self.service_paths, f"http requested service stop pid={pid} source={source}")
        return {"ok": True, "pid": pid, "action": "stop_requested"}

    def record(self, request_id: str) -> dict[str, Any]:
        path, record = runner.find_request_record(self.service_paths, request_id)
        if path is None or record is None:
            raise KeyError(f"Unknown request_id: {request_id}")
        service_state = runner.load_json(self.service_paths.service_state_file)
        if (
            not record.get("run_dir")
            and str(record.get("status", "")) == "active"
            and str(service_state.get("current_request_id", "")) == request_id
        ):
            run_dir = str(service_state.get("current_run_dir", "")).strip()
            if run_dir:
                record["run_dir"] = run_dir
        record["_path"] = str(path)
        return {"ok": True, "record": record}

    def tail(self, request_id: str | None, file_name: str, lines: int) -> str:
        if request_id is None:
            return runner.tail_file(self.service_paths.service_log_file, lines)
        path, record = runner.find_request_record(self.service_paths, request_id)
        if path is None or record is None:
            raise KeyError(f"Unknown request_id: {request_id}")
        if file_name == "record":
            return json.dumps(record, ensure_ascii=False, indent=2)
        run_dir = record.get("run_dir")
        if not run_dir:
            service_state = runner.load_json(self.service_paths.service_state_file)
            if str(record.get("status", "")) == "active" and str(service_state.get("current_request_id", "")) == request_id:
                run_dir = str(service_state.get("current_run_dir", "")).strip()
        if not run_dir:
            return json.dumps(record, ensure_ascii=False, indent=2)
        task_dir = Path(run_dir) / "task-001"
        file_map = {
            "log": task_dir / "codex.log",
            "trace": task_dir / "trace.txt",
            "events": task_dir / "events.jsonl",
            "last-message": task_dir / "last_message.txt",
            "protocol": task_dir / "protocol.json",
        }
        if file_name not in file_map:
            raise ValueError(f"Unsupported file: {file_name}")
        return runner.tail_file(file_map[file_name], lines)

    def make_handler(self) -> type[BaseHTTPRequestHandler]:
        api = self

        class Handler(BaseHTTPRequestHandler):
            server_version = "APDv1DeployApi/0.1"

            def log_message(self, fmt: str, *args: Any) -> None:
                if api.args.quiet:
                    return
                super().log_message(fmt, *args)

            def do_GET(self) -> None:
                try:
                    path, _, query = self.path.partition("?")
                    params = dict(item.split("=", 1) if "=" in item else (item, "") for item in query.split("&") if item)
                    if path == "/healthz":
                        json_response(self, 200, {"ok": True, "service": "apdv1-deploy-api"})
                        return
                    if path == "/status":
                        json_response(self, 200, api.status_payload(limit=int(params.get("limit", "10"))))
                        return
                    if path.startswith("/requests/"):
                        parts = path.strip("/").split("/")
                        request_id = parts[1]
                        if len(parts) == 2:
                            json_response(self, 200, api.record(request_id))
                            return
                        if len(parts) == 3 and parts[2] == "tail":
                            text = api.tail(
                                request_id,
                                params.get("file", "trace"),
                                int(params.get("lines", "40")),
                            )
                            text_response(self, 200, text)
                            return
                    if path == "/logs":
                        text_response(self, 200, api.tail(None, "service", int(params.get("lines", "40"))))
                        return
                    json_response(self, 404, {"ok": False, "error": "not_found"})
                except Exception as exc:
                    json_response(self, 500, {"ok": False, "error": str(exc), "type": exc.__class__.__name__})

            def do_POST(self) -> None:
                try:
                    path = self.path.split("?", 1)[0]
                    payload = read_json(self)
                    if path == "/deploy":
                        json_response(self, 200, api.submit(payload))
                        return
                    if path.startswith("/requests/") and path.endswith("/cancel"):
                        request_id = path.strip("/").split("/")[1]
                        json_response(self, 200, api.cancel(request_id, source=str(payload.get("source", "http"))))
                        return
                    if path == "/abort-current":
                        json_response(self, 200, api.abort_current(source=str(payload.get("source", "http"))))
                        return
                    if path == "/stop":
                        json_response(self, 200, api.stop_service(source=str(payload.get("source", "http"))))
                        return
                    json_response(self, 404, {"ok": False, "error": "not_found"})
                except KeyError as exc:
                    json_response(self, 404, {"ok": False, "error": str(exc), "type": exc.__class__.__name__})
                except Exception as exc:
                    json_response(self, 500, {"ok": False, "error": str(exc), "type": exc.__class__.__name__})

        return Handler


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="HTTP API for APDv1 app-server deployment queue")
    parser.add_argument("--root", default=str(Path(__file__).resolve().parent.parent))
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=int(os.environ.get("APP_DEPLOY_API_PORT", "18084")))
    parser.add_argument("--quiet", action="store_true")
    return parser


def main() -> int:
    args = build_parser().parse_args()
    api = DeployApi(args)
    server = ThreadingHTTPServer((args.host, args.port), api.make_handler())
    print(f"apdv1 deploy api listening on http://{args.host}:{args.port}", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
