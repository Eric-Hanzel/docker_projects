import json
from pathlib import Path
from typing import Any, Literal

from mcp.server.fastmcp import FastMCP

from .client import Apdv1ApiClient
from .config import load_config


mcp = FastMCP("apdv1-deployer")
config = load_config()
client = Apdv1ApiClient(config)


def _json_text(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True)


def _normalize_target(target: dict[str, Any], *, require_url: bool = True) -> dict[str, Any]:
    normalized = dict(target)
    url = str(normalized.get("url", "")).strip()
    if require_url and not url:
        raise ValueError("target.url is required")
    if url:
        normalized["url"] = url

    delivery_mode = normalized.get("delivery_mode")
    if delivery_mode is not None:
        value = str(delivery_mode).strip()
        if value not in {"portable-deliverable", "local-run"}:
            raise ValueError("delivery_mode must be one of: portable-deliverable, local-run")
        normalized["delivery_mode"] = value

    portable_final_required = normalized.get("portable_final_required")
    if portable_final_required is not None and not isinstance(portable_final_required, bool):
        text = str(portable_final_required).strip().lower()
        if text in {"true", "1", "yes"}:
            normalized["portable_final_required"] = True
        elif text in {"false", "0", "no"}:
            normalized["portable_final_required"] = False
        else:
            raise ValueError("portable_final_required must be boolean")

    legacy_format = normalized.pop("delivery_format", None)
    if legacy_format is not None:
        value = str(legacy_format).strip().lower()
        if value in {"portable", "directory"}:
            normalized.setdefault("delivery_mode", "portable-deliverable")
            normalized.setdefault("portable_final_required", True)
        elif value == "image":
            normalized.setdefault("delivery_mode", "portable-deliverable")
            normalized.setdefault("portable_final_required", True)
            normalized["image_bundle"] = True
        else:
            raise ValueError("delivery_format is legacy; accepted values are: portable, directory, image")

    if normalized.get("image_bundle") is True:
        normalized.setdefault("delivery_mode", "portable-deliverable")
        normalized.setdefault("portable_final_required", True)

    if "delivery_mode" not in normalized:
        normalized["delivery_mode"] = "portable-deliverable"
        normalized.setdefault("portable_final_required", True)

    if normalized["delivery_mode"] == "portable-deliverable":
        normalized.setdefault("portable_final_required", True)
    elif normalized["delivery_mode"] == "local-run":
        normalized.setdefault("portable_final_required", False)

    return normalized


def _record_payload(record_response: dict[str, Any]) -> dict[str, Any]:
    record = record_response.get("record", record_response)
    return record if isinstance(record, dict) else {}


def _task_state(record: dict[str, Any]) -> dict[str, Any]:
    task_state = record.get("task_state")
    return task_state if isinstance(task_state, dict) else {}


def _record_url(record: dict[str, Any]) -> str:
    target = record.get("target")
    if isinstance(target, dict):
        return str(target.get("url", "")).strip()
    return ""


def _project_name(record: dict[str, Any]) -> str:
    state = _task_state(record)
    for key in ("project_name", "resolved_project_name"):
        value = str(state.get(key) or record.get(key) or "").strip()
        if value:
            return value
    return ""


def _apdv1_root_from_record(record: dict[str, Any]) -> Path | None:
    for key in ("run_dir",):
        value = str(record.get(key, "")).strip()
        if value:
            path = Path(value)
            try:
                return path.parents[2]
            except IndexError:
                pass
    state = _task_state(record)
    value = str(state.get("task_dir") or state.get("log_file") or "").strip()
    if value:
        path = Path(value)
        parts = path.parts
        if "app_server" in parts:
            idx = parts.index("app_server")
            return Path(*parts[:idx]) if idx > 0 else None
    return None


def _artifact_paths(record: dict[str, Any]) -> dict[str, Any]:
    root = _apdv1_root_from_record(record)
    project = _project_name(record)
    if root is None or not project:
        return {}
    names = []
    for name in (project, f"{project}-final", f"{project}-image-final"):
        if name not in names:
            names.append(name)
    cleanup = str(_task_state(record).get("cleanup_project_names") or record.get("cleanup_project_names") or "")
    for item in cleanup.split(","):
        name = item.strip()
        if name and name not in names:
            names.append(name)

    deliverables = []
    logs = []
    for name in names:
        deliverable = root / "Deliverable" / name
        log_dir = root / "DP_LOGS" / name
        if deliverable.exists():
            item: dict[str, str] = {"name": name, "path": str(deliverable)}
            quickstart = deliverable / "README_QUICKSTART.md"
            deploy_readme = deliverable / "README_DEPLOY.md"
            if quickstart.exists():
                item["quickstart"] = str(quickstart)
            if deploy_readme.exists():
                item["deploy_readme"] = str(deploy_readme)
            deliverables.append(item)
        if log_dir.exists():
            item = {"name": name, "path": str(log_dir)}
            summary = log_dir / "summary.md"
            deploy_log = log_dir / "deploy.log"
            verification_result = log_dir / "verification_result.json"
            audit_result = log_dir / "audit_result.json"
            errors_log = log_dir / "errors.log"
            if summary.exists():
                item["summary"] = str(summary)
            if deploy_log.exists():
                item["deploy_log"] = str(deploy_log)
            if verification_result.exists():
                item["verification_result"] = str(verification_result)
            if audit_result.exists():
                item["audit_result"] = str(audit_result)
            if errors_log.exists():
                item["errors_log"] = str(errors_log)
            logs.append(item)
    return {"project_name": project, "deliverables": deliverables, "logs": logs}


def _short_record(record: dict[str, Any]) -> dict[str, Any]:
    state = _task_state(record)
    return {
        "request_id": record.get("request_id"),
        "status": record.get("status"),
        "result": record.get("result"),
        "url": _record_url(record),
        "project_name": _project_name(record),
        "submitted_at": record.get("submitted_at"),
        "started_at": record.get("started_at") or state.get("started_at"),
        "completed_at": record.get("completed_at") or state.get("finished_at"),
        "run_dir": record.get("run_dir"),
    }


def _status_records(limit: int) -> dict[str, list[dict[str, Any]]]:
    status = client.status(limit=limit)
    return {
        "pending": list(status.get("pending") or []),
        "active": list(status.get("active") or []),
        "completed": list(status.get("recent_completed") or []),
        "failed": list(status.get("recent_failed") or []),
        "canceled": list(status.get("recent_canceled") or []),
    }


def _find_record(request_id: str | None = None, url: str | None = None, limit: int = 50) -> dict[str, Any] | None:
    if request_id:
        return _record_payload(client.request_record(request_id))
    wanted_url = (url or "").strip()
    groups = _status_records(limit)
    for section in ("active", "pending", "completed", "failed", "canceled"):
        for record in groups[section]:
            if wanted_url and _record_url(record) != wanted_url:
                continue
            return record
    return None


@mcp.tool()
def apdv1_health() -> dict[str, Any]:
    """Check whether the APDv1 HTTP API is reachable."""
    return client.health()


@mcp.tool()
def apdv1_deploy(url: str, extras: dict[str, Any] | None = None) -> dict[str, Any]:
    """Submit one APDv1 deployment target. Default delivery_mode is portable-deliverable."""
    target = _normalize_target({**dict(extras or {}), "url": url})
    clean_url = str(target.pop("url"))
    return client.deploy(clean_url, target)


@mcp.tool()
def apdv1_deploy_batch(targets: list[dict[str, Any]]) -> dict[str, Any]:
    """Submit multiple APDv1 deployment targets. Each target needs url; delivery_mode defaults to portable-deliverable."""
    normalized = [_normalize_target(target) for target in targets]
    return client.deploy_batch(normalized)


@mcp.tool()
def apdv1_tasks(limit: int = 20, url: str | None = None) -> dict[str, Any]:
    """Return a user-friendly task overview grouped by queue state."""
    groups = _status_records(limit)
    wanted_url = (url or "").strip()
    output: dict[str, Any] = {}
    for section, records in groups.items():
        items = []
        for record in records:
            if wanted_url and _record_url(record) != wanted_url:
                continue
            items.append(_short_record(record))
        output[section] = items
    output["hint"] = "Use apdv1_result with request_id for exact details, or omit request_id to inspect the latest visible task."
    return output


@mcp.tool()
def apdv1_result(
    request_id: str | None = None,
    url: str | None = None,
    include_last_message: bool = True,
    trace_tail_lines: int = 0,
) -> dict[str, Any]:
    """Return a user-friendly result summary. If request_id is omitted, the latest visible task is used."""
    record = _find_record(request_id=request_id, url=url, limit=50)
    if record is None:
        return {
            "ok": False,
            "error": "No matching APDv1 task was found.",
            "hint": "Call apdv1_tasks to list visible request ids, or pass a request_id/url.",
        }
    rid = str(record.get("request_id", "")).strip()
    if rid:
        record = _record_payload(client.request_record(rid))
    status = str(record.get("status", "")).strip()
    result: dict[str, Any] = {
        "ok": status in {"COMPLETED_SUCCESS", "COMPLETED_CONDITIONAL_SUCCESS"},
        "request_id": rid,
        "status": status,
        "result": record.get("result"),
        "url": _record_url(record),
        "project_name": _project_name(record),
        "submitted_at": record.get("submitted_at"),
        "started_at": record.get("started_at") or _task_state(record).get("started_at"),
        "completed_at": record.get("completed_at") or _task_state(record).get("finished_at"),
        "run_dir": record.get("run_dir"),
        "artifacts": _artifact_paths(record),
        "record": record,
    }
    if include_last_message and rid:
        try:
            result["last_message"] = client.tail(request_id=rid, file="last-message", lines=config.default_tail_lines)
        except Exception as exc:
            result["last_message_error"] = str(exc)
    if trace_tail_lines > 0 and rid:
        try:
            result["trace_tail"] = client.tail(request_id=rid, file="trace", lines=trace_tail_lines)
        except Exception as exc:
            result["trace_tail_error"] = str(exc)
    if not result["artifacts"]:
        result["artifact_hint"] = "Artifacts are usually created under apdv1/Deliverable/<project> and apdv1/DP_LOGS/<project> after the deployment reaches later phases."
    return result


@mcp.tool()
def apdv1_tail(
    request_id: str | None = None,
    file: Literal["trace", "log", "events", "last-message", "protocol", "record"] = "trace",
    lines: int | None = None,
) -> str:
    """Read APDv1 service logs or a request log file."""
    return client.tail(request_id=request_id, file=file, lines=lines or config.default_tail_lines)


@mcp.tool()
def apdv1_cancel(request_id: str) -> dict[str, Any]:
    """Cancel a pending request or request interruption of a matching active request."""
    return client.cancel(request_id)


@mcp.tool()
def apdv1_abort_current(confirm: bool = False) -> dict[str, Any]:
    """Abort the currently active APDv1 request. Requires confirm=true."""
    if not confirm:
        return {"ok": False, "error": "Set confirm=true to abort the active APDv1 request."}
    return client.abort_current()


@mcp.resource("apdv1://status")
def status_resource() -> str:
    """Current APDv1 status as JSON."""
    return _json_text(client.status())


@mcp.resource("apdv1://requests/{request_id}")
def request_resource(request_id: str) -> str:
    """One APDv1 request record as JSON."""
    return _json_text(client.request_record(request_id))


@mcp.resource("apdv1://logs/service")
def service_log_resource() -> str:
    """Recent APDv1 service log lines."""
    return client.tail(lines=config.default_tail_lines)


@mcp.resource("apdv1://logs/{request_id}/{file}")
def request_log_resource(request_id: str, file: str) -> str:
    """Recent APDv1 request log lines."""
    return client.tail(request_id=request_id, file=file, lines=config.default_tail_lines)


def main() -> None:
    mcp.run()


if __name__ == "__main__":
    main()
