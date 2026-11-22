"""Create an Admin import-upgrade file for the staged Guardian delivery workflow."""

import argparse
import json
import sys
from copy import deepcopy
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app.agent_specs.admin_bundle import compile_bundle, contract_compatibility
from app.agent_specs.guardian_contracts import (
    MENTOR_REVIEW_ID,
    direct_mentor_workflow,
    mentor_distance_evidence,
    mentor_latency_trial,
    parent_workflow,
    simplify_mentor_review,
    stage_mentor_review,
)


def upgrade(
    record, *, simplify=False, direct=False, parent=False, latency_trial=False,
    low_effort_trial=False, crop_trial=False, distance_evidence=False, distance_low_effort=False,
):
    bundle = deepcopy(record["bundle"])
    if compile_bundle(bundle).digest != record["digest"]:
        raise ValueError("source digest mismatch")
    if distance_evidence or distance_low_effort:
        mentor_distance_evidence(bundle["files"], low_effort=distance_low_effort)
    elif latency_trial or low_effort_trial or crop_trial:
        mentor_latency_trial(bundle["files"])
        if crop_trial:
            bundle["files"]["agents/tutoring.stem-extract.json"]["models"][0]["guardian_crop_handoff"] = True
        if low_effort_trial:
            model = bundle["files"]["agents/tutoring.blueprint-planner.json"]["models"][0]
            model["guardian_t1_reasoning_effort"] = "low"
    elif parent:
        files = bundle["files"]
        path = "workflows/guardian-mentor.json"
        if path not in files or f"gates/{MENTOR_REVIEW_ID}.json" in files:
            raise ValueError("guardian parent upgrade requires a direct mentor workflow")
        files[path] = parent_workflow()
    elif direct:
        direct_mentor_workflow(bundle["files"])
    elif simplify:
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
    modes = parser.add_mutually_exclusive_group()
    modes.add_argument("--latency-trial", action="store_true", help="Build the Guardian scope and English direct-route candidate")
    modes.add_argument("--crop-trial", action="store_true", help="Try extractor-selected image crops in Guardian primary solves")
    modes.add_argument("--low-effort-trial", action="store_true", help="Request low effort only for Guardian T1 primary solves")
    modes.add_argument("--distance-evidence", action="store_true", help="Anchor Guardian paper-tape formulas to the actual image crop")
    modes.add_argument("--distance-low-effort", action="store_true", help="Build the same distance evidence candidate with low effort in Guardian T1")
    modes.add_argument("--parent", action="store_true", help="Link the direct mentor to its staged blueprint")
    modes.add_argument("--simplify", action="store_true")
    modes.add_argument("--direct", action="store_true")
    args = parser.parse_args()
    args.output.write_text(
        json.dumps(
            upgrade(
                json.loads(args.source.read_text()),
                simplify=args.simplify,
                direct=args.direct,
                parent=args.parent, latency_trial=args.latency_trial, low_effort_trial=args.low_effort_trial, crop_trial=args.crop_trial,
                distance_evidence=args.distance_evidence, distance_low_effort=args.distance_low_effort,
            ),
            ensure_ascii=False,
        )
    )
