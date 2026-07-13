#!/usr/bin/env python3
import argparse
import json
import os
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

from cli import cmd_doctor, make_client, parse_config


def json_response(handler: BaseHTTPRequestHandler, status: int, payload: dict[str, Any]) -> None:
    body = json.dumps(payload, ensure_ascii=False, indent=2).encode("utf-8")
    handler.send_response(status)
    handler.send_header("Content-Type", "application/json; charset=utf-8")
    handler.send_header("Content-Length", str(len(body)))
    handler.end_headers()
    handler.wfile.write(body)


def read_json(handler: BaseHTTPRequestHandler) -> dict[str, Any]:
    size = int(handler.headers.get("Content-Length", "0"))
    if size <= 0:
        return {}
    return json.loads(handler.rfile.read(size).decode("utf-8"))


class AppServerGateway:
    def __init__(self, args: argparse.Namespace):
        self.args = args
        self.root_dir = Path(args.root).resolve()

    def make_handler(self) -> type[BaseHTTPRequestHandler]:
        gateway = self

        class Handler(BaseHTTPRequestHandler):
            server_version = "APDv1AppServerGateway/0.1"

            def log_message(self, fmt: str, *args: Any) -> None:
                if gateway.args.quiet:
                    return
                super().log_message(fmt, *args)

            def do_GET(self) -> None:
                if self.path == "/healthz":
                    json_response(self, 200, {"ok": True, "status": "healthy"})
                    return
                if self.path == "/config":
                    config = parse_config(gateway.root_dir)
                    json_response(
                        self,
                        200,
                        {
                            "ok": True,
                            "model": config.get("model", "gpt-5.4"),
                            "approval_policy": config.get("approval_policy", "never"),
                            "sandbox_mode": config.get("sandbox_mode", "danger-full-access"),
                        },
                    )
                    return
                json_response(self, 404, {"ok": False, "error": "not_found"})

            def do_POST(self) -> None:
                try:
                    if self.path == "/request":
                        payload = read_json(self)
                        result = gateway.raw_request(payload)
                        json_response(self, 200, result)
                        return
                    if self.path == "/turn/start":
                        payload = read_json(self)
                        result = gateway.turn_start(payload)
                        json_response(self, 200, result)
                        return
                    json_response(self, 404, {"ok": False, "error": "not_found"})
                except Exception as exc:
                    json_response(self, 500, {"ok": False, "error": str(exc), "type": exc.__class__.__name__})

        return Handler

    def _client_args(self) -> argparse.Namespace:
        return argparse.Namespace(
            root=str(self.root_dir),
            codex_bin=self.args.codex_bin,
            model=self.args.model,
            approval_policy=self.args.approval_policy,
            sandbox_mode=self.args.sandbox_mode,
        )

    def raw_request(self, payload: dict[str, Any]) -> dict[str, Any]:
        method = str(payload.get("method", "")).strip()
        if not method:
            raise ValueError("method is required")
        params = payload.get("params", {})
        if not isinstance(params, dict):
            raise ValueError("params must be an object")
        client = None
        try:
            client, paths, _ = make_client(self._client_args(), self.root_dir, "daemon-request")
            client.ensure_initialized()
            result = client.request(method, params, timeout=float(payload.get("timeout", 30)))
            return {"ok": True, "result": result, "paths": {"task_dir": str(paths.task_dir)}}
        finally:
            if client is not None:
                client.close()

    def turn_start(self, payload: dict[str, Any]) -> dict[str, Any]:
        text = str(payload.get("text", ""))
        if not text:
            raise ValueError("text is required")
        client = None
        try:
            client, paths, resolved = make_client(self._client_args(), self.root_dir, "daemon-turn")
            client.ensure_initialized()
            thread_id = str(payload.get("thread_id", "")).strip()
            if not thread_id:
                thread_result = client.start_thread(
                    {
                        "model": resolved["model"],
                        "cwd": str(self.root_dir),
                        "approvalPolicy": resolved["approval_policy"],
                        "serviceName": "apdv1_appserver_http_gateway",
                    },
                    timeout=float(payload.get("timeout", 60)),
                )
                thread_id = str(thread_result.get("thread", {}).get("id", ""))
            turn_result = client.start_turn(thread_id, [{"type": "text", "text": text}], timeout=float(payload.get("timeout", 60)))
            return {"ok": True, "thread_id": thread_id, "result": turn_result, "paths": {"task_dir": str(paths.task_dir)}}
        finally:
            if client is not None:
                client.close()


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Generic HTTP gateway for Codex App Server stdio client")
    parser.add_argument("--root", default=str(Path(__file__).resolve().parent.parent))
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=int(os.environ.get("APP_SERVER_GATEWAY_PORT", "18081")))
    parser.add_argument("--codex-bin", default=os.environ.get("CODEX_BIN", "codex"))
    parser.add_argument("--model")
    parser.add_argument("--approval-policy")
    parser.add_argument("--sandbox-mode")
    parser.add_argument("--quiet", action="store_true")
    return parser


def main() -> int:
    args = build_parser().parse_args()
    gateway = AppServerGateway(args)
    server = ThreadingHTTPServer((args.host, args.port), gateway.make_handler())
    print(f"app_server_gateway listening on http://{args.host}:{args.port}", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
