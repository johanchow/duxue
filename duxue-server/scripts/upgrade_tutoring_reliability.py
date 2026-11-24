"""Create an Admin import-upgrade artifact for tutoring reliability & streamlined loops.

Upgrades an exported Admin release/draft snapshot idempotently:
1. Streamlines `tutoring.model_loop` (or legacy `tutoring-retry`) from 9 actions to 3 actions
   (`primary -> repair -> finish`).
2. Upgrades `tutoring-blueprint` to v2 mutually exclusive `START` edges (`needs_extract` /
   `has_verified_stem`) plus `select -> finish` (`worksheet_batch`) short-circuit while
   preserving any existing `mentor_language` branch and all component model/prompt settings.
3. Syncs `agents/tutoring.stem-extract.json` prompt to document `worksheet_batch` so the
   `select -> finish` short-circuit can actually fire while preserving model settings.
4. Deduplicates consecutive repeated lines (such as 7x `保持表述准确。`) in
   `gates/tutoring.leak-judge.json` prompt template.
"""

import argparse
import json
import sys
from copy import deepcopy
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app.agent_specs import blueprint_steps
from app.agent_specs.admin_bundle import compile_bundle, contract_compatibility
from app.agent_specs.registrations import LEGACY_LOOP, MODEL_LOOP
from app.agent_specs.subworkflows import compact_model_loop_workflow


def _dedupe_consecutive_lines(text: str) -> str:
    lines = text.splitlines()
    out: list[str] = []
    for line in lines:
        if out and line.strip() and line.strip() == out[-1].strip():
            continue
        out.append(line)
    return "\n".join(out)


def upgrade(record: dict) -> dict:
    bundle = deepcopy(record["bundle"])
    if compile_bundle(bundle).digest != record["digest"]:
        raise ValueError("source digest mismatch")
    files = bundle["files"]

    # 1. Streamline tutoring.model_loop (or legacy tutoring-retry) to 3 actions
    loop_id = MODEL_LOOP if f"workflows/{MODEL_LOOP}.json" in files else LEGACY_LOOP
    loop_key = f"workflows/{loop_id}.json"
    if loop_key in files:
        existing_loop = files[loop_key]
        compact_doc = compact_model_loop_workflow(loop_id)
        if isinstance(existing_loop, dict) and "version" in existing_loop:
            compact_doc["version"] = existing_loop["version"]
        files[loop_key] = compact_doc

    # 2. Upgrade tutoring-blueprint edges to v2 mutually exclusive START + worksheet_batch
    extract_key = f"agents/{blueprint_steps.EXTRACT}.json"
    if blueprint_steps.FLOW_FILE in files and extract_key in files:
        existing_bp = files[blueprint_steps.FLOW_FILE]
        has_mentor_language = any(
            edge.get("condition_id") == "mentor_language"
            for edge in existing_bp.get("edges", [])
        )
        new_bp = blueprint_steps.workflow(
            mentor_language=has_mentor_language,
            v2_edges=True,
        )
        if isinstance(existing_bp, dict) and "version" in existing_bp:
            new_bp["version"] = existing_bp["version"]
        files[blueprint_steps.FLOW_FILE] = new_bp

    # 3. Sync stem-extract prompt with worksheet_batch guidance (preserve models/settings)
    if extract_key in files and f"agents/{blueprint_steps.PLANNER_ID}.json" in files:
        extract_doc = files[extract_key]
        prompt = extract_doc.get("prompt")
        if (
            isinstance(prompt, dict)
            and isinstance(prompt.get("template"), str)
            and "worksheet_batch" not in prompt["template"]
        ):
            scratch = deepcopy(files)
            blueprint_steps.upgrade_files(scratch)
            prompt["template"] = scratch[extract_key]["prompt"]["template"]

    # 4. Clean consecutive duplicate lines in leak-judge prompt (e.g. 7x "保持表述准确。")
    leak_judge_key = "gates/tutoring.leak-judge.json"
    if leak_judge_key in files:
        lj_prompt = files[leak_judge_key].get("prompt")
        if isinstance(lj_prompt, dict) and isinstance(lj_prompt.get("template"), str):
            lj_prompt["template"] = _dedupe_consecutive_lines(lj_prompt["template"])

    bundle["compatibility"] = contract_compatibility(files)
    compiled = compile_bundle(bundle)
    return {
        **record,
        "bundle": bundle,
        "kind": "draft",
        "digest": compiled.digest,
        "migration_source": {
            k: record[k] for k in ("kind", "id", "digest", "revision") if k in record
        },
    }


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source", type=Path)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    result = upgrade(json.loads(args.source.read_text(encoding="utf-8")))
    args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
