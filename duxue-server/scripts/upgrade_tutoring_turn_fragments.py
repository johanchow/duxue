"""Create an Admin import-upgrade artifact splitting `tutoring.turn` prompt.template into
a lean always-on core template + deterministic on-demand system fragments.

Idempotently upgrades an exported Admin release/draft snapshot:
1. Extracts optional/conditional sections from `agents/tutoring.turn.json`'s `prompt.template`
   into named static `prompt.fragments` (`choice_and_submitted`, `learning_search`,
   `visual_delivery_detail`, `pronounce_rules`, `image_review`, `gaokao_blueprint`).
2. Preserves all required capability handshake markers (`[image-review.v1]`, etc.) across
   `template + fragments` so `compile_bundle()` and `require_configuration()` pass cleanly.
3. Recomputes `compatibility` and `digest` for direct import into Admin as a draft.
"""

from __future__ import annotations

import argparse
import json
import sys
from copy import deepcopy
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app.agent_specs.admin_bundle import compile_bundle, contract_compatibility
from app.application.workflows.image_review import require_configuration

_FRAGMENT_SPECS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("visual_delivery_detail", ("[visual-delivery.v1]",)),
    ("gaokao_blueprint", ("[gaokao-blueprint-science.v1]",)),
    (
        "choice_and_submitted",
        ("[choice-guidance.v1]", "[reasoned-choice.v1]", "[submitted-feedback.v4]"),
    ),
    ("learning_search", ("[learning-search.v1]",)),
    ("image_review", ("最高优先级的阶段约定：", "[tutor-visual-discipline.v1]", "[image-review.v1]")),
)


def _split_blocks(template: str) -> list[str]:
    """Split a prompt template into logical marker-headed blocks (handles both blank-line
    and single-newline marker transitions)."""
    markers = (
        "[visual-delivery.v1]",
        "[gaokao-blueprint-science.v1]",
        "[tutor-visual-discipline.v1]",
        "[learning-search.v1]",
        "[choice-guidance.v1]",
        "[reasoned-choice.v1]",
        "[submitted-feedback.v4]",
        "[image-review.v1]",
        "最高优先级的阶段约定：",
    )
    blocks: list[str] = []
    current: list[str] = []
    for raw_line in template.splitlines():
        stripped = raw_line.strip()
        if not stripped:
            if current:
                blocks.append("\n".join(current).strip())
                current = []
            continue
        if any(stripped.startswith(m) for m in markers) and current:
            blocks.append("\n".join(current).strip())
            current = [raw_line]
        else:
            current.append(raw_line)
    if current:
        blocks.append("\n".join(current).strip())
    return [b for b in blocks if b]


def _classify_block(block: str) -> str | None:
    first = block.splitlines()[0].strip()
    for frag_name, prefixes in _FRAGMENT_SPECS:
        if any(first.startswith(prefix) for prefix in prefixes):
            return frag_name
    return None


def split_tutoring_turn_template(template: str) -> tuple[str, dict[str, str]]:
    """Split an existing `tutoring.turn` template into `(lean_core_template, extracted_fragments)`."""
    core_blocks: list[str] = []
    grouped: dict[str, list[str]] = {}
    for block in _split_blocks(template):
        target = _classify_block(block)
        if target is None:
            core_blocks.append(block)
        else:
            grouped.setdefault(target, []).append(block)

    core = "\n\n".join(core_blocks).strip()
    fragments = {name: "\n\n".join(parts).strip() for name, parts in grouped.items() if parts}
    return core, fragments


def upgrade(record: dict) -> dict:
    bundle = deepcopy(record["bundle"])
    if compile_bundle(bundle).digest != record["digest"]:
        raise ValueError("source digest mismatch")
    files = bundle["files"]

    turn_key = "agents/tutoring.turn.json"
    if turn_key not in files:
        raise ValueError(f"missing {turn_key} in bundle")

    doc = files[turn_key]
    prompt = doc.get("prompt")
    if not isinstance(prompt, dict) or not isinstance(prompt.get("template"), str):
        raise ValueError(f"{turn_key}: missing prompt.template")

    lean_core, extracted = split_tutoring_turn_template(prompt["template"])
    prompt["template"] = lean_core
    fragments = prompt.setdefault("fragments", {})
    for frag_name, frag_text in extracted.items():
        if frag_name == "image_review" and frag_name in fragments:
            existing_tmpl = fragments[frag_name].get("template", "").strip()
            merged = (
                frag_text
                if "[image-review.v1]" in frag_text
                else (f"{frag_text}\n\n{existing_tmpl}".strip() if existing_tmpl else frag_text)
            )
            fragments[frag_name] = {
                "id": "tutoring.turn.fragment.image_review",
                "template": merged,
                "variables": {},
            }
        else:
            fragments[frag_name] = {
                "id": f"tutoring.turn.fragment.{frag_name}",
                "template": frag_text,
                "variables": {},
            }

    bundle["compatibility"] = contract_compatibility(files)
    compiled = compile_bundle(bundle)
    require_configuration(bundle)
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
