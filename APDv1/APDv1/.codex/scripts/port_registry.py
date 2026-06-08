#!/usr/bin/env python3
"""Maintain a shared port registry for local deployment scripts."""

from __future__ import annotations

import argparse
import datetime as dt
import json
import pathlib
import re
import subprocess
import sys
from typing import Any

try:
    import tomllib  # Python 3.11+
except ModuleNotFoundError:  # pragma: no cover
    tomllib = None


def now_iso() -> str:
    return dt.datetime.now(dt.timezone.utc).astimezone().isoformat(timespec="seconds")


def find_repo_root(start: pathlib.Path) -> pathlib.Path:
    current = start.resolve()
    for candidate in [current, *current.parents]:
        if (candidate / ".codex").exists():
            return candidate
    return current


def load_codex_config(repo_root: pathlib.Path) -> dict[str, Any]:
    defaults: dict[str, Any] = {
        "enabled": True,
        "registry_file": ".codex/state/port_registry.json",
        "default_range_start": 18080,
        "default_range_end": 18999,
    }
    if tomllib is None:
        return defaults

    merged = dict(defaults)

    # Prefer the dedicated project file so Codex's official config schema stays clean.
    dedicated_file = repo_root / ".codex" / "port_registry.toml"
    if dedicated_file.exists():
        try:
            dedicated = tomllib.loads(dedicated_file.read_text(encoding="utf-8"))
        except Exception:
            dedicated = {}
        if isinstance(dedicated, dict):
            merged.update(dedicated)

    # Keep backward compatibility with older repos that still embed [port_registry] in config.toml.
    config_file = repo_root / ".codex" / "config.toml"
    if config_file.exists():
        try:
            parsed = tomllib.loads(config_file.read_text(encoding="utf-8"))
        except Exception:
            parsed = {}
        section = parsed.get("port_registry") or {}
        if isinstance(section, dict):
            merged.update(section)

    return merged


def resolve_registry_path(
    repo_root: pathlib.Path,
    config: dict[str, Any],
    explicit_path: str | None,
) -> pathlib.Path:
    if explicit_path:
        return pathlib.Path(explicit_path).expanduser().resolve()
    configured = str(config.get("registry_file", ".codex/state/port_registry.json"))
    configured_path = pathlib.Path(configured)
    if configured_path.is_absolute():
        return configured_path
    return (repo_root / configured_path).resolve()


def default_registry() -> dict[str, Any]:
    timestamp = now_iso()
    return {
        "version": 1,
        "updated_at": timestamp,
        "claims": [],
        "observed": {
            "updated_at": timestamp,
            "host_listening": [],
            "docker_published": [],
            "union": [],
        },
    }


def load_registry(path: pathlib.Path) -> dict[str, Any]:
    if not path.exists():
        return default_registry()
    try:
        loaded = json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:
        raise RuntimeError(f"failed to read registry {path}: {exc}") from exc
    if not isinstance(loaded, dict):
        raise RuntimeError(f"invalid registry format in {path}")
    base = default_registry()
    base.update(loaded)
    if not isinstance(base.get("claims"), list):
        base["claims"] = []
    if not isinstance(base.get("observed"), dict):
        base["observed"] = default_registry()["observed"]
    return base


def save_registry(path: pathlib.Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    data["updated_at"] = now_iso()
    data["claims"] = sorted(
        [
            claim
            for claim in data.get("claims", [])
            if isinstance(claim, dict) and isinstance(claim.get("port"), int)
        ],
        key=lambda item: (int(item["port"]), str(item.get("project", ""))),
    )
    temp_path = path.with_suffix(path.suffix + ".tmp")
    temp_path.write_text(
        json.dumps(data, ensure_ascii=True, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    temp_path.replace(path)


def run_command(argv: list[str]) -> str:
    try:
        completed = subprocess.run(
            argv,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            check=False,
        )
    except FileNotFoundError:
        return ""
    if completed.returncode != 0:
        return ""
    return completed.stdout


def parse_ss_ports(raw_output: str) -> set[int]:
    ports: set[int] = set()
    for line in raw_output.splitlines():
        line = line.strip()
        if not line or line.startswith("State"):
            continue
        parts = line.split()
        if len(parts) < 4:
            continue
        local_addr = parts[3]
        match = re.search(r":(\d+)$", local_addr)
        if not match:
            continue
        port = int(match.group(1))
        if 1 <= port <= 65535:
            ports.add(port)
    return ports


def parse_docker_ports(raw_output: str) -> set[int]:
    ports: set[int] = set()
    pattern = re.compile(
        r"(?:^|,\s*)(?:\[[0-9A-Fa-f:]+\]|::|:::|\*|[A-Za-z0-9_.-]+):(\d+)->"
    )
    for line in raw_output.splitlines():
        for matched in pattern.finditer(line):
            port = int(matched.group(1))
            if 1 <= port <= 65535:
                ports.add(port)
    return ports


def scan_observed_ports() -> tuple[set[int], set[int]]:
    host_ports = parse_ss_ports(run_command(["ss", "-ltn"]))
    docker_ports = parse_docker_ports(run_command(["docker", "ps", "--format", "{{.Ports}}"]))
    return host_ports, docker_ports


def refresh_observed(data: dict[str, Any]) -> set[int]:
    host_ports, docker_ports = scan_observed_ports()
    merged = sorted(host_ports | docker_ports)
    data["observed"] = {
        "updated_at": now_iso(),
        "host_listening": sorted(host_ports),
        "docker_published": sorted(docker_ports),
        "union": merged,
    }
    return set(merged)


def port_bound_by_compose_project(port: int, compose_project: str | None) -> bool:
    if not compose_project:
        return False
    output = run_command(
        [
            "docker",
            "ps",
            "--filter",
            f"label=com.docker.compose.project={compose_project}",
            "--format",
            "{{.Ports}}",
        ]
    )
    ports = parse_docker_ports(output)
    return port in ports


def claim_for_project(data: dict[str, Any], project: str, port: int) -> dict[str, Any] | None:
    for claim in data.get("claims", []):
        if not isinstance(claim, dict):
            continue
        if claim.get("project") == project and claim.get("port") == port:
            return claim
    return None


def claims_using_port(data: dict[str, Any], port: int, excluding_project: str | None = None) -> list[dict[str, Any]]:
    conflicts: list[dict[str, Any]] = []
    for claim in data.get("claims", []):
        if not isinstance(claim, dict):
            continue
        if claim.get("port") != port:
            continue
        if excluding_project and claim.get("project") == excluding_project:
            continue
        conflicts.append(claim)
    return conflicts


def ensure_valid_port(port: int) -> None:
    if port < 1 or port > 65535:
        raise SystemExit(f"invalid port: {port}")


def cmd_snapshot(args: argparse.Namespace, path: pathlib.Path) -> int:
    data = load_registry(path)
    refresh_observed(data)
    save_registry(path, data)
    if args.print_json:
        print(json.dumps(data["observed"], ensure_ascii=True, indent=2, sort_keys=True))
    return 0


def cmd_show(_: argparse.Namespace, path: pathlib.Path) -> int:
    data = load_registry(path)
    refresh_observed(data)
    save_registry(path, data)
    print(json.dumps(data, ensure_ascii=True, indent=2, sort_keys=True))
    return 0


def cmd_choose(args: argparse.Namespace, path: pathlib.Path) -> int:
    data = load_registry(path)
    observed = refresh_observed(data)
    save_registry(path, data)

    blocked = set(observed)
    for claim in data.get("claims", []):
        if not isinstance(claim, dict):
            continue
        project = str(claim.get("project", ""))
        port = int(claim.get("port", 0))
        if project != args.project:
            blocked.add(port)

    preferred = args.preferred
    if preferred is not None:
        ensure_valid_port(preferred)
        if preferred not in blocked:
            print(preferred)
            return 0

    claimed_by_project = sorted(
        {
            int(claim["port"])
            for claim in data.get("claims", [])
            if isinstance(claim, dict) and claim.get("project") == args.project and isinstance(claim.get("port"), int)
        }
    )
    for port in claimed_by_project:
        if port in blocked and not claim_for_project(data, args.project, port):
            continue
        print(port)
        return 0

    start_port = args.range_start
    end_port = args.range_end
    if start_port > end_port:
        raise SystemExit("invalid range: range_start > range_end")
    for port in range(start_port, end_port + 1):
        if port in blocked:
            continue
        print(port)
        return 0

    print(
        f"no free port found in range {start_port}-{end_port}; "
        "run snapshot/show to inspect registry and host listeners",
        file=sys.stderr,
    )
    return 1


def cmd_claim(args: argparse.Namespace, path: pathlib.Path) -> int:
    ensure_valid_port(args.port)
    data = load_registry(path)
    observed = refresh_observed(data)
    existing = claim_for_project(data, args.project, args.port)
    conflicts = claims_using_port(data, args.port, excluding_project=args.project)
    if conflicts:
        conflict = conflicts[0]
        print(
            f"port {args.port} already claimed by project={conflict.get('project')} "
            f"(status={conflict.get('status', 'unknown')})",
            file=sys.stderr,
        )
        return 1

    if args.port in observed and not existing and not port_bound_by_compose_project(args.port, args.compose_project):
        print(
            f"port {args.port} is already in use on host/docker; "
            "choose another port or stop conflicting service",
            file=sys.stderr,
        )
        return 1

    if existing is None:
        existing = {
            "port": args.port,
            "project": args.project,
            "status": args.status,
            "created_at": now_iso(),
            "updated_at": now_iso(),
        }
        if args.compose_project:
            existing["compose_project"] = args.compose_project
        if args.owner:
            existing["owner"] = args.owner
        if args.note:
            existing["note"] = args.note
        data["claims"].append(existing)
    else:
        existing["status"] = args.status
        existing["updated_at"] = now_iso()
        if args.compose_project:
            existing["compose_project"] = args.compose_project
        if args.owner:
            existing["owner"] = args.owner
        if args.note:
            existing["note"] = args.note

    save_registry(path, data)
    print(args.port)
    return 0


def cmd_activate(args: argparse.Namespace, path: pathlib.Path) -> int:
    ensure_valid_port(args.port)
    data = load_registry(path)
    refresh_observed(data)
    claim = claim_for_project(data, args.project, args.port)
    if claim is None:
        claim = {
            "port": args.port,
            "project": args.project,
            "status": "active",
            "created_at": now_iso(),
            "updated_at": now_iso(),
        }
        if args.compose_project:
            claim["compose_project"] = args.compose_project
        data["claims"].append(claim)
    else:
        claim["status"] = "active"
        claim["updated_at"] = now_iso()
        if args.compose_project:
            claim["compose_project"] = args.compose_project
    save_registry(path, data)
    print(args.port)
    return 0


def cmd_release(args: argparse.Namespace, path: pathlib.Path) -> int:
    ensure_valid_port(args.port)
    data = load_registry(path)
    refresh_observed(data)
    data["claims"] = [
        claim
        for claim in data.get("claims", [])
        if not (
            isinstance(claim, dict)
            and claim.get("project") == args.project
            and claim.get("port") == args.port
        )
    ]
    save_registry(path, data)
    return 0


def cmd_release_project(args: argparse.Namespace, path: pathlib.Path) -> int:
    data = load_registry(path)
    refresh_observed(data)
    data["claims"] = [
        claim
        for claim in data.get("claims", [])
        if not (isinstance(claim, dict) and claim.get("project") == args.project)
    ]
    save_registry(path, data)
    return 0


def build_parser(default_range_start: int, default_range_end: int) -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Shared port registry utility")
    parser.add_argument("--registry", help="Registry file path")
    sub = parser.add_subparsers(dest="command", required=True)

    snapshot = sub.add_parser("snapshot", help="Refresh observed host/docker port snapshot")
    snapshot.add_argument("--print-json", action="store_true")

    sub.add_parser("show", help="Show full registry JSON")

    choose = sub.add_parser("choose", help="Choose a free port using registry + host snapshot")
    choose.add_argument("--project", required=True)
    choose.add_argument("--preferred", type=int)
    choose.add_argument("--range-start", type=int, default=default_range_start)
    choose.add_argument("--range-end", type=int, default=default_range_end)

    claim = sub.add_parser("claim", help="Claim a port for a project")
    claim.add_argument("--project", required=True)
    claim.add_argument("--port", type=int, required=True)
    claim.add_argument("--compose-project")
    claim.add_argument("--owner")
    claim.add_argument("--note")
    claim.add_argument("--status", default="reserved")

    activate = sub.add_parser("activate", help="Mark a project port claim as active")
    activate.add_argument("--project", required=True)
    activate.add_argument("--port", type=int, required=True)
    activate.add_argument("--compose-project")

    release = sub.add_parser("release", help="Release one project port claim")
    release.add_argument("--project", required=True)
    release.add_argument("--port", type=int, required=True)

    release_project = sub.add_parser("release-project", help="Release all claims for one project")
    release_project.add_argument("--project", required=True)

    return parser


def main() -> int:
    repo_root = find_repo_root(pathlib.Path.cwd())
    config = load_codex_config(repo_root)
    parser = build_parser(
        int(config.get("default_range_start", 18080)),
        int(config.get("default_range_end", 18999)),
    )
    args = parser.parse_args()
    registry_path = resolve_registry_path(repo_root, config, args.registry)

    handlers = {
        "snapshot": cmd_snapshot,
        "show": cmd_show,
        "choose": cmd_choose,
        "claim": cmd_claim,
        "activate": cmd_activate,
        "release": cmd_release,
        "release-project": cmd_release_project,
    }
    return handlers[args.command](args, registry_path)


if __name__ == "__main__":
    sys.exit(main())
