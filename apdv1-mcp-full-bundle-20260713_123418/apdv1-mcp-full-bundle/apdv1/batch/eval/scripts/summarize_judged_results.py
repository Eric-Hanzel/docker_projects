#!/usr/bin/env python3
import json
import statistics
import sys
from pathlib import Path


def mean(values):
    vals = [v for v in values if isinstance(v, (int, float))]
    return statistics.mean(vals) if vals else None


def main():
    if len(sys.argv) != 3:
        raise SystemExit("usage: summarize_judged_results.py JUDGED_JSONL OUT_JSON")
    rows = []
    with open(sys.argv[1], encoding="utf-8") as f:
        for line in f:
            if line.strip():
                rows.append(json.loads(line))
    total = len(rows)
    runtime = sum(1 for r in rows if r.get("runtime_success") is True)
    conditional = sum(1 for r in rows if r.get("conditional_success") is True)
    labels = {}
    statuses = {}
    for r in rows:
        label = r.get("failure_primary_label")
        if label:
            labels[label] = labels.get(label, 0) + 1
        status = r.get("terminal_status")
        if status:
            statuses[status] = statuses.get(status, 0) + 1
    summary = {
        "total": total,
        "runtime_success_count": runtime,
        "conditional_success_count": conditional,
        "strict_success_rate": runtime / total if total else None,
        "useful_completion_rate": (runtime + conditional) / total if total else None,
        "terminal_status_counts": statuses,
        "failure_primary_label_counts": labels,
        "mean_wall_time_seconds": mean([r.get("wall_time_seconds") for r in rows]),
        "mean_network_adjusted_seconds": mean([r.get("network_adjusted_seconds") for r in rows]),
        "mean_total_tokens": mean([r.get("total_tokens") for r in rows]),
    }
    Path(sys.argv[2]).write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False))


if __name__ == "__main__":
    main()
