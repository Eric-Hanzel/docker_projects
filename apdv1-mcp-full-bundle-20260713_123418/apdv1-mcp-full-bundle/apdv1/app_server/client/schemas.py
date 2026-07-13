import json
import subprocess
from pathlib import Path
from typing import Any


def generate_schema(*, codex_bin: str, root_dir: Path, out_dir: Path, experimental: bool = True) -> dict[str, Any]:
    cmd = [codex_bin, "app-server", "generate-json-schema", "--out", str(out_dir)]
    if experimental:
        cmd.insert(3, "--experimental")
    result = subprocess.run(cmd, cwd=root_dir, capture_output=True, text=True, timeout=60, check=False)
    return {
        "ok": result.returncode == 0,
        "returncode": result.returncode,
        "stdout": result.stdout,
        "stderr": result.stderr,
        "out_dir": str(out_dir),
    }


def _methods_from_schema(path: Path) -> list[str]:
    data = json.loads(path.read_text(encoding="utf-8"))
    methods: list[str] = []
    for item in data.get("oneOf", []):
        enum_values = item.get("properties", {}).get("method", {}).get("enum", [])
        methods.extend(str(value) for value in enum_values)
    return methods


def read_method_index(schema_dir: Path) -> dict[str, list[str]]:
    return {
        "client_requests": _methods_from_schema(schema_dir / "ClientRequest.json"),
        "server_requests": _methods_from_schema(schema_dir / "ServerRequest.json"),
    }


def validate_method(methods: dict[str, list[str]], *, direction: str, method: str) -> dict[str, Any]:
    key = "client_requests" if direction == "client" else "server_requests"
    available = methods.get(key, [])
    return {
        "ok": method in available,
        "direction": direction,
        "method": method,
        "known_count": len(available),
    }
