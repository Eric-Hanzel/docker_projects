#!/usr/bin/env python3
import csv
import json
import statistics
import sys
from pathlib import Path


TOKEN_FIELDS = [
    "input_tokens",
    "cached_input_tokens",
    "output_tokens",
    "reasoning_output_tokens",
    "total_tokens",
]


def number(value):
    if value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def mean(values):
    vals = [v for v in values if v is not None]
    if not vals:
        return None
    return round(statistics.mean(vals), 2)


def median(values):
    vals = [v for v in values if v is not None]
    if not vals:
        return None
    return round(statistics.median(vals), 2)


def load_jsonl(path):
    rows = []
    with path.open(encoding="utf-8") as f:
        for line in f:
            if line.strip():
                rows.append(json.loads(line))
    return rows


def main():
    if len(sys.argv) < 2:
        print("Usage: summarize_portable_cost.py RAW_RESULTS.jsonl [OUT_DIR]", file=sys.stderr)
        return 2

    raw_path = Path(sys.argv[1]).resolve()
    out_dir = Path(sys.argv[2]).resolve() if len(sys.argv) > 2 else raw_path.parent
    out_dir.mkdir(parents=True, exist_ok=True)

    rows = load_jsonl(raw_path)
    per_project = []
    for row in rows:
        wall = number(row.get("wall_time_seconds"))
        item = {
            "task_id": row.get("task_id"),
            "target_index": row.get("target_index"),
            "url": row.get("url"),
            "terminal_status": row.get("terminal_status"),
            "exit_code": row.get("exit_code"),
            "wall_time_seconds": wall,
            "wall_time_minutes": round(wall / 60, 2) if wall is not None else None,
            "task_dir": row.get("task_dir"),
        }
        for field in TOKEN_FIELDS:
            item[field] = number(row.get(field))
        per_project.append(item)

    wall_times = [p["wall_time_seconds"] for p in per_project]
    total_tokens = [p["total_tokens"] for p in per_project]
    status_counts = {}
    for p in per_project:
        status = p.get("terminal_status") or "UNKNOWN"
        status_counts[status] = status_counts.get(status, 0) + 1

    mean_wall = mean(wall_times)
    mean_tokens = mean(total_tokens)
    completed_count = len(per_project)
    total_wall = sum(v for v in wall_times if v is not None)
    total_token_sum = sum(v for v in total_tokens if v is not None)
    projects_per_24h_by_mean = round(86400 / mean_wall, 2) if mean_wall else None
    tokens_per_24h_by_mean = (
        round(projects_per_24h_by_mean * mean_tokens)
        if projects_per_24h_by_mean is not None and mean_tokens is not None
        else None
    )
    projects_per_24h_by_observed_rate = (
        round(86400 * completed_count / total_wall, 2)
        if total_wall > 0 and completed_count > 0
        else None
    )
    tokens_per_24h_by_observed_rate = (
        round(86400 * total_token_sum / total_wall)
        if total_wall > 0 and total_token_sum > 0
        else None
    )

    summary = {
        "raw_results_file": str(raw_path),
        "total_projects": completed_count,
        "terminal_status_counts": status_counts,
        "total_wall_time_seconds": total_wall,
        "total_wall_time_hours": round(total_wall / 3600, 2) if total_wall else 0,
        "mean_wall_time_seconds": mean_wall,
        "median_wall_time_seconds": median(wall_times),
        "mean_total_tokens": mean_tokens,
        "median_total_tokens": median(total_tokens),
        "total_tokens": total_token_sum,
        "projects_per_24h_by_mean": projects_per_24h_by_mean,
        "tokens_per_24h_by_mean": tokens_per_24h_by_mean,
        "projects_per_24h_by_observed_rate": projects_per_24h_by_observed_rate,
        "tokens_per_24h_by_observed_rate": tokens_per_24h_by_observed_rate,
        "per_project": per_project,
    }

    json_path = out_dir / "portable_cost_summary.json"
    csv_path = out_dir / "portable_cost_per_project.csv"
    md_path = out_dir / "portable_cost_summary.md"

    json_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    with csv_path.open("w", encoding="utf-8", newline="") as f:
        fieldnames = [
            "task_id",
            "target_index",
            "url",
            "terminal_status",
            "exit_code",
            "wall_time_seconds",
            "wall_time_minutes",
            *TOKEN_FIELDS,
            "task_dir",
        ]
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        for item in per_project:
            writer.writerow({k: item.get(k) for k in fieldnames})

    lines = [
        "# Portable Cost Summary",
        "",
        f"- Raw results: `{raw_path}`",
        f"- Projects: {completed_count}",
        f"- Status counts: `{json.dumps(status_counts, ensure_ascii=False, sort_keys=True)}`",
        f"- Total wall time: {summary['total_wall_time_hours']} h",
        f"- Mean wall time: {mean_wall} s",
        f"- Median wall time: {summary['median_wall_time_seconds']} s",
        f"- Mean total tokens: {mean_tokens}",
        f"- Median total tokens: {summary['median_total_tokens']}",
        f"- Estimated projects per 24h: {projects_per_24h_by_observed_rate}",
        f"- Estimated tokens per 24h: {tokens_per_24h_by_observed_rate}",
        "",
        "| task | status | minutes | total_tokens | url |",
        "| --- | --- | ---: | ---: | --- |",
    ]
    for item in per_project:
        lines.append(
            f"| {item.get('task_id')} | {item.get('terminal_status')} | "
            f"{item.get('wall_time_minutes')} | {item.get('total_tokens')} | {item.get('url')} |"
        )
    md_path.write_text("\n".join(lines) + "\n", encoding="utf-8")

    print(json.dumps({"summary": str(json_path), "csv": str(csv_path), "markdown": str(md_path)}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
