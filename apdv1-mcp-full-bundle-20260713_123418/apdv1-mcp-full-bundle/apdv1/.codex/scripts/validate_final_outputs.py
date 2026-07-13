#!/usr/bin/env python3
"""Lightweight APDv1 final-bundle contract checker.

This intentionally avoids third-party jsonschema dependencies. It checks the
high-value invariants that batch runners and auditors need for quick feedback.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any


REQUIRED_DELIVERABLE_FILES = [
    "README_QUICKSTART.md",
    "docker-compose.yml",
    "scripts/deploy.sh",
    "scripts/verify.sh",
    "scripts/reset.sh",
]

REQUIRED_IMAGE_FILES = [
    "README_QUICKSTART.md",
    "docker-compose.yml",
    "scripts/deploy.sh",
    "scripts/verify.sh",
    "scripts/reset.sh",
    "runtime-config-initialized.tar.gz",
]

REQUIRED_LOG_FILES = [
    "preflight.json",
    "preflight.md",
    "deploy.log",
    "verification_result.json",
    "summary.md",
]


def load_json(path: Path) -> dict[str, Any]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:
        raise ValueError(f"{path}: invalid JSON: {exc}") from exc
    if not isinstance(data, dict):
        raise ValueError(f"{path}: expected JSON object")
    return data


def has_any(path: Path, names: list[str]) -> bool:
    return any((path / name).exists() for name in names)


def check(
    project_name: str,
    root: Path,
    *,
    delivery_style: str = "portable",
    terminal_status: str | None = None,
    require_audit: bool = False,
) -> tuple[bool, list[str], list[str]]:
    suffix = "-image-final" if delivery_style == "image" else "-final"
    deliverable = root / "Deliverable" / f"{project_name}{suffix}"
    logs = root / "DP_LOGS" / f"{project_name}{suffix}"
    errors: list[str] = []
    warnings: list[str] = []

    if not deliverable.is_dir():
        errors.append(f"missing deliverable dir: {deliverable}")
    if not logs.is_dir():
        errors.append(f"missing logs dir: {logs}")
    if errors:
        return False, errors, warnings

    required_files = REQUIRED_IMAGE_FILES if delivery_style == "image" else REQUIRED_DELIVERABLE_FILES
    for rel in required_files:
        if not (deliverable / rel).exists():
            errors.append(f"missing deliverable file: {rel}")

    if delivery_style == "image":
        image_dir = deliverable / "images"
        if not has_any(deliverable, ["image-build-context.tar.gz"]) and not (
            image_dir.is_dir() and (list(image_dir.glob("*.tar")) or list(image_dir.glob("*.tar.gz")))
        ):
            errors.append("missing image artifact: images/*.tar, images/*.tar.gz, or image-build-context.tar.gz")
    elif not has_any(deliverable, ["source-initialized.tar.gz", "runtime-config-initialized.tar.gz"]):
        errors.append("missing initialized snapshot: source-initialized.tar.gz or runtime-config-initialized.tar.gz")

    initdb = deliverable / "initdb"
    if not initdb.is_dir():
        errors.append("missing initdb directory")
    elif not any(initdb.glob("*.sql.gz")) and not (initdb / "README_NO_DB.md").exists():
        errors.append("missing DB state: initdb/*.sql.gz or initdb/README_NO_DB.md")

    for rel in REQUIRED_LOG_FILES:
        if not (logs / rel).exists():
            errors.append(f"missing log file: {rel}")

    audit_verdict = ""
    audit_path = logs / "audit_result.json"
    if audit_path.exists():
        try:
            audit = load_json(audit_path)
            verdict = audit.get("verdict")
            if verdict not in {"PASS", "CONDITIONAL", "FAIL"}:
                errors.append("audit_result.json verdict must be PASS, CONDITIONAL, or FAIL")
            else:
                audit_verdict = str(verdict)
            if terminal_status == "COMPLETED_SUCCESS" and verdict != "PASS":
                errors.append("COMPLETED_SUCCESS requires audit verdict PASS")
            if terminal_status == "COMPLETED_CONDITIONAL_SUCCESS" and verdict != "CONDITIONAL":
                errors.append("COMPLETED_CONDITIONAL_SUCCESS requires audit verdict CONDITIONAL")
            if verdict == "PASS" and audit.get("blocking_findings") not in ([], None):
                errors.append("audit_result.json PASS must not include blocking findings")
            if verdict == "FAIL":
                errors.append("audit_result.json verdict is FAIL")
            if verdict == "CONDITIONAL":
                if not audit.get("conditional_reason"):
                    errors.append("CONDITIONAL audit missing conditional_reason")
                if not audit.get("blocking_requirement"):
                    errors.append("CONDITIONAL audit missing blocking_requirement")
        except ValueError as exc:
            errors.append(str(exc))
    elif require_audit or terminal_status in {"COMPLETED_SUCCESS", "COMPLETED_CONDITIONAL_SUCCESS"}:
        errors.append(f"missing audit result: {audit_path}")
    else:
        warnings.append(f"missing audit result: {audit_path}")

    verification_path = logs / "verification_result.json"
    if verification_path.exists():
        try:
            verification = load_json(verification_path)
            strict_verification = terminal_status != "COMPLETED_CONDITIONAL_SUCCESS" and audit_verdict != "CONDITIONAL"
            if strict_verification and verification.get("passed") is not True:
                errors.append("verification_result.json does not have passed=true")
            if strict_verification and verification.get("basic_function_verified") is not True:
                errors.append("verification_result.json does not have basic_function_verified=true")
            if not strict_verification and verification.get("passed") is not True:
                warnings.append("verification_result.json passed is not true under CONDITIONAL result")
            if not strict_verification and verification.get("basic_function_verified") is not True:
                warnings.append("verification_result.json basic_function_verified is not true under CONDITIONAL result")
        except ValueError as exc:
            errors.append(str(exc))

    return not errors, errors, warnings


def main() -> int:
    parser = argparse.ArgumentParser(description="Validate APDv1 portable final output structure.")
    parser.add_argument("project_name", help="Resolved project name without the -final suffix")
    parser.add_argument("--root", default=".", help="APDv1 repository root")
    parser.add_argument("--json", action="store_true", help="Emit machine-readable result")
    parser.add_argument(
        "--delivery-style",
        choices=["portable", "image"],
        default="portable",
        help="Final deliverable style to validate",
    )
    parser.add_argument(
        "--terminal-status",
        choices=["COMPLETED_SUCCESS", "COMPLETED_CONDITIONAL_SUCCESS", "COMPLETED_FAILED"],
        default=None,
        help="Expected task terminal status; enables stricter audit verdict checks",
    )
    parser.add_argument("--require-audit", action="store_true", help="Fail when audit_result.json is absent")
    args = parser.parse_args()

    ok, errors, warnings = check(
        args.project_name,
        Path(args.root).resolve(),
        delivery_style=args.delivery_style,
        terminal_status=args.terminal_status,
        require_audit=args.require_audit,
    )
    payload = {"ok": ok, "project_name": args.project_name, "errors": errors, "warnings": warnings}
    if args.json:
        print(json.dumps(payload, ensure_ascii=False, indent=2))
    else:
        print("PASS" if ok else "FAIL")
        for item in warnings:
            print(f"warning: {item}")
        for item in errors:
            print(f"error: {item}")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
