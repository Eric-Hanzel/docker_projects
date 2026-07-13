#!/usr/bin/env python3
import json
import statistics
import sys
from pathlib import Path


def mean(values):
    vals = [v for v in values if isinstance(v, (int, float))]
    return statistics.mean(vals) if vals else None


def pct(value):
    return None if value is None else round(value * 100, 2)


def load_rows(paths):
    rows = []
    for path in paths:
        with open(path, encoding="utf-8") as f:
            for line in f:
                if line.strip():
                    row = json.loads(line)
                    row["_source_file"] = str(path)
                    rows.append(row)
    return rows


def summarize(rows):
    total = len(rows)
    runtime = sum(1 for r in rows if r.get("runtime_success") is True)
    conditional = sum(1 for r in rows if r.get("conditional_success") is True)
    labels = {}
    for r in rows:
        label = r.get("failure_primary_label")
        if label:
            labels[label] = labels.get(label, 0) + 1
    return {
        "total": total,
        "runtime_success_count": runtime,
        "conditional_success_count": conditional,
        "strict_success_rate": runtime / total if total else None,
        "useful_completion_rate": (runtime + conditional) / total if total else None,
        "mean_wall_time_seconds": mean([r.get("wall_time_seconds") for r in rows]),
        "mean_network_adjusted_seconds": mean([r.get("network_adjusted_seconds") for r in rows]),
        "mean_total_tokens": mean([r.get("total_tokens") for r in rows]),
        "failure_primary_label_counts": labels,
    }


def main():
    if len(sys.argv) < 3:
        raise SystemExit("usage: compare_judged_results.py OUT_JSON JUDGED_JSONL [JUDGED_JSONL ...]")
    out = Path(sys.argv[1])
    rows = load_rows(sys.argv[2:])
    by_arm = {}
    for row in rows:
        by_arm.setdefault(row.get("arm") or "unknown", []).append(row)
    result = {
        "overall": summarize(rows),
        "by_arm": {arm: summarize(arm_rows) for arm, arm_rows in sorted(by_arm.items())},
    }
    out.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(result, ensure_ascii=False))

    print("\narm,total,strict_success_rate,useful_completion_rate,mean_wall_time_seconds,mean_network_adjusted_seconds,mean_total_tokens")
    for arm, summary in result["by_arm"].items():
        print(
            ",".join(
                [
                    arm,
                    str(summary["total"]),
                    str(pct(summary["strict_success_rate"])),
                    str(pct(summary["useful_completion_rate"])),
                    str(summary["mean_wall_time_seconds"]),
                    str(summary["mean_network_adjusted_seconds"]),
                    str(summary["mean_total_tokens"]),
                ]
            )
        )


if __name__ == "__main__":
    main()
