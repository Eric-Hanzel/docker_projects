import os
from dataclasses import dataclass


@dataclass(frozen=True)
class Config:
    api_base: str = "http://127.0.0.1:18084"
    timeout_seconds: float = 30.0
    default_tail_lines: int = 80


def load_config() -> Config:
    return Config(
        api_base=os.environ.get("APDV1_API_BASE", "http://127.0.0.1:18084").rstrip("/"),
        timeout_seconds=float(os.environ.get("APDV1_MCP_REQUEST_TIMEOUT", "30")),
        default_tail_lines=int(os.environ.get("APDV1_MCP_DEFAULT_TAIL_LINES", "80")),
    )
