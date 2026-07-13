import base64
import hashlib
import json
import os
import socket
import struct
import time
from typing import Any
from urllib.parse import urlparse

from .core import AppServerError


class WebSocketAppServerClient:
    """Minimal ws:// JSON-RPC client for app-server endpoints.

    Supports unencrypted ws:// text frames, enough for localhost development and
    smoke testing. Auth headers can be passed for capability-token or bearer setups.
    """

    def __init__(self, url: str, headers: dict[str, str] | None = None):
        parsed = urlparse(url)
        if parsed.scheme != "ws":
            raise ValueError("Only ws:// URLs are supported")
        self.host = parsed.hostname or "127.0.0.1"
        self.port = parsed.port or 80
        self.path = parsed.path or "/"
        if parsed.query:
            self.path += "?" + parsed.query
        self.sock = socket.create_connection((self.host, self.port), timeout=10)
        self.request_id = 0
        self._handshake(headers or {})

    def _handshake(self, headers: dict[str, str]) -> None:
        key = base64.b64encode(os.urandom(16)).decode("ascii")
        request_headers = {
            "Host": f"{self.host}:{self.port}",
            "Upgrade": "websocket",
            "Connection": "Upgrade",
            "Sec-WebSocket-Key": key,
            "Sec-WebSocket-Version": "13",
            **headers,
        }
        raw = f"GET {self.path} HTTP/1.1\r\n" + "".join(f"{k}: {v}\r\n" for k, v in request_headers.items()) + "\r\n"
        self.sock.sendall(raw.encode("ascii"))
        response = b""
        while b"\r\n\r\n" not in response:
            chunk = self.sock.recv(4096)
            if not chunk:
                raise AppServerError("WebSocket handshake failed: connection closed")
            response += chunk
        header_text = response.decode("iso-8859-1", errors="replace")
        if " 101 " not in header_text.split("\r\n", 1)[0]:
            raise AppServerError(f"WebSocket handshake failed: {header_text.splitlines()[0]}")
        expected = base64.b64encode(hashlib.sha1((key + "258EAFA5-E914-47DA-95CA-C5AB0DC85B11").encode()).digest()).decode()
        if expected.lower() not in header_text.lower():
            raise AppServerError("WebSocket handshake failed: accept key mismatch")

    def close(self) -> None:
        try:
            self.sock.close()
        except OSError:
            pass

    def _send_frame(self, text: str) -> None:
        payload = text.encode("utf-8")
        header = bytearray([0x81])
        length = len(payload)
        if length < 126:
            header.append(0x80 | length)
        elif length < 65536:
            header.append(0x80 | 126)
            header.extend(struct.pack("!H", length))
        else:
            header.append(0x80 | 127)
            header.extend(struct.pack("!Q", length))
        mask = os.urandom(4)
        masked = bytes(byte ^ mask[i % 4] for i, byte in enumerate(payload))
        self.sock.sendall(bytes(header) + mask + masked)

    def _recv_exact(self, size: int) -> bytes:
        data = b""
        while len(data) < size:
            chunk = self.sock.recv(size - len(data))
            if not chunk:
                raise AppServerError("WebSocket connection closed")
            data += chunk
        return data

    def _recv_frame(self, timeout: float) -> str | None:
        self.sock.settimeout(timeout)
        first, second = self._recv_exact(2)
        opcode = first & 0x0F
        masked = bool(second & 0x80)
        length = second & 0x7F
        if length == 126:
            length = struct.unpack("!H", self._recv_exact(2))[0]
        elif length == 127:
            length = struct.unpack("!Q", self._recv_exact(8))[0]
        mask = self._recv_exact(4) if masked else b""
        payload = self._recv_exact(length)
        if masked:
            payload = bytes(byte ^ mask[i % 4] for i, byte in enumerate(payload))
        if opcode == 0x8:
            return None
        if opcode != 0x1:
            return ""
        return payload.decode("utf-8")

    def send(self, payload: dict[str, Any]) -> None:
        self._send_frame(json.dumps(payload, ensure_ascii=False))

    def recv(self, timeout: float = 30.0) -> dict[str, Any] | None:
        text = self._recv_frame(timeout)
        if text is None:
            return None
        if not text:
            return {}
        return json.loads(text)

    def request(self, method: str, params: dict[str, Any] | None = None, timeout: float = 30.0) -> dict[str, Any]:
        self.request_id += 1
        request_id = self.request_id
        self.send({"id": request_id, "method": method, "params": params or {}})
        deadline = time.monotonic() + timeout
        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise AppServerError(f"Timed out waiting for response to {method}")
            msg = self.recv(timeout=remaining)
            if msg is None:
                raise AppServerError(f"ws app-server exited while waiting for response to {method}")
            if msg.get("id") == request_id and "method" not in msg:
                if "error" in msg:
                    raise AppServerError(f"{method} failed: {msg['error']}")
                return msg.get("result", {})
