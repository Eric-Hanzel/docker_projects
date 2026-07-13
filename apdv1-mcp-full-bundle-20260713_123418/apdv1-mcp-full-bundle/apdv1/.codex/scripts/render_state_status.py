#!/usr/bin/env python3
"""Render a human-readable summary of APDv1 live state."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
STATE = ROOT / ".codex" / "state"


def load_json(path: Path) -> dict:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}
    return data if isinstance(data, dict) else {}


def main() -> int:
    task = load_json(STATE / "task_state.json")
    app_task = load_json(STATE / "app_server_task_state.json")
    service = load_json(STATE / "app_server_service_state.json")
    registry = load_json(STATE / "port_registry.json")

    queue_root = STATE / "app_server_queue"
    queue = {
        name: len(list((queue_root / name).glob("*.json"))) if (queue_root / name).exists() else 0
        for name in ["pending", "active", "completed", "failed", "canceled"]
    }

    lines = [
        "# APDv1 State Status",
        "",
        f"Updated: {datetime.now(timezone.utc).astimezone().replace(microsecond=0).isoformat()}",
        "",
        "## Main Batch Task",
        "",
        f"- Status: `{task.get('status', 'unknown')}`",
        f"- Project: `{task.get('project_name', '')}`",
        f"- Message: {task.get('message', '')}",
        f"- Updated at: `{task.get('updated_at', '')}`",
        "",
        "## App Server",
        "",
        f"- Service status: `{service.get('status', 'unknown')}`",
        f"- Service PID: `{service.get('pid', '')}`",
        f"- Current request: `{service.get('current_request_id', '')}`",
        f"- Task status: `{app_task.get('status', 'unknown')}`",
        f"- Task message: {app_task.get('message', '')}",
        "",
        "## Queue",
        "",
    ]
    lines.extend(f"- {name}: `{count}`" for name, count in queue.items())

    lines.extend(["", "## Ports", ""])
    claims = registry.get("claims", [])
    claims = claims if isinstance(claims, list) else []
    lines.append(f"- Active claims: `{len(claims)}`")
    for claim in claims[:10]:
        if isinstance(claim, dict):
            lines.append(
                f"  - `{claim.get('project', '')}` port `{claim.get('port', '')}` status `{claim.get('status', '')}`"
            )
    observed = registry.get("observed", {})
    if isinstance(observed, dict):
        lines.append(f"- Observed docker ports: `{observed.get('docker_published', [])}`")
        lines.append(f"- Observed listening ports: `{observed.get('host_listening', [])}`")

    lines.extend(
        [
            "",
            "## File Map",
            "",
            "- `task_state.json`: current shell batch task state",
            "- `task_history.jsonl`: append-only shell batch history",
            "- `app_server_service_state.json`: app-server daemon/service state",
            "- `app_server_service_history.jsonl`: append-only app-server service history",
            "- `app_server_task_state.json`: current app-server task state",
            "- `app_server_task_history.jsonl`: append-only app-server task history",
            "- `app_server_service.log`: app-server service log",
            "- `app_server_runner.nohup.log`: nohup log for app-server runner",
            "- `port_registry.json`: shared port coordination state",
            "- `*.lock`: runner lock files",
            "- `app_server_queue/`: app-server request queue directories",
            "",
            "Historical archives and bulky reports are stored under `.codex-backups/`.",
        ]
    )
    (STATE / "STATUS.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(STATE / "STATUS.md")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
