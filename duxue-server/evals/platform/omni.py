"""Reviewable projection of the pinned local batch into hosted Dataset items."""

from __future__ import annotations

import argparse
import json
from collections import Counter
from pathlib import Path

from evals.local.dataset import load, sha, validate
from evals.platform.protocol import convert, digest, hydrate

KNOWN_ISSUES = {
    "omni-english-010": [
        "Original USER question includes an answer and explanation; requires input-isolation review."
    ],
    "omni-geography-015": [
        "Question refers to a passage absent from visible text and original image; requires material-completeness review."
    ],
}


def content_digest(row):
    metadata = {k: v for k, v in row["metadata"].items() if k != "migration_digest"}
    return digest([row["input"], row["expected_output"], metadata])


def assert_unchanged(remote, proposed):
    """Never overwrite a Dataset item edited after an earlier import."""
    actual = {
        "input": remote["input"],
        "expected_output": remote.get("expectedOutput", remote.get("expected_output")),
        "metadata": remote.get("metadata", {}),
    }
    if (
        remote.get("status") != "ACTIVE"
        or actual["metadata"].get("migration_digest")
        != proposed["metadata"]["migration_digest"]
        or content_digest(actual) != content_digest(proposed)
    ):
        raise ValueError(
            "remote item differs; refusing overwrite: "
            + proposed["metadata"]["case_id"]
        )


def project(root):
    root = Path(root)
    if validate(root)["acceptance_status"] != "passed":
        raise ValueError("incomplete local batch")
    manifest, tasks = load(root)
    rows = []
    for entry, record in tasks:
        raw = json.loads((root / entry["record"]).read_text())
        source = json.loads((root / entry["source_record"]).read_text())
        row = convert(raw, entry["dataset"], execution_target=entry["execution_target"])
        row["dataset_name"] = entry["dataset"]
        row["input"].update(
            execution_target=entry["execution_target"], assets=entry["assets"]
        )
        row["metadata"].update(
            batch=manifest["batch"],
            subject=entry["subject"],
            level=entry["level"],
            eval_category=entry["category"],
            execution_target=entry["execution_target"],
            family_id=entry["family_id"],
            split=entry["split"],
            scenario=entry["scenario"],
            level_review=entry["level_review"],
            source_revision=manifest["source_revision"],
            source_uid=source["uid"],
            source_record_sha256=source["record_sha256"],
            source_record=entry["source_record"],
            local_record_sha256=sha(root / entry["record"]),
            local_manifest_sha256=sha(root / "manifest.json"),
            known_issues=KNOWN_ISSUES.get(record.id, []),
            review_required=record.id in KNOWN_ISSUES,
            grading_status="uncalibrated",
        )
        row["metadata"]["migration_digest"] = content_digest(row)
        from types import SimpleNamespace

        hydrate(SimpleNamespace(**row))
        rows.append(row)
    return rows


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--data", type=Path, default=Path("evals/data/omni-edu-v1"))
    p.add_argument("--out", type=Path, required=True)
    args = p.parse_args(argv)
    rows = project(args.data)
    args.out.mkdir(parents=True, exist_ok=False)
    chunks = []
    for dataset in sorted({r["dataset_name"] for r in rows}):
        part = []
        for row in [r for r in rows if r["dataset_name"] == dataset]:
            item = {
                "id": row["id"],
                "input": row["input"],
                "expectedOutput": row["expected_output"],
                "metadata": row["metadata"],
                "status": "ACTIVE",
            }
            if (
                part
                and len(json.dumps(part + [item], ensure_ascii=False).encode()) > 55000
            ):
                chunks.append((dataset, part))
                part = []
            part.append(item)
        if part:
            chunks.append((dataset, part))
    index = []
    for i, (dataset, items) in enumerate(chunks):
        name = f"payload-{i:03}.json"
        (args.out / name).write_text(json.dumps(items, ensure_ascii=False) + "\n")
        index.append({"dataset": dataset, "file": name, "items": len(items)})
    (args.out / "plan.json").write_text(
        json.dumps(
            {"counts": dict(Counter(r["dataset_name"] for r in rows)), "chunks": index},
            ensure_ascii=False,
            indent=2,
        )
        + "\n"
    )
    print(json.dumps({"out": str(args.out), "tasks": len(rows), "chunks": len(index)}))


if __name__ == "__main__":
    main()
