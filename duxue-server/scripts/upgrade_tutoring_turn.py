"""Upgrade a verified Admin export to executable turn paths."""

import argparse
import json
import sys
from copy import deepcopy
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app.agent_specs.admin_bundle import compile_bundle, contract_compatibility


def upgrade(record):
    original = record["bundle"]
    if compile_bundle(original).digest != record["digest"]:
        raise ValueError("source digest mismatch")
    result = {
        **deepcopy(record),
        "kind": "draft",
        "migration_source": {
            k: record[k] for k in ("kind", "id", "digest", "revision") if k in record
        },
    }
    bundle = result["bundle"]
    flow = bundle["files"]["workflows/tutoring.json"]
    if flow.get("execution") == "turn_graph":
        return result
    flow["execution"] = "turn_graph"
    flow["rollout_percent"] = 0
    patch = json.loads(
        (Path(__file__).parent / "config_upgrades/tutoring_turn.json").read_text()
    )
    flow["nodes"].extend(patch["add_nodes"])
    flow["edges"] = patch["edges"]
    bundle["compatibility"] = contract_compatibility(bundle["files"])
    result["digest"] = compile_bundle(bundle).digest
    return result


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source", type=Path)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    args.output.write_text(
        json.dumps(upgrade(json.loads(args.source.read_text())), ensure_ascii=False)
    )
