"""Create an Admin import-upgrade file for the staged Guardian delivery workflow."""

import argparse
import json
import sys
from copy import deepcopy
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app.agent_specs.admin_bundle import compile_bundle, contract_compatibility
from app.agent_specs.guardian_contracts import MENTOR_REVIEW_ID, stage_mentor_review


def upgrade(record):
    bundle = deepcopy(record["bundle"])
    if compile_bundle(bundle).digest != record["digest"]:
        raise ValueError("source digest mismatch")
    if f"gates/{MENTOR_REVIEW_ID}.json" not in bundle["files"]:
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
    args = parser.parse_args()
    args.output.write_text(
        json.dumps(upgrade(json.loads(args.source.read_text())), ensure_ascii=False)
    )
