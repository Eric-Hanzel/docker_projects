#!/usr/bin/env python3
import argparse
import json
import os
import re
import subprocess
import sys
from datetime import datetime, timezone


DEFAULT_POLICY = ".codex/image_cache_policy.json"


def run(args, timeout=None):
    try:
        return subprocess.run(
            args,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=timeout,
        )
    except subprocess.TimeoutExpired as exc:
        return subprocess.CompletedProcess(
            args,
            124,
            stdout=exc.stdout or "",
            stderr=f"timed out after {timeout}s",
        )


def load_policy(path):
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def docker_images():
    proc = run(["docker", "images", "--format", "{{json .}}"])
    if proc.returncode != 0:
        raise SystemExit(proc.stderr.strip() or "docker images failed")
    images = []
    for line in proc.stdout.splitlines():
        if not line.strip():
            continue
        row = json.loads(line)
        row["Ref"] = f"{row.get('Repository', '')}:{row.get('Tag', '')}"
        images.append(row)
    return images


def running_images():
    proc = run(["docker", "ps", "--format", "{{.Image}}"])
    if proc.returncode != 0:
        return set(), set()
    refs = {line.strip() for line in proc.stdout.splitlines() if line.strip()}
    ids = set()
    inspect_proc = run(["docker", "ps", "-q"])
    if inspect_proc.returncode != 0:
        return refs, ids
    for container_id in inspect_proc.stdout.splitlines():
        if not container_id.strip():
            continue
        image_proc = run(["docker", "inspect", "--format", "{{.Image}}", container_id.strip()])
        if image_proc.returncode != 0:
            continue
        image_id = image_proc.stdout.strip()
        if image_id.startswith("sha256:"):
            image_id = image_id[len("sha256:"):]
        if image_id:
            ids.add(image_id)
            ids.add(image_id[:12])
    return refs, ids


def parse_size_to_bytes(size):
    text = str(size).strip()
    match = re.match(r"^([0-9.]+)\s*([A-Za-z]+)$", text)
    if not match:
        return 0
    value = float(match.group(1))
    unit = match.group(2).lower()
    factors = {
        "b": 1,
        "kb": 1000,
        "mb": 1000**2,
        "gb": 1000**3,
        "tb": 1000**4,
        "kib": 1024,
        "mib": 1024**2,
        "gib": 1024**3,
        "tib": 1024**4,
    }
    return int(value * factors.get(unit, 0))


def starts_with_any(value, prefixes):
    for prefix in prefixes:
        if value == prefix:
            return True
        if prefix.endswith(("/", "-")) and value.startswith(prefix):
            return True
    return False


def matches_any(value, patterns):
    return any(re.search(pattern, value) for pattern in patterns)


def classify(image, policy, running_refs, running_ids):
    repo = image.get("Repository", "")
    tag = image.get("Tag", "")
    image_id = image.get("ID", "")
    ref = f"{repo}:{tag}"
    identity = f"{repo}:{tag}"

    if ref in running_refs or image_id in running_ids:
        return "keep", "used by a running container"
    if repo == "<none>" or tag == "<none>":
        return "remove_safe", "dangling image"
    if matches_any(identity, policy.get("remove_name_patterns", [])):
        return "remove_safe", "APDv1 final/bundle/project artifact naming"
    if starts_with_any(repo, policy.get("keep_repositories", [])):
        return "keep", "reusable base, service, build, or cluster cache"
    if starts_with_any(repo, policy.get("review_repositories", [])):
        return "review_complete_product", "complete product or suite image; not generic base cache"
    return "review_unknown", "not covered by the cache policy"


def summarize(rows):
    totals = {}
    counts = {}
    for row in rows:
        bucket = row["bucket"]
        counts[bucket] = counts.get(bucket, 0) + 1
        totals[bucket] = totals.get(bucket, 0) + row["size_bytes"]
    return {
        bucket: {"count": counts[bucket], "bytes": totals[bucket]}
        for bucket in sorted(counts)
    }


def human_bytes(n):
    value = float(n)
    for unit in ["B", "KB", "MB", "GB", "TB"]:
        if value < 1000 or unit == "TB":
            return f"{value:.1f}{unit}" if unit != "B" else f"{int(value)}B"
        value /= 1000


def write_reports(rows, summary, output_dir):
    os.makedirs(output_dir, exist_ok=True)
    json_path = os.path.join(output_dir, "docker_image_cache_report.json")
    md_path = os.path.join(output_dir, "docker_image_cache_report.md")
    payload = {
        "generated_at": datetime.now(timezone.utc).astimezone().replace(microsecond=0).isoformat(),
        "summary": summary,
        "images": rows,
    }
    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)
        f.write("\n")
    with open(md_path, "w", encoding="utf-8") as f:
        f.write("# Docker Image Cache Report\n\n")
        f.write("## Summary\n\n")
        for bucket, data in summary.items():
            f.write(f"- `{bucket}`: {data['count']} images, {human_bytes(data['bytes'])}\n")
        f.write("\n## Images\n\n")
        f.write("| Bucket | Size | Image | Reason |\n")
        f.write("| --- | ---: | --- | --- |\n")
        for row in sorted(rows, key=lambda r: (r["bucket"], -r["size_bytes"], r["ref"])):
            f.write(f"| `{row['bucket']}` | {row['size']} | `{row['ref']}` | {row['reason']} |\n")
    return json_path, md_path


def apply_removals(rows, bucket, timeout):
    refs = []
    for row in rows:
        if row["bucket"] != bucket:
            continue
        if row["repository"] == "<none>" or row["tag"] == "<none>":
            refs.append(row["id"])
        else:
            refs.append(row["ref"])
    results = []
    for ref in refs:
        proc = run(["docker", "rmi", ref], timeout=timeout)
        results.append({
            "ref": ref,
            "returncode": proc.returncode,
            "stdout": proc.stdout.strip(),
            "stderr": proc.stderr.strip(),
        })
    return results


def main():
    parser = argparse.ArgumentParser(
        description="Classify Docker images for APDv1 cache retention and safe cleanup."
    )
    parser.add_argument("--policy", default=DEFAULT_POLICY)
    parser.add_argument("--output-dir", default=".codex/state/docker-image-cache")
    parser.add_argument("--apply-safe", action="store_true", help="Remove only remove_safe images.")
    parser.add_argument(
        "--apply-reviewed",
        action="store_true",
        help="Also remove review_complete_product images. Use only after reviewing the report.",
    )
    parser.add_argument(
        "--rmi-timeout",
        type=int,
        default=90,
        help="Timeout in seconds for each docker rmi operation.",
    )
    args = parser.parse_args()

    policy = load_policy(args.policy)
    running_refs, running_ids = running_images()
    rows = []
    for image in docker_images():
        bucket, reason = classify(image, policy, running_refs, running_ids)
        size = image.get("Size", "")
        rows.append({
            "bucket": bucket,
            "reason": reason,
            "repository": image.get("Repository", ""),
            "tag": image.get("Tag", ""),
            "id": image.get("ID", ""),
            "size": size,
            "size_bytes": parse_size_to_bytes(size),
            "created_since": image.get("CreatedSince", ""),
            "created_at": image.get("CreatedAt", ""),
            "containers": image.get("Containers", ""),
            "ref": image.get("Ref", ""),
        })

    summary = summarize(rows)
    json_path, md_path = write_reports(rows, summary, args.output_dir)

    print(f"Report JSON: {json_path}")
    print(f"Report Markdown: {md_path}")
    for bucket, data in summary.items():
        print(f"{bucket}: {data['count']} images, {human_bytes(data['bytes'])}")

    removal_results = []
    if args.apply_safe:
        removal_results.extend(apply_removals(rows, "remove_safe", args.rmi_timeout))
    if args.apply_reviewed:
        removal_results.extend(apply_removals(rows, "review_complete_product", args.rmi_timeout))
    if removal_results:
        result_path = os.path.join(args.output_dir, "docker_image_cache_removal_results.json")
        with open(result_path, "w", encoding="utf-8") as f:
            json.dump(removal_results, f, ensure_ascii=False, indent=2)
            f.write("\n")
        failed = [r for r in removal_results if r["returncode"] != 0]
        print(f"Removal results: {result_path}")
        if failed:
            print(f"Failed removals: {len(failed)}", file=sys.stderr)
            return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
