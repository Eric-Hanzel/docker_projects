#!/usr/bin/env python3
import json
import sys
from pathlib import Path


FIELDS = [
    "input_tokens",
    "cached_input_tokens",
    "output_tokens",
    "reasoning_output_tokens",
    "total_tokens",
]


def last_usage(path: Path):
    usage = None
    try:
        with path.open(encoding="utf-8", errors="ignore") as f:
            for line in f:
                try:
                    obj = json.loads(line)
                except Exception:
                    continue
                if obj.get("type") != "event_msg":
                    continue
                payload = obj.get("payload") or {}
                if payload.get("type") != "token_count":
                    continue
                info = payload.get("info") or {}
                current = info.get("total_token_usage")
                if isinstance(current, dict):
                    usage = current
    except FileNotFoundError:
        return None
    return usage


def main() -> int:
    if len(sys.argv) < 2:
        print(json.dumps({k: None for k in FIELDS}))
        return 0

    paths = []
    for arg in sys.argv[1:]:
        p = Path(arg)
        if p.is_dir():
            paths.extend(sorted(p.glob("**/trajectory.jsonl")))
        else:
            paths.append(p)

    total = {k: 0 for k in FIELDS}
    found = False
    per_file = []
    for path in paths:
        usage = last_usage(path)
        if not usage:
            continue
        found = True
        normalized = {k: int(usage.get(k) or 0) for k in FIELDS}
        per_file.append({"path": str(path), **normalized})
        for key in FIELDS:
            total[key] += normalized[key]

    if not found:
        total = {k: None for k in FIELDS}
    total["trajectory_count"] = len(per_file)
    total["per_trajectory"] = per_file
    print(json.dumps(total, ensure_ascii=False, separators=(",", ":")))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
