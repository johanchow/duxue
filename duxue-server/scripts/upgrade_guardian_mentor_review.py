"""Create an Admin import-upgrade file for the staged Guardian delivery workflow."""

import argparse
import json
import sys
from copy import deepcopy
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app.agent_specs.admin_bundle import compile_bundle, contract_compatibility
from app.agent_specs.guardian_contracts import (
    simplify_mentor_review,
    stage_mentor_review,
    MENTOR_REVIEW_ID,
)


def upgrade(record, *, simplify=False):
    bundle = deepcopy(record["bundle"])
    if compile_bundle(bundle).digest != record["digest"]:
        raise ValueError("source digest mismatch")
    if simplify:
        simplify_mentor_review(bundle["files"])
    elif f"gates/{MENTOR_REVIEW_ID}.json" not in bundle["files"]:
        stage_mentor_review(bundle["files"])
    bundle["compatibility"] = contract_compatibility(bundle["files"])
    return {
        **record,
        "bundle": bundle,
        "kind": "draft",
        "digest": compile_bundle(bundle).digest,
        "migration_source": {
            key: record[key]
            for key in ("kind", "id", "digest", "revision")
            if key in record
        },
    }


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source", type=Path)
    parser.add_argument("output", type=Path)
    parser.add_argument("--simplify", action="store_true")
    args = parser.parse_args()
    args.output.write_text(
        json.dumps(
            upgrade(json.loads(args.source.read_text()), simplify=args.simplify),
            ensure_ascii=False,
        )
    )
