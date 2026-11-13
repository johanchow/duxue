"""Upgrade a complete Admin export into an import-upgrade draft; never publish."""

import argparse
import copy
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app.agent_specs.admin_bundle import compile_bundle, contract_compatibility, digest
from app.agent_specs.observation_contracts import (
    FILES,
    IDS,
    LEGACY_FILES,
    provision,
    workflow_documents,
)


def upgrade(record, *, model=None, activity_prompt=None, support_prompt=None):
    if digest(record["bundle"]) != record["digest"]:
        raise ValueError("source digest mismatch")
    bundle = copy.deepcopy(record["bundle"])
    old_metadata = {name:{key:doc[key] for key in ("display_name","description") if key in doc} for name,doc in bundle["files"].items()}
    previous = {
        identifier: bundle["files"].get(f"agents/{identifier}.json")
        for identifier in IDS
    }
    # Only registered extension files may be migrated. All unrelated configuration
    # must still pass the existing complete baseline compiler, unchanged.
    for name in FILES | LEGACY_FILES:
        bundle["files"].pop(name, None)
    bundle["compatibility"] = contract_compatibility(bundle["files"])
    compile_bundle(bundle)
    for identifier, prompt in [
        ("behavior.visible-activity", activity_prompt),
        ("behavior.support-opportunity", support_prompt),
    ]:
        old = previous[identifier]
        if old is None:
            if not model or not prompt:
                raise ValueError(
                    "new observation agents require explicit model and both prompts"
                )
            doc = provision(identifier, model=model, prompt=prompt)
        else:
            doc = old
            if model:
                doc["models"][0]["name"] = model
            if prompt:
                doc["prompt"]["template"] = prompt
        bundle["files"][f"agents/{identifier}.json"] = doc
    bundle["files"].update(workflow_documents())
    for name,metadata in old_metadata.items():
        if name in bundle["files"]:
            bundle["files"][name].update(metadata)
    bundle["compatibility"] = contract_compatibility(bundle["files"])
    compiled = compile_bundle(bundle)
    return {
        **record,
        "kind": "draft",
        "bundle": bundle,
        "digest": compiled.digest,
        "migration_source": {
            key: record[key]
            for key in ("id", "digest", "kind", "revision")
            if key in record
        },
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source", type=Path)
    parser.add_argument("output", type=Path)
    parser.add_argument("--model")
    parser.add_argument("--activity-prompt", type=Path)
    parser.add_argument("--support-prompt", type=Path)
    args = parser.parse_args()
    record = upgrade(
        json.loads(args.source.read_text()),
        model=args.model,
        activity_prompt=args.activity_prompt.read_text()
        if args.activity_prompt
        else None,
        support_prompt=args.support_prompt.read_text() if args.support_prompt else None,
    )
    args.output.write_text(json.dumps(record, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
