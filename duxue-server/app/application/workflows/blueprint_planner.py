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


_NECESSARY_ONLY_CHECK_KINDS = frozenset(
    {"physics_dimension_and_eq", "chemistry_conservation"}
)


def verify_milestone_anchor_detail(engine: MathEnginePort | None, raw_ms: dict) -> dict:
    """Verify a milestone's `canonical_target` deterministically against `verify_request`.

    Returns four-state status:
    - `verified`: verified within engine scope (strength: `sufficient` or `necessary_only`)
    - `contradicted`: deterministic mismatch or counterexample found
    - `not_applicable`: conceptual rubric with no deterministic operator
    - `unknown`: missing engine/request, parse/runtime error, conditions, or inconclusive verdict
    """
    check_kind = raw_ms.get("check_kind") or "conceptual_rubric"
    if check_kind == "conceptual_rubric":
        return {"status": "not_applicable", "strength": "none", "reason": None, "engine_result": None}
    strength = "necessary_only" if check_kind in _NECESSARY_ONLY_CHECK_KINDS else "sufficient"
    verify_req = raw_ms.get("verify_request")
    canonical = raw_ms.get("canonical_target")
    if engine is None or not isinstance(verify_req, dict):
        return {
            "status": "unknown",
            "strength": strength,
            "reason": "engine_or_verify_request_missing",
            "engine_result": None,
        }
    try:
        req = MathInput.model_validate(verify_req)
        res = engine.execute(req)
    except Exception as exc:  # noqa: BLE001
        return {
            "status": "unknown",
            "strength": strength,
            "reason": f"engine_error:{type(exc).__name__}",
            "engine_result": None,
        }
    if res.status != "ok" or res.conditions:
        return {
            "status": "unknown",
            "strength": strength,
            "reason": res.error_code or ("conditional_result" if res.conditions else res.status),
            "engine_result": res.result,
        }
    if res.checked_scope == "equivalence":
        if res.verdict == "equal":
            return {"status": "verified", "strength": strength, "reason": None, "engine_result": res.result}
        if res.verdict == "not_equal":
            return {
                "status": "contradicted",
                "strength": strength,
                "reason": "equivalence_not_equal",
                "engine_result": res.result,
            }
        return {
            "status": "unknown",
            "strength": strength,
            "reason": f"equivalence_{res.verdict}",
            "engine_result": res.result,
        }
    if res.verdict == "not_equal":
        return {
            "status": "contradicted",
            "strength": strength,
            "reason": "counterexample_or_mismatch",
            "engine_result": res.result,
        }
    if res.result is None or not isinstance(canonical, str) or not canonical.strip():
        return {
            "status": "unknown",
            "strength": strength,
            "reason": "missing_result_or_canonical_target",
            "engine_result": res.result,
        }
    target_str = canonical.strip()
    if res.result.strip() == target_str:
        return {"status": "verified", "strength": strength, "reason": None, "engine_result": res.result}
    # For algebraic/value results, check symbolic equivalence between engine result and canonical_target
    if res.checked_scope == "value":
        try:
            eq_req = MathInput(
                op="equivalent",
                args={"left": res.result, "right": target_str},
                symbols=req.symbols,
                assumptions=req.assumptions,
            )
            eq_res = engine.execute(eq_req)
            if eq_res.status == "ok" and not eq_res.conditions:
                if eq_res.verdict == "equal":
                    return {"status": "verified", "strength": strength, "reason": None, "engine_result": res.result}
                if eq_res.verdict == "not_equal":
                    return {
                        "status": "contradicted",
                        "strength": strength,
                        "reason": f"expected_{res.result}_got_{target_str}",
                        "engine_result": res.result,
                    }
            # For symbolic expressions with free variables, `equivalent` returns `unknown` when difference
            # depends on the variable; use deterministic counterexample search to falsify mismatches.
            if req.symbols:
                bounds = {}
                for sym in req.symbols[:3]:
                    name = sym.name if hasattr(sym, "name") else sym.get("name")
                    if name:
                        bounds[name] = [-5, 5]
                if bounds:
                    ce_req = MathInput(
                        op="search_counterexample",
                        args={"relation": f"({res.result}) == ({target_str})", "bounds": bounds},
                        symbols=req.symbols,
                        assumptions=req.assumptions,
                    )
                    ce_res = engine.execute(ce_req)
                    if ce_res.status == "ok" and ce_res.verdict == "not_equal":
                        return {
                            "status": "contradicted",
                            "strength": strength,
                            "reason": f"counterexample:{ce_res.result or f'expected_{res.result}_got_{target_str}'}",
                            "engine_result": res.result,
                        }
        except Exception as exc:  # noqa: BLE001
            return {
                "status": "unknown",
                "strength": strength,
                "reason": f"equivalence_check_error:{type(exc).__name__}",
                "engine_result": res.result,
            }
        return {
            "status": "unknown",
            "strength": strength,
            "reason": "equivalence_inconclusive",
            "engine_result": res.result,
        }
    # Deterministic structured result (e.g. solution set) differs from canonical_target
    return {
        "status": "contradicted",
        "strength": strength,
        "reason": f"expected_{res.result}_got_{target_str}",
        "engine_result": res.result,
    }


def verify_milestone_anchor(engine: MathEnginePort | None, raw_ms: dict) -> str:
    """Return four-state verification status: verified | contradicted | unknown | not_applicable."""
    return verify_milestone_anchor_detail(engine, raw_ms)["status"]


_verify_milestone_anchor = verify_milestone_anchor


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
