"""Transaction-free SolutionBlueprint planner & deterministic pre-verification.

All LLM calls and isolated engine calls execute BEFORE any database write transaction.
Any milestone whose `verify_request` fails or returns non-equal/error is downgraded to
`verification_status="unverified"` so model hallucinations never become gold anchors.
"""

from __future__ import annotations

import hashlib
from typing import Protocol

from app.application.ports.math_engine import MathEnginePort, MathInput
from app.contexts.tutoring.domain.blueprint import (
    Approach,
    Milestone,
    ProblemGroupContext,
    ProblemInvariant,
    SolutionBlueprint,
)


class BlueprintPlannerPort(Protocol):
    def plan(
        self,
        *,
        content: str,
        images: list[str],
        prior_group: dict | None = None,
        grade_stage: str | None = None,
    ) -> dict | None: ...


class QwenBlueprintPlannerGateway(BlueprintPlannerPort):
    def __init__(self, settings_obj=None):
        self._settings = settings_obj

    def plan(
        self,
        *,
        content: str,
        images: list[str],
        prior_group: dict | None = None,
        grade_stage: str | None = None,
    ) -> dict | None:
        from app.agent_specs.contexts import build_context
        from app.agent_specs.definitions import load_definitions
        from app.agent_specs.gaokao_contracts import PLANNER_ID
        from app.infrastructure.ai import components

        defs = load_definitions()
        if PLANNER_ID not in defs.units:
            return None
        spec = components.COMPONENTS.get(PLANNER_ID)
        if spec is None:
            return None
        payload = {
            "problem_text": content,
            "grade_stage": grade_stage,
            "prior_group_context": prior_group,
        }
        try:
            user = build_context(PLANNER_ID, payload=payload, images=images)
            return components.invoke_agent_component(
                spec=spec, user=user, settings_obj=self._settings
            ).unwrap()
        except Exception:  # noqa: BLE001 - blueprint failure must gracefully degrade to ordinary tutoring
            return None


def _verify_milestone_anchor(engine: MathEnginePort | None, raw_ms: dict) -> str:
    check_kind = raw_ms.get("check_kind") or "conceptual_rubric"
    if check_kind == "conceptual_rubric":
        return "not_applicable"
    verify_req = raw_ms.get("verify_request")
    if engine is None or not isinstance(verify_req, dict):
        return "unverified"
    try:
        req = MathInput.model_validate(verify_req)
        res = engine.execute(req)
    except Exception:  # noqa: BLE001
        return "unverified"
    if res.status != "ok":
        return "unverified"
    if res.checked_scope == "equivalence":
        return "verified" if res.verdict == "equal" else "unverified"
    return "verified" if res.result is not None else "unverified"


def build_verified_blueprint_and_group(
    planner: BlueprintPlannerPort | None,
    engine: MathEnginePort | None,
    *,
    content: str,
    images: list[str],
    prior_group: ProblemGroupContext | None = None,
    grade_stage: str | None = None,
) -> tuple[SolutionBlueprint | None, ProblemGroupContext | None]:
    if planner is None:
        return None, prior_group
    raw = planner.plan(
        content=content,
        images=images,
        prior_group=prior_group.to_dict() if prior_group else None,
        grade_stage=grade_stage,
    )
    if not isinstance(raw, dict):
        return None, prior_group

    digest = hashlib.sha256(
        (content + "|" + ",".join(str(len(img or "")) for img in images)).encode("utf-8")
    ).hexdigest()[:32]

    verified_approaches: list[Approach] = []
    for raw_app in (raw.get("approaches") or [])[:3]:
        if not isinstance(raw_app, dict) or not raw_app.get("id") or not raw_app.get("name"):
            continue
        milestones: list[Milestone] = []
        for idx, raw_ms in enumerate((raw_app.get("milestones") or [])[:8]):
            if not isinstance(raw_ms, dict) or not raw_ms.get("id") or not raw_ms.get("goal"):
                continue
            v_status = _verify_milestone_anchor(engine, raw_ms)
            parsed = Milestone.from_dict(
                {
                    **raw_ms,
                    "verification_status": v_status,
                    "student_status": "in_progress" if idx == 0 and not verified_approaches else "pending",
                }
            )
            milestones.append(parsed)
        if milestones:
            verified_approaches.append(
                Approach(
                    id=str(raw_app["id"])[:32],
                    name=str(raw_app["name"])[:120],
                    milestones=tuple(milestones),
                )
            )

    blueprint: SolutionBlueprint | None = None
    if verified_approaches:
        constraints = tuple(
            ProblemInvariant.from_dict(c)
            for c in (raw.get("implicit_constraints") or [])[:8]
            if isinstance(c, dict) and c.get("id") and c.get("expression")
        )
        first_app = verified_approaches[0]
        blueprint = SolutionBlueprint(
            subject=str(raw.get("subject") or "general")[:32],
            problem_digest=digest,
            approaches=tuple(verified_approaches),
            implicit_constraints=constraints,
            active_approach_id=first_app.id,
            active_milestone_id=first_app.milestones[0].id,
        )

    group = prior_group
    stem_ref = raw.get("shared_stem_ref")
    if isinstance(stem_ref, str) and stem_ref.strip() and group is None:
        group = ProblemGroupContext(
            shared_stem_ref=stem_ref.strip()[:64],
            shared_stem_summary=str(raw.get("shared_stem_summary") or content[:500])[:1000],
            subproblem_label=(
                str(raw["subproblem_label"]).strip()[:32]
                if isinstance(raw.get("subproblem_label"), str) and raw["subproblem_label"].strip()
                else None
            ),
        )

    return blueprint, group
