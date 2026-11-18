"""Download a revision-pinned SWE-bench split; do not execute repository code."""

import argparse
from collections import Counter
from datetime import datetime, timezone
import hashlib
from importlib.metadata import version
import json
from pathlib import Path


PUBLIC_FIELDS = ("instance_id", "repo", "base_commit", "problem_statement")
REQUIRED = PUBLIC_FIELDS + ("patch", "test_patch", "FAIL_TO_PASS", "PASS_TO_PASS")


def test_ids(value):
    """Accept both historical JSON strings and current list-valued columns."""
    parsed = json.loads(value) if isinstance(value, str) else value
    if not isinstance(parsed, list) or not all(isinstance(x, str) for x in parsed):
        raise ValueError("Test IDs must be a list of strings")
    return parsed


def validate(row):
    missing = set(REQUIRED) - row.keys()
    if missing:
        raise ValueError(f"Missing fields: {sorted(missing)}")
    for field in PUBLIC_FIELDS + ("patch", "test_patch"):
        if not isinstance(row[field], str) or not row[field].strip():
            raise ValueError(f"Empty or non-string field: {field}")
    commit = row["base_commit"]
    if len(commit) != 40 or any(c not in "0123456789abcdef" for c in commit.lower()):
        raise ValueError("base_commit must be a full 40-character SHA")
    if not test_ids(row["FAIL_TO_PASS"]):
        raise ValueError("FAIL_TO_PASS must not be empty")
    test_ids(row["PASS_TO_PASS"])


def public_task(row):
    return {field: row[field] for field in PUBLIC_FIELDS}


def jsonl_bytes(rows):
    return ("".join(json.dumps(row, ensure_ascii=False) + "\n" for row in rows)).encode("utf-8")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dataset", default="SWE-bench/SWE-bench_Lite")
    parser.add_argument("--split", choices=("dev", "test"), default="dev")
    parser.add_argument("--revision", default="main", help="Resolved to an immutable SHA before loading")
    parser.add_argument("--output", type=Path, default=Path("data"))
    args = parser.parse_args()

    # Lazy imports keep --help and schema validation usable without SDK packages.
    from datasets import load_dataset
    from huggingface_hub import HfApi

    root = args.output.resolve()
    slug = args.dataset.rsplit("/", 1)[-1].lower().replace("swe-bench_", "")
    name = f"{slug}-{args.split}"
    paths = {
        "public": root / "public" / name / "tasks.jsonl",
        "private": root / "private" / name / "oracle.jsonl",
        "manifest": root / "manifests" / f"{name}.json",
    }
    for path in paths.values():
        if path.exists():
            parser.error(f"Refusing to overwrite {path}; use a fresh --output directory")

    info = HfApi().dataset_info(args.dataset, revision=args.revision)
    revision = info.sha
    if not revision:
        raise RuntimeError("Dataset revision could not be resolved")
    dataset = load_dataset(args.dataset, split=args.split, revision=revision)
    rows = list(dataset)
    if not rows:
        raise ValueError("Empty dataset split")
    seen = set()
    for row in rows:
        validate(row)
        if row["instance_id"] in seen:
            raise ValueError(f"Duplicate instance: {row['instance_id']}")
        seen.add(row["instance_id"])

    payloads = {
        "public": jsonl_bytes(public_task(row) for row in rows),
        "private": jsonl_bytes(rows),
    }
    manifest = {
        "schema_version": 1,
        "dataset": args.dataset,
        "revision": revision,
        "requested_revision": args.revision,
        "split": args.split,
        "downloaded_at": datetime.now(timezone.utc).isoformat(),
        "status": "schema_validated",
        "count": len(rows),
        "repositories": dict(sorted(Counter(row["repo"] for row in rows).items())),
        "instance_ids": sorted(seen),
        "packages": {name: version(name) for name in ("datasets", "huggingface_hub")},
        "files": {
            key: {
                "path": paths[key].relative_to(root).as_posix(),
                "sha256": hashlib.sha256(value).hexdigest(),
            }
            for key, value in payloads.items()
        },
        "note": "Schema checked only. No environment, oracle or test execution validated.",
    }
    # Validate everything before writing; never silently reuse an existing export.
    for key, payload in payloads.items():
        paths[key].parent.mkdir(parents=True, exist_ok=True)
        with paths[key].open("xb") as handle:
            handle.write(payload)
    paths["manifest"].parent.mkdir(parents=True, exist_ok=True)
    with paths["manifest"].open("x", encoding="utf-8") as handle:
        json.dump(manifest, handle, ensure_ascii=False, indent=2)
        handle.write("\n")
    print(json.dumps({"count": len(rows), "revision": revision,
                      "manifest": str(paths["manifest"])}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
