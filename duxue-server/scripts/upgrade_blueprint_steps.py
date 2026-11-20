"""Create an Admin import-upgrade artifact from a verified release or working draft."""

import argparse
import json
import sys
from copy import deepcopy
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app.agent_specs.admin_bundle import compile_bundle, contract_compatibility
from app.agent_specs.blueprint_steps import upgrade_files


def upgrade(record, *, ward_max_output_tokens=None):
    bundle = deepcopy(record["bundle"])
    if compile_bundle(bundle).digest != record["digest"]:
        raise ValueError("source digest mismatch")
    upgrade_files(bundle["files"], ward_max_output_tokens=ward_max_output_tokens)
    bundle["compatibility"] = contract_compatibility(bundle["files"])
    return {
        **record,
        "bundle": bundle,
        "kind": "draft",
        "digest": compile_bundle(bundle).digest,
        "migration_source": {
            k: record[k] for k in ("kind", "id", "digest", "revision") if k in record
        },
    }


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source", type=Path)
    parser.add_argument("output", type=Path)
    parser.add_argument("--ward-max-output-tokens", type=int, choices=(4096, 8192),
                        help="Override the Ward turn budget for a local comparison")
    args = parser.parse_args()
    args.output.write_text(
        json.dumps(upgrade(json.loads(args.source.read_text()), ward_max_output_tokens=args.ward_max_output_tokens), ensure_ascii=False)
    )
