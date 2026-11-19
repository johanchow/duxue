"""Run the configured Guardian delivery graph over independently reviewed parts."""

from jsonschema import Draft202012Validator

from app.agent_specs.catalog import executing_node, load_catalog
from app.agent_specs.contexts import build_context
from app.agent_specs.guardian_contracts import (
    MENTOR_BRANCHES,
    MENTOR_DELIVER_ID,
    MENTOR_EXPLAIN_ID,
    MENTOR_REPAIR_ID,
    MENTOR_REVIEW_ID,
    MENTOR_WORKFLOW_ID,
    _sections_schema,
)
from app.agent_specs.runtime import GateDecision, execute_workflow
from app.infrastructure.ai import components
from app.infrastructure.ai.client import model_time_budget, remaining_model_time
from app.infrastructure.ai.errors import ModelGatewayError, ModelTimeBudgetExceeded

_SECTION_SCHEMA = Draft202012Validator(_sections_schema())


def _sections(raw):
    if not _SECTION_SCHEMA.is_valid({"sections": raw}):
        return {}
    parts = {row["id"]: row["content"].strip() for row in raw}
    if len(parts) != len(raw) or not all(
        key.strip() and value for key, value in parts.items()
    ):
        return {}
    return parts


def run_mentor_review(
    *, explain, needs_review, question, images, solution, settings_obj=None
):
    candidate = None
    sections = {}
    approved = {}
    targets = {}
    repaired = {}
    coverage_complete = False
    partial = False
    standalone = False

    def model(unit, payload, *, reserve):
        spec = components.COMPONENTS.get(unit)
        user = build_context(unit, payload=payload, current_images=images)
        try:
            remaining = remaining_model_time()
            if remaining is None:
                return components.invoke_json_component(
                    spec=spec, user=user, settings_obj=settings_obj
                )
            budget = remaining - reserve(remaining)
            if budget <= 0:
                return None
            with model_time_budget(budget):
                result = components.invoke_json_component(
                    spec=spec, user=user, settings_obj=settings_obj
                )
                remaining_model_time()
                return result
        except (ModelGatewayError, ModelTimeBudgetExceeded):
            return None

    def generate(state):
        nonlocal candidate, sections, standalone
        candidate, raw = explain()
        state["branch"] = "skip_review"
        if needs_review(candidate):
            sections = _sections(raw.get("sections"))
            standalone = not sections
            if standalone:
                sections = {"main": candidate.content}
            state["branch"] = "review"
        return {
            "act": candidate.act if candidate else "unavailable",
            "part_ids": list(sections),
        }

    def review(state):
        nonlocal coverage_complete
        recheck = executing_node.get()[1] == "guardian-mentor.recheck"
        current = repaired if recheck else sections
        raw = model(
            MENTOR_REVIEW_ID,
            {
                "question": question,
                "solution": solution,
                "sections": current,
                "scope": "repaired_parts" if recheck else "whole_question",
                "approved_context": approved if recheck else {},
                "visual": candidate.visual.model_dump(mode="json")
                if standalone and not recheck and candidate.visual
                else None,
            },
            reserve=lambda _: 1.5,
        )
        state["branch"] = "finish"
        if raw is None:
            return GateDecision("deny", "review_unavailable")
        rows = {row["id"]: row for row in raw["rows"]}
        if len(rows) != len(raw["rows"]) or set(rows) != set(current):
            return GateDecision("deny", "review_part_ids_mismatch")
        state["part_review"] = {
            "coverage_complete": raw["coverage_complete"],
            "rows": raw["rows"],
        }
        if not recheck:
            coverage_complete = raw["coverage_complete"]
        if not recheck or raw["coverage_complete"]:
            approved.update(
                {
                    key: current[key]
                    for key, row in rows.items()
                    if row["status"] == "pass"
                }
            )
        if not recheck:
            targets.update(
                {
                    key: {"content": current[key], "reason": row["reason"]}
                    for key, row in rows.items()
                    if row["status"] == "wrong" and row["reason"]
                }
            )
            if targets:
                state["branch"] = "repair"
        return GateDecision(
            "allow"
            if raw["coverage_complete"]
            and all(row["status"] == "pass" for row in rows.values())
            else "deny",
            "review_completed",
        )

    def repair(state):
        raw = model(
            MENTOR_REPAIR_ID,
            {
                "question": question,
                "solution": solution,
                "targets": targets,
                "approved_context": approved,
            },
            reserve=lambda remaining: max(5.0, remaining / 3),
        )
        parts = _sections(raw["sections"]) if raw else {}
        if set(parts) == set(targets):
            repaired.update(parts)
        state["branch"] = "review" if repaired else "finish"
        return {"repaired_ids": list(repaired)}

    def deliver(state):
        nonlocal candidate, partial
        if not needs_review(candidate):
            return {"status": "direct" if candidate else "unavailable"}
        if not approved or (standalone and not coverage_complete):
            candidate = None
            return {"status": "unavailable"}
        partial = not coverage_complete or set(approved) != set(sections)
        content = "\n\n".join(approved[key] for key in sections if key in approved)
        if partial:
            content += "\n\n部分小问尚未核对通过，以上为本次可交付的部分。"
        # All delivered text comes from exact reviewed sections. An assembled or
        # repaired answer cannot reuse a diagram from an earlier draft.
        if len(content) > 3600:
            candidate = None
            return {"status": "unavailable", "reason": "reviewed_content_too_long"}
        candidate = candidate.model_copy(
            update={
                "content": content,
                "visual": candidate.visual if standalone and not repaired else None,
            }
        )
        return {
            "status": "partial" if partial else "complete",
            "approved_ids": list(approved),
        }

    execute_workflow(
        load_catalog().spec(MENTOR_WORKFLOW_ID),
        handlers={
            MENTOR_EXPLAIN_ID: generate,
            MENTOR_REVIEW_ID: review,
            MENTOR_REPAIR_ID: repair,
            MENTOR_DELIVER_ID: deliver,
        },
        conditions={
            branch: (lambda state, expected=branch: state.get("branch") == expected)
            for branch in MENTOR_BRANCHES
        },
    )
    return candidate, partial
