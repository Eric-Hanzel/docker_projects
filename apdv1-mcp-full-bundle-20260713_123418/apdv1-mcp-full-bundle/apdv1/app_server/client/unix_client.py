import base64
import hashlib
import json
import os
import socket
import struct
import time
from pathlib import Path
from typing import Any

from .core import AppServerError


class UnixSocketAppServerClient:
    """JSON-RPC client for `codex app-server --listen unix://PATH`.

    Codex's unix listener uses WebSocket framing over the Unix domain socket, not
    raw JSONL. This client performs the HTTP upgrade handshake and then exchanges
    masked client text frames.
    """

    def __init__(self, socket_path: Path):
        self.socket_path = socket_path
        self.sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        self.sock.connect(str(socket_path))
        self.request_id = 0
        self._handshake()

    def _handshake(self) -> None:
        key = base64.b64encode(os.urandom(16)).decode("ascii")
        raw = (
            "GET / HTTP/1.1\r\n"
            "Host: localhost\r\n"
            "Upgrade: websocket\r\n"
            "Connection: Upgrade\r\n"
            f"Sec-WebSocket-Key: {key}\r\n"
            "Sec-WebSocket-Version: 13\r\n"
            "\r\n"
        )
        self.sock.sendall(raw.encode("ascii"))
        response = b""
        while b"\r\n\r\n" not in response:
            chunk = self.sock.recv(4096)
            if not chunk:
                raise AppServerError("Unix WebSocket handshake failed: connection closed")
            response += chunk
        header_text = response.decode("iso-8859-1", errors="replace")
        if " 101 " not in header_text.split("\r\n", 1)[0]:
            raise AppServerError(f"Unix WebSocket handshake failed: {header_text.splitlines()[0]}")
        expected = base64.b64encode(
            hashlib.sha1((key + "258EAFA5-E914-47DA-95CA-C5AB0DC85B11").encode()).digest()
        ).decode()
        if expected.lower() not in header_text.lower():
            raise AppServerError("Unix WebSocket handshake failed: accept key mismatch")

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
                raise AppServerError("Unix WebSocket connection closed")
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
                raise AppServerError(f"unix app-server exited while waiting for response to {method}")
            if msg.get("id") == request_id and "method" not in msg:
                if "error" in msg:
                    raise AppServerError(f"{method} failed: {msg['error']}")
                return msg.get("result", {})
