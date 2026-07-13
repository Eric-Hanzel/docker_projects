#!/usr/bin/env python3
import argparse
import json
import re
from pathlib import Path


MAX_TEXT_CHARS = 50000
TAIL_CHARS = 30000


def read_text(path: Path, limit: int = MAX_TEXT_CHARS) -> str:
    try:
        data = path.read_text(encoding="utf-8", errors="replace")
    except Exception as exc:
        return f"[unreadable: {exc}]"
    if len(data) <= limit:
        return data
    head = limit // 3
    tail = limit - head
    return data[:head] + "\n\n[... truncated ...]\n\n" + data[-tail:]


def tail_text(path: Path, limit: int = TAIL_CHARS) -> str:
    try:
        data = path.read_text(encoding="utf-8", errors="replace")
    except Exception as exc:
        return f"[unreadable: {exc}]"
    if len(data) <= limit:
        return data
    return "[... tail excerpt ...]\n" + data[-limit:]


def load_json(path: Path):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None


def load_metadata(root: Path):
    meta = {}
    path = root / "batch/eval/targets/eval_target_metadata.jsonl"
    if not path.exists():
        return meta
    with path.open(encoding="utf-8") as f:
        for line in f:
            if not line.strip():
                continue
            try:
                row = json.loads(line)
            except Exception:
                continue
            url = row.get("url")
            if url:
                meta[url] = row
    return meta


def append_file_section(parts, title: str, path: Path, mode: str = "tail"):
    parts.append(f"## {title}\n")
    parts.append(f"Path: `{path}`\n")
    text = tail_text(path) if mode == "tail" else read_text(path)
    parts.append("```text\n" + text + "\n```\n")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("result_json", help="Per-task result.json or one raw-result JSON object file")
    parser.add_argument("--root", default=".", help="Repository root")
    args = parser.parse_args()

    root = Path(args.root).resolve()
    result_path = Path(args.result_json).resolve()
    row = load_json(result_path)
    if not isinstance(row, dict):
        raise SystemExit(f"Could not parse result JSON: {result_path}")

    metadata = load_metadata(root).get(row.get("url"), {})
    task_dir = Path(row.get("task_dir", "")).resolve()
    parts = []

    parts.append("# Judge Context\n")
    parts.append("## Raw Result\n")
    parts.append("```json\n" + json.dumps(row, ensure_ascii=False, indent=2) + "\n```\n")

    if metadata:
        safe_meta = {
            k: metadata.get(k)
            for k in [
                "url",
                "category",
                "expected_difficulty",
                "selection_reason",
                "historical_status",
            ]
            if k in metadata
        }
        parts.append("## Evaluation Metadata\n")
        parts.append("This metadata is for judging and analysis only; it was not passed to the deployment agent.\n")
        parts.append("```json\n" + json.dumps(safe_meta, ensure_ascii=False, indent=2) + "\n```\n")

    combined_text = ""
    for name in ["target.json", "last_message.txt", "trace.txt", "codex.log"]:
        path = task_dir / name
        if path.exists():
            mode = "full" if name in {"target.json", "last_message.txt"} else "tail"
            append_file_section(parts, name, path, mode)
            try:
                combined_text += "\n" + path.read_text(encoding="utf-8", errors="replace")
            except Exception:
                pass

    token_path = task_dir / "token_usage.json"
    if token_path.exists():
        append_file_section(parts, "token_usage.json", token_path, "full")

    cleanup_path = task_dir / "docker_cleanup_report.json"
    if cleanup_path.exists():
        append_file_section(parts, "docker_cleanup_report.json", cleanup_path, "full")

    agents_dir = task_dir / "agents"
    if agents_dir.exists():
        for audit_file in sorted(agents_dir.glob("*/trace.txt"))[:5]:
            append_file_section(parts, f"subagent trace: {audit_file.parent.name}", audit_file, "tail")

    # APDv1 runs often write audit evidence outside the task dir. Pull referenced
    # audit paths when logs mention them.
    referenced = set()
    for match in re.finditer(r"DP_LOGS/[A-Za-z0-9_.@:+/-]+/(?:audit_result\.json|audit\.md|summary\.md|deploy\.log)", combined_text):
        referenced.add(match.group(0))
    for rel in sorted(referenced):
        path = root / rel
        if path.exists():
            append_file_section(parts, rel, path, "full" if path.suffix in {".json", ".md"} else "tail")

    print("\n".join(parts))


if __name__ == "__main__":
    main()
