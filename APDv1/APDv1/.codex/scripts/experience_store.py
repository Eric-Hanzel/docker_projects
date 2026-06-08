#!/usr/bin/env python3
import argparse
import json
import sys
from copy import deepcopy
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
STORE_DIR = ROOT / ".codex" / "experience"
CATALOG_PATH = STORE_DIR / "catalog.json"

GENERIC_TAGS = {
    "docker", "dockerhub", "registry", "image-pull", "throughput", "bandwidth",
    "deploy", "bundle", "verify", "verification", "http", "curl", "proxy",
    "network", "source", "clone", "codeload", "git", "github", "permissions",
    "cli", "user", "init", "runtime", "deliverable", "batch-budget"
}


def load_json(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def dump_json(path: Path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def read_jsonl(path: Path):
    if not path.exists():
        return []
    rows = []
    for line in path.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        rows.append(json.loads(stripped))
    return rows


def write_jsonl(path: Path, rows):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as fh:
        for row in rows:
            fh.write(json.dumps(row, ensure_ascii=False) + "\n")


def ensure_store():
    catalog = load_json(CATALOG_PATH)
    for kind in catalog["kinds"].values():
        for subcategory in kind["subcategories"].values():
            for key in ("index_file", "detail_file"):
                path = STORE_DIR / subcategory[key]
                path.parent.mkdir(parents=True, exist_ok=True)
                if not path.exists():
                    path.write_text("", encoding="utf-8")
    return catalog


def classify_record(record):
    category = record.get("category", "")
    tags = set(record.get("tags", []))
    kind = record.get("kind") or "failure_avoidance_patterns"

    if kind == "success_patterns":
        if category.startswith("bundle/"):
            subcategory = "bundle-packaging"
        elif category.startswith("verify/"):
            subcategory = "verification"
        elif category.startswith("deploy/init") or category.startswith("init/"):
            subcategory = "runtime-init"
        elif category.startswith("deploy/") or category.startswith("plan/"):
            subcategory = "deploy-path"
        elif "performance" in tags or "throughput" in tags or "budget" in tags:
            subcategory = "performance-decisions"
        else:
            subcategory = "project-specific"
    else:
        if category.startswith("deploy/source-fetch"):
            subcategory = "source-fetch"
        elif category.startswith("deploy/image-pull"):
            subcategory = "image-pull"
        elif category.startswith("deploy/init") or category.startswith("init/"):
            subcategory = "runtime-init"
        elif category.startswith("dependencies/"):
            subcategory = "dependency-gates"
        elif category.startswith("verify/"):
            subcategory = "verification"
        elif category.startswith("frontend/") or category.startswith("build/"):
            subcategory = "build-artifacts"
        elif "proxy" in tags or "port" in tags or "network" in tags:
            subcategory = "ports-and-network"
        else:
            subcategory = "project-specific"
    return kind, subcategory


def normalize_text_list(values):
    seen = set()
    merged = []
    for value in values or []:
        text = str(value).strip()
        if not text or text in seen:
            continue
        merged.append(text)
        seen.add(text)
    return merged


def derive_summary(record):
    for field in ("summary", "symptom", "root_cause"):
        text = str(record.get(field, "")).strip()
        if text:
            return text
    signature = str(record.get("signature", "")).replace("-", " ").strip()
    if signature:
        return signature[:160]
    return "validated experience entry"


def derive_patterns(tags):
    project_patterns = []
    stack_patterns = []
    for tag in tags:
        if tag in GENERIC_TAGS:
            stack_patterns.append(tag)
        else:
            project_patterns.append(tag)
    return normalize_text_list(project_patterns), normalize_text_list(stack_patterns)


def normalize_record(record, quick_checks=None):
    normalized = deepcopy(record)
    normalized["kind"], normalized["subcategory"] = classify_record(normalized)
    normalized["stage"] = normalize_text_list(normalized.get("stage", []))
    normalized["tags"] = normalize_text_list(normalized.get("tags", []))
    normalized["fix"] = normalize_text_list(normalized.get("fix", []))
    normalized["precheck"] = normalize_text_list(normalized.get("precheck", []))
    normalized["anti_pattern"] = normalize_text_list(normalized.get("anti_pattern", []))
    normalized["quick_checks"] = normalize_text_list(
        normalized.get("quick_checks", []) + list(quick_checks or [])
    )
    normalized["summary"] = derive_summary(normalized)
    normalized.setdefault("successful_path", "")
    normalized.setdefault("evidence", [])
    normalized["evidence"] = normalize_text_list(normalized.get("evidence", []))
    project_patterns, stack_patterns = derive_patterns(normalized["tags"])
    normalized.setdefault("project_patterns", project_patterns)
    normalized.setdefault("stack_patterns", stack_patterns)
    normalized["project_patterns"] = normalize_text_list(normalized.get("project_patterns", []))
    normalized["stack_patterns"] = normalize_text_list(normalized.get("stack_patterns", []))
    return normalized


def subcategory_paths(catalog, kind_name, subcategory_name):
    subcategory = catalog["kinds"][kind_name]["subcategories"][subcategory_name]
    return STORE_DIR / subcategory["index_file"], STORE_DIR / subcategory["detail_file"]


def build_index_entry(detail_record, detail_path):
    return {
        "id": detail_record["id"],
        "kind": detail_record["kind"],
        "subcategory": detail_record["subcategory"],
        "category": detail_record["category"],
        "signature": detail_record["signature"],
        "stage": detail_record.get("stage", []),
        "severity": detail_record.get("severity", "medium"),
        "tags": detail_record.get("tags", []),
        "project_patterns": detail_record.get("project_patterns", []),
        "stack_patterns": detail_record.get("stack_patterns", []),
        "summary": detail_record.get("summary", ""),
        "quick_checks": detail_record.get("quick_checks", []),
        "detail_file": str(detail_path.relative_to(STORE_DIR)),
        "count": detail_record.get("count", 1),
        "last_seen": detail_record.get("last_seen", "")
    }


def merge_records(existing, incoming):
    merged = deepcopy(existing)
    scalar_keep_existing = {"id", "kind", "subcategory", "category", "signature", "created_at"}
    for key, value in incoming.items():
        if key in scalar_keep_existing and merged.get(key):
            continue
        if isinstance(value, list):
            merged[key] = normalize_text_list(merged.get(key, []) + value)
        elif value not in ("", None):
            merged[key] = value
    merged["summary"] = derive_summary(merged)
    merged["count"] = max(int(existing.get("count", 1)), int(incoming.get("count", 1)))
    return merged


def upsert_records(records):
    catalog = ensure_store()
    grouped = {}
    for raw in records:
        record = normalize_record(raw, raw.get("quick_checks", []))
        grouped.setdefault((record["kind"], record["subcategory"]), []).append(record)

    for (kind_name, subcategory_name), sub_records in grouped.items():
        index_path, detail_path = subcategory_paths(catalog, kind_name, subcategory_name)
        existing_details = read_jsonl(detail_path)
        by_key = {(row["category"], row["signature"]): row for row in existing_details}
        order = [(row["category"], row["signature"]) for row in existing_details]

        for record in sub_records:
            key = (record["category"], record["signature"])
            current = by_key.get(key)
            if current:
                by_key[key] = merge_records(current, record)
            else:
                by_key[key] = record
                order.append(key)

        merged_details = [by_key[key] for key in order]
        write_jsonl(detail_path, merged_details)
        write_jsonl(index_path, [build_index_entry(row, detail_path) for row in merged_details])


def query_records(args):
    catalog = ensure_store()
    selected_kinds = [args.kind] if args.kind else list(catalog["kinds"].keys())
    results = []
    for kind_name in selected_kinds:
        subcategories = catalog["kinds"][kind_name]["subcategories"]
        selected_subcats = [args.subcategory] if args.subcategory else list(subcategories.keys())
        for subcategory_name in selected_subcats:
            index_path, detail_path = subcategory_paths(catalog, kind_name, subcategory_name)
            index_rows = read_jsonl(index_path)
            detail_rows = None
            for row in index_rows:
                score = 0
                if args.stage:
                    overlap = set(args.stage) & set(row.get("stage", []))
                    if not overlap:
                        continue
                    score += 3 * len(overlap)
                if args.tag:
                    overlap = set(args.tag) & set(row.get("tags", []))
                    if not overlap:
                        continue
                    score += 2 * len(overlap)
                haystack = " ".join(
                    [
                        row.get("summary", ""),
                        row.get("category", ""),
                        row.get("signature", ""),
                        " ".join(row.get("tags", [])),
                        " ".join(row.get("project_patterns", [])),
                        " ".join(row.get("stack_patterns", []))
                    ]
                ).lower()
                if args.text:
                    text = args.text.lower()
                    if text not in haystack:
                        continue
                    score += 1
                if score == 0 and (args.stage or args.tag or args.text):
                    continue
                output = deepcopy(row)
                output["_score"] = score
                if args.full:
                    if detail_rows is None:
                        detail_rows = {
                            detail["id"]: detail for detail in read_jsonl(detail_path)
                        }
                    detail = detail_rows.get(row["id"])
                    if detail:
                        output["detail"] = detail
                results.append(output)
    results.sort(key=lambda item: (-item.get("_score", 0), item.get("id", "")))
    for row in results[: args.limit]:
        print(json.dumps(row, ensure_ascii=False))


def main():
    parser = argparse.ArgumentParser(description="Hierarchical experience store helper.")
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("init-store", help="Ensure catalog-backed directories and files exist.")

    upsert = sub.add_parser("upsert-record", help="Upsert one record or an array of records.")
    upsert.add_argument("--input", required=True, help="Path to JSON file or '-' for stdin.")

    query = sub.add_parser("query", help="Query relevant experience entries.")
    query.add_argument("--kind", choices=["success_patterns", "failure_avoidance_patterns"])
    query.add_argument("--subcategory")
    query.add_argument("--stage", action="append")
    query.add_argument("--tag", action="append")
    query.add_argument("--text")
    query.add_argument("--full", action="store_true")
    query.add_argument("--limit", type=int, default=10)

    args = parser.parse_args()
    if args.command == "init-store":
        ensure_store()
        return 0
    if args.command == "upsert-record":
        raw = sys.stdin.read() if args.input == "-" else Path(args.input).read_text(encoding="utf-8")
        data = json.loads(raw)
        records = data if isinstance(data, list) else [data]
        upsert_records(records)
        return 0
    if args.command == "query":
        query_records(args)
        return 0
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
