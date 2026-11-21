"""Application Commands for ProblemSolving: RequestSolve, ConfirmStem, ExecuteDossierSolve."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, replace

from sqlalchemy.orm import Session

from app.application.ports.math_engine import MathEnginePort, MathInput
from app.application.ports.problem_solving import (
    ProblemSolverModelPort,
    QwenProblemSolverGateway,
    SqlProblemDossierRepository,
)
from app.application.workflows.blueprint_planner import verify_milestone_anchor_detail
from app.contexts.problem_solving.domain.dossier import (
    AnchorVerifyState,
    DifficultyTier,
    DossierConfidence,
    DossierConfidencePolicy,
    DossierStatus,
    ProblemDossier,
    RouteComparisonStatus,
    ScoringPoint,
    StructuredStem,
    compare_critical_conditions,
    image_request_fingerprint,
)
from app.contexts.tutoring.domain.blueprint import (
    Approach,
    Milestone,
    ProblemInvariant,
)
from app.infrastructure.ai.client import remaining_model_time
from app.infrastructure.ai.errors import ModelTimeBudgetExceeded
from app.infrastructure.ai.parallel_routes import collect_solve_routes
from app.infrastructure.persistence.models import now, uid


def _default_enqueue(dossier_id: str, images: list[str] | None = None) -> None:
    from app.workers.solving_tasks import enqueue_solve_dossier

    enqueue_solve_dossier(dossier_id, images=images or [])


class RequestSolveCommand:
    """Idempotent request to obtain or schedule a `ward`-scoped `ProblemDossier`."""

    def __init__(
        self,
        db: Session,
        *,
        enqueue_fn: Callable[..., None] | None = None,
        solver_version: str = "dossier.v1",
    ):
        self.db = db
        self.repo = SqlProblemDossierRepository(db)
        self.enqueue_fn = enqueue_fn
        self.solver_version = solver_version

    def _dispatch(self, dossier_id: str, images: list[str]) -> None:
        fn = self.enqueue_fn or _default_enqueue
        try:
            fn(dossier_id, images)
        except TypeError:
            fn(dossier_id)

    def execute(
        self,
        *,
        ward_id: str,
        text: str,
        images: list[str] | None = None,
        subject: str = "general",
        initial_tier: str = "T1",
    ) -> ProblemDossier:
        from app.agent_specs.image_refs import image_ref

        imgs = [img for img in (images or []) if isinstance(img, str) and img]
        refs = [image_ref(img) for img in imgs]
        stem = StructuredStem(subject=subject, raw_text=text.strip()[:4000])
        current_time = now()
        if refs:
            fingerprint = image_request_fingerprint(stem, refs)
            existing = self.repo.find_image_request(ward_id=ward_id, fingerprint=fingerprint)
        else:
            existing = self.repo.find_reusable(stem=stem, ward_id=ward_id)
        if existing is not None:
            if existing.status in {"ready", "low_confidence"}:
                return existing
            if existing.status == "pending" and not existing.can_acquire_solve_lease(current_time):
                return existing
            # Expired pending lease or failed -> renew lease and re-enqueue
            if existing.scope == "ward":
                renewed = existing.renew_lease(current_time)
                saved = self.repo.save(renewed)
                self._dispatch(saved.dossier_id, imgs)
                return saved

        # Student uploads are ALWAYS hard-locked to `scope="ward"` to prevent PII/answer contamination!
        created = ProblemDossier.create_pending(
            dossier_id=uid(),
            scope="ward",
            owner_ward_id=ward_id,
            stem=stem,
            tier="T2" if initial_tier == "T2" else "T1",
            solver_version=self.solver_version,
            now_at=current_time,
        )
        if refs:
            created = replace(created, fingerprint=fingerprint, evidence={"request_image_refs": refs})
        saved = self.repo.save(created)
        self._dispatch(saved.dossier_id, imgs)
        return saved


class ConfirmStemCommand:
    """Student confirms or corrects ambiguous stem conditions -> bumps stem_version and re-solves."""

    def __init__(self, db: Session, *, enqueue_fn: Callable[..., None] | None = None):
        self.db = db
        self.repo = SqlProblemDossierRepository(db)
        self.enqueue_fn = enqueue_fn

    def execute(
        self,
        *,
        ward_id: str,
        dossier_id: str,
        confirmed_text: str,
        images: list[str] | None = None,
    ) -> ProblemDossier:
        dossier = self.repo.get(dossier_id)
        if dossier is None:
            raise ValueError("dossier_not_found")
        if dossier.scope != "ward" or dossier.owner_ward_id != ward_id:
            raise PermissionError("unauthorized_dossier_mutation")
        updated = dossier.confirm_stem(confirmed_text, now_at=now())
        saved = self.repo.save(updated)
        fn = self.enqueue_fn or _default_enqueue
        try:
            fn(saved.dossier_id, list(images or []))
        except TypeError:
            fn(saved.dossier_id)
        return saved


@dataclass(frozen=True)
class _ParsedRoute:
    approaches: tuple[Approach, ...] = ()
    invariants: tuple[ProblemInvariant, ...] = ()
    scoring_points: tuple[ScoringPoint, ...] = ()
    final_answers: dict[str, str] = None  # type: ignore[assignment]
    uncertain: bool = True
    anchor_state: AnchorVerifyState = "unknown"
    contradictions: tuple[dict, ...] = ()

    def __post_init__(self):
        if self.final_answers is None:
            object.__setattr__(self, "final_answers", {})


def _call_solve_route(
    solver: ProblemSolverModelPort,
    *,
    stem: StructuredStem,
    images: list[str],
    route_hint: str,
    feedback: dict | None = None,
) -> dict | None:
    """Invoke solver route with single in-place retry on timeout (never escalate tier)."""
    for attempt in range(2):
        try:
            if feedback is not None:
                try:
                    return solver.solve_route(
                        stem=stem, images=images, route_hint=route_hint, feedback=feedback
                    )
                except TypeError:
                    return solver.solve_route(stem=stem, images=images, route_hint=route_hint)
            return solver.solve_route(stem=stem, images=images, route_hint=route_hint)
        except ModelTimeBudgetExceeded:
            raise
        except TimeoutError:
            if attempt == 0:
                continue
            return None
    return None


def _parse_and_verify_route(
    engine: MathEnginePort | None, raw: dict | None
) -> _ParsedRoute:
    if not isinstance(raw, dict):
        return _ParsedRoute()
    approaches: list[Approach] = []
    contradictions: list[dict] = []
    for raw_app in (raw.get("approaches") or [])[:3]:
        if not isinstance(raw_app, dict) or not raw_app.get("id") or not raw_app.get("name"):
            continue
        milestones: list[Milestone] = []
        for raw_ms in (raw_app.get("milestones") or [])[:8]:
            if not isinstance(raw_ms, dict) or not raw_ms.get("id") or not raw_ms.get("goal"):
                continue
            detail = verify_milestone_anchor_detail(engine, raw_ms)
            v_status = detail["status"]
            if v_status == "contradicted":
                contradictions.append(
                    {
                        "milestone_id": str(raw_ms["id"])[:32],
                        "goal": str(raw_ms["goal"])[:200],
                        "canonical_target": raw_ms.get("canonical_target"),
                        "reason": detail["reason"],
                        "engine_result": detail["engine_result"],
                    }
                )
            milestones.append(
                Milestone.from_dict({**raw_ms, "verification_status": v_status})
            )
        if milestones:
            approaches.append(
                Approach(
                    id=str(raw_app["id"])[:32],
                    name=str(raw_app["name"])[:120],
                    milestones=tuple(milestones),
                )
            )
    invariants = tuple(
        ProblemInvariant.from_dict(c)
        for c in (raw.get("implicit_constraints") or [])[:8]
        if isinstance(c, dict) and c.get("id") and c.get("expression")
    )
    scoring = tuple(
        ScoringPoint.from_dict(sp)
        for sp in (raw.get("scoring_points") or [])[:10]
        if isinstance(sp, dict) and sp.get("id") and sp.get("step")
    )
    raw_finals = raw.get("final_answers")
    finals: dict[str, str] = {}
    if isinstance(raw_finals, dict):
        for k, v in list(raw_finals.items())[:10]:
            if isinstance(v, (str, int, float)) and str(v).strip():
                finals[str(k)[:32]] = str(v).strip()[:500]
    uncertain = bool(raw.get("uncertain", False))
    apps_tuple = tuple(approaches)
    anchor_state = DossierConfidencePolicy.classify_anchor_verification(apps_tuple)
    return _ParsedRoute(
        approaches=apps_tuple,
        invariants=invariants,
        scoring_points=scoring,
        final_answers=finals,
        uncertain=uncertain,
        anchor_state=anchor_state,
        contradictions=tuple(contradictions),
    )


def _compare_answers(
    engine: MathEnginePort | None, ans_a: dict[str, str], ans_b: dict[str, str]
) -> RouteComparisonStatus:
    """Three-state route comparison: consistent | contradicted | incomparable."""
    if not ans_a or not ans_b or set(ans_a) != set(ans_b):
        return "incomparable"
    saw_incomparable = False
    for key, va in ans_a.items():
        vb = ans_b[key]
        if va.strip() == vb.strip():
            continue
        if engine is None:
            saw_incomparable = True
            continue
        try:
            res = engine.execute(MathInput(op="equivalent", args={"left": va, "right": vb}))
            if res.status == "ok" and not res.conditions:
                if res.verdict == "equal":
                    continue
                if res.verdict == "not_equal":
                    return "contradicted"
            saw_incomparable = True
        except Exception:  # noqa: BLE001
            saw_incomparable = True
    return "incomparable" if saw_incomparable else "consistent"


def _answers_agree(
    engine: MathEnginePort | None, ans_a: dict[str, str], ans_b: dict[str, str]
) -> bool:
    return _compare_answers(engine, ans_a, ans_b) == "consistent"


@dataclass(frozen=True)
class VerifiedSolution:
    """Stateless, persistence-free verified problem solution produced outside DB transactions.

    Shared by `ExecuteDossierSolveCommand` (which persists it onto a `ProblemDossier`
    aggregate root) and adult `Guardian` mentor explanations (zero student-domain writes).
    """

    stem: StructuredStem
    tier: DifficultyTier
    status: DossierStatus
    confidence: DossierConfidence
    approaches: tuple[Approach, ...] = ()
    invariants: tuple[ProblemInvariant, ...] = ()
    scoring_points: tuple[ScoringPoint, ...] = ()
    final_answers: dict[str, str] = None  # type: ignore[assignment]
    evidence: dict = None  # type: ignore[assignment]
    failure_reason: str | None = None

    def __post_init__(self):
        if self.final_answers is None:
            object.__setattr__(self, "final_answers", {})
        if self.evidence is None:
            object.__setattr__(self, "evidence", {})

    @classmethod
    def from_dossier(cls, dossier: ProblemDossier) -> VerifiedSolution:
        return cls(
            stem=dossier.stem,
            tier=dossier.tier,
            status=dossier.status,
            confidence=dossier.confidence,
            approaches=dossier.approaches,
            invariants=dossier.invariants,
            scoring_points=dossier.scoring_points,
            final_answers=dict(dossier.final_answers),
            evidence=dict(dossier.evidence),
        )

    def mentor_projection(self) -> dict:
        return {
            "status": self.status,
            "confidence": self.confidence,
            "tier": self.tier,
            "stem": self.stem.to_dict(),
            "implicit_constraints": [inv.to_dict() for inv in self.invariants],
            "approaches": [app.to_dict() for app in self.approaches],
            "scoring_points": [sp.to_dict() for sp in self.scoring_points],
            "verified_final_answers": dict(self.final_answers)
            if self.status == "ready" and self.confidence == "high"
            else {},
            "candidate_final_answers": dict(self.final_answers)
            if self.confidence != "high"
            else {},
            "evidence": dict(self.evidence),
        }


def _reread_stem(solver, stem: StructuredStem, images) -> tuple[StructuredStem, bool]:
    """Attempt one independent read and stop if usable evidence is unavailable."""
    try:
        reread_raw = solver.extract_stem(text=stem.raw_text, images=images, independent_reread=True)
    except TimeoutError:
        remaining_model_time()  # Preserve the enclosing turn deadline if it expired.
        reread_raw = None
    if not isinstance(reread_raw, dict) or not str(reread_raw.get("raw_text") or "").strip():
        return replace(stem, needs_student_confirmation=True, reread_verified=False,
                       disputed_conditions=("reread_unavailable",)), True
    reread_stem = StructuredStem.from_dict(reread_raw)
    agreed, disputed_reasons = compare_critical_conditions(stem, reread_stem)
    if agreed:
        return replace(stem, reread_verified=True, needs_student_confirmation=False), False
    return (
        replace(
            stem,
            reread_verified=False,
            needs_student_confirmation=True,
            disputed_conditions=disputed_reasons or (reread_stem.raw_text[:200],),
        ),
        True,
    )


def _finalize_single_route(
    *,
    stem: StructuredStem,
    parsed: _ParsedRoute,
    used_backup: bool = False,
    prior_contradictions: tuple[dict, ...] = (),
) -> VerifiedSolution:
    if not parsed.approaches:
        return VerifiedSolution(
            stem=stem,
            tier="T1",
            status="failed",
            confidence="low",
            evidence={
                "route_count": 1,
                "anchor_verification": parsed.anchor_state,
                "used_backup": used_backup,
                "prior_contradictions": list(prior_contradictions),
            },
            failure_reason="no_valid_approaches_produced",
        )
    completeness = DossierConfidencePolicy.evaluate_subproblem_completeness(
        stem, parsed.final_answers
    )
    confidence = DossierConfidencePolicy.evaluate_confidence(
        bank_matched=False,
        route_count=1,
        comparison="consistent",
        approaches=parsed.approaches,
        stem_disputed=False,
        subproblems_complete=completeness["complete"],
    )
    if parsed.uncertain:
        confidence = "low"
    status: DossierStatus = (
        "ready" if confidence in {"high", "medium"} and parsed.approaches else "low_confidence"
    )
    return VerifiedSolution(
        stem=stem,
        tier="T1",
        status=status,
        confidence=confidence,
        approaches=parsed.approaches,
        invariants=parsed.invariants,
        scoring_points=parsed.scoring_points,
        final_answers=parsed.final_answers,
        evidence={
            "route_count": 1,
            "anchor_verification": parsed.anchor_state,
            "all_anchors_verified": parsed.anchor_state == "verified",
            "subproblem_completeness": completeness,
            "used_backup": used_backup,
            "prior_contradictions": list(prior_contradictions),
            "contradictions": list(parsed.contradictions),
        },
    )


def _finalize_t2_routes(
    *,
    stem: StructuredStem,
    parsed_1: _ParsedRoute,
    parsed_2: _ParsedRoute,
    math_engine: MathEnginePort | None,
    stem_disputed: bool = False,
) -> VerifiedSolution:
    eliminated_route: str | None = None
    # Contradiction elimination: if one route is deterministically falsified and the other is not,
    # discard the falsified route and evaluate the surviving route independently.
    r1_bad = parsed_1.anchor_state == "contradicted"
    r2_bad = parsed_2.anchor_state == "contradicted"
    if r1_bad and not r2_bad and parsed_2.approaches:
        eliminated_route = "T2_algebraic"
        surviving = parsed_2
        completeness = DossierConfidencePolicy.evaluate_subproblem_completeness(
            stem, surviving.final_answers
        )
        confidence = DossierConfidencePolicy.evaluate_confidence(
            bank_matched=False,
            route_count=1,
            comparison="incomparable",
            approaches=surviving.approaches,
            stem_disputed=stem_disputed,
            subproblems_complete=completeness["complete"],
        )
        status: DossierStatus = (
            "ready" if confidence in {"high", "medium"} else "low_confidence"
        )
        return VerifiedSolution(
            stem=stem,
            tier="T2",
            status=status,
            confidence=confidence,
            approaches=surviving.approaches,
            invariants=surviving.invariants,
            scoring_points=surviving.scoring_points,
            final_answers=surviving.final_answers,
            evidence={
                "route_count": 1,
                "comparison": "incomparable",
                "routes_consistent": False,
                "eliminated_route": eliminated_route,
                "anchor_verification": surviving.anchor_state,
                "subproblem_completeness": completeness,
                "stem_disputed": stem_disputed,
            },
        )
    if r2_bad and not r1_bad and parsed_1.approaches:
        eliminated_route = "T2_alternative"
        surviving = parsed_1
        completeness = DossierConfidencePolicy.evaluate_subproblem_completeness(
            stem, surviving.final_answers
        )
        confidence = DossierConfidencePolicy.evaluate_confidence(
            bank_matched=False,
            route_count=1,
            comparison="incomparable",
            approaches=surviving.approaches,
            stem_disputed=stem_disputed,
            subproblems_complete=completeness["complete"],
        )
        status = "ready" if confidence in {"high", "medium"} else "low_confidence"
        return VerifiedSolution(
            stem=stem,
            tier="T2",
            status=status,
            confidence=confidence,
            approaches=surviving.approaches,
            invariants=surviving.invariants,
            scoring_points=surviving.scoring_points,
            final_answers=surviving.final_answers,
            evidence={
                "route_count": 1,
                "comparison": "incomparable",
                "routes_consistent": False,
                "eliminated_route": eliminated_route,
                "anchor_verification": surviving.anchor_state,
                "subproblem_completeness": completeness,
                "stem_disputed": stem_disputed,
            },
        )

    comparison = _compare_answers(math_engine, parsed_1.final_answers, parsed_2.final_answers)
    merged_apps = list(parsed_1.approaches)
    if comparison == "consistent" and parsed_2.approaches:
        existing_ids = {a.id for a in merged_apps}
        for alt_app in parsed_2.approaches:
            alt_id = (
                alt_app.id
                if alt_app.id not in existing_ids
                else f"alt_{alt_app.id}"[:32]
            )
            merged_apps.append(replace(alt_app, id=alt_id))
    chosen_apps = tuple(merged_apps[:3]) or parsed_2.approaches
    chosen_invs = parsed_1.invariants or parsed_2.invariants
    chosen_sps = parsed_1.scoring_points or parsed_2.scoring_points
    chosen_finals = parsed_1.final_answers or parsed_2.final_answers

    if not chosen_apps:
        return VerifiedSolution(
            stem=stem,
            tier="T2",
            status="failed",
            confidence="low",
            evidence={
                "route_count": 0,
                "comparison": comparison,
                "stem_disputed": stem_disputed,
            },
            failure_reason="no_valid_approaches_produced",
        )

    active_routes = int(bool(parsed_1.approaches)) + int(bool(parsed_2.approaches))
    completeness = DossierConfidencePolicy.evaluate_subproblem_completeness(
        stem, chosen_finals
    )
    confidence = DossierConfidencePolicy.evaluate_confidence(
        bank_matched=False,
        route_count=active_routes,
        comparison=comparison,
        approaches=chosen_apps,
        stem_disputed=stem_disputed,
        subproblems_complete=completeness["complete"],
    )
    status = (
        "ready"
        if confidence in {"high", "medium"} and chosen_apps
        else "low_confidence"
    )
    return VerifiedSolution(
        stem=stem,
        tier="T2",
        status=status,
        confidence=confidence,
        approaches=chosen_apps,
        invariants=chosen_invs,
        scoring_points=chosen_sps,
        final_answers=chosen_finals,
        evidence={
            "route_count": active_routes,
            "comparison": comparison,
            "routes_consistent": comparison == "consistent",
            "eliminated_route": eliminated_route,
            "anchor_verification": DossierConfidencePolicy.classify_anchor_verification(chosen_apps),
            "subproblem_completeness": completeness,
            "stem_disputed": stem_disputed,
        },
    )


def solve_and_verify_problem(
    *,
    stem: StructuredStem,
    images: list[str] | None = None,
    solver: ProblemSolverModelPort,
    math_engine: MathEnginePort | None = None,
    initial_tier: DifficultyTier = "T1",
    allow_t2_escalation: bool = True,
    question: str | None = None,
) -> VerifiedSolution:
    """Pure out-of-transaction solving & deterministic verification pipeline.

    T1 and T2 are strictly separated (no T1 -> T2 escalation):
    - T1: single route + 4-state deterministic verification; if `contradicted`, optional on-demand
      reread for images (short-circuit on dispute) then heterogeneous backup solver.
    - T2: parallel heterogeneous dual routes + 4-state verification + contradiction elimination +
      3-state comparison.
    """
    imgs = [img for img in (images or []) if isinstance(img, str) and img]
    tier: DifficultyTier = "T2" if initial_tier == "T2" else "T1"

    from app.agent_specs.blueprint_steps import EXTRACT
    from app.agent_specs.definitions import load_definitions

    if EXTRACT in load_definitions().units:
        return execute_blueprint(
            stem=stem,
            images=imgs,
            solver=solver,
            math_engine=math_engine,
            tier=tier,
            allow_upgrade=allow_t2_escalation,
            question=question,
        )

    # On-demand reread only when image stem was explicitly flagged unclear
    if imgs and stem.needs_student_confirmation and not stem.reread_verified:
        stem, disputed = _reread_stem(solver, stem, imgs)
        if disputed:
            return VerifiedSolution(
                stem=stem,
                tier=tier,
                status="low_confidence",
                confidence="low",
                evidence={"stem_disputed": True, "short_circuited": True},
            )

    if tier == "T1":
        raw_t1 = _call_solve_route(solver, stem=stem, images=imgs, route_hint="T1")
        if isinstance(raw_t1, dict) and raw_t1.get("subject"):
            stem = replace(stem, subject=str(raw_t1["subject"])[:32])
        parsed_t1 = _parse_and_verify_route(math_engine, raw_t1)
        has_t1_candidate = isinstance(raw_t1, dict) and bool(parsed_t1.approaches or parsed_t1.final_answers)
        if has_t1_candidate and parsed_t1.anchor_state != "contradicted":
            return _finalize_single_route(stem=stem, parsed=parsed_t1, used_backup=False)
        # Contradicted on image problem -> on-demand reread first to check misread digits
        if parsed_t1.anchor_state == "contradicted" and imgs and not stem.reread_verified:
            stem, disputed = _reread_stem(solver, stem, imgs)
            if disputed:
                return VerifiedSolution(
                    stem=stem,
                    tier="T1",
                    status="low_confidence",
                    confidence="low",
                    evidence={
                        "stem_disputed": True,
                        "short_circuited": True,
                        "prior_contradictions": list(parsed_t1.contradictions),
                    },
                )
        raw_backup = _call_solve_route(
            solver,
            stem=stem,
            images=imgs,
            route_hint="T1_backup",
            feedback=(
                {"contradictions": list(parsed_t1.contradictions)}
                if parsed_t1.contradictions
                else None
            ),
        )
        parsed_backup = _parse_and_verify_route(math_engine, raw_backup)
        return _finalize_single_route(
            stem=stem,
            parsed=parsed_backup,
            used_backup=True,
            prior_contradictions=parsed_t1.contradictions,
        )

    routes = collect_solve_routes(("T2_algebraic", "T2_alternative"), lambda hint: _call_solve_route(
        solver, stem=stem, images=imgs, route_hint=hint))
    raw_r1, raw_r2 = routes.get("T2_algebraic"), routes.get("T2_alternative")
    parsed_1 = _parse_and_verify_route(math_engine, raw_r1)
    parsed_2 = _parse_and_verify_route(math_engine, raw_r2)
    result = _finalize_t2_routes(
        stem=stem,
        parsed_1=parsed_1,
        parsed_2=parsed_2,
        math_engine=math_engine,
        stem_disputed=False,
    )
    timeouts = [hint for hint in ("T2_algebraic", "T2_alternative") if hint not in routes]
    return replace(result, evidence={**result.evidence, "timed_out_routes": timeouts})



def execute_blueprint(
    *,
    stem,
    images,
    solver,
    math_engine,
    tier="T1",
    allow_upgrade=True,
    question=None,
    bank_lookup=None,
    workflow_spec=None,
    allow_language_direct=False,
):
    """Run the pinned topology; workers with a prepared stem resume at selection."""
    from app.agent_specs import blueprint_steps as steps
    from app.agent_specs.catalog import executing_node, load_catalog
    from app.agent_specs.runtime import GateDecision, execute_workflow

    _ = allow_upgrade  # Retained for backward-compatible signature; T1->T2 escalation removed.
    solution: VerifiedSolution | None = None
    disputed = False
    reread_origin: str | None = None
    route_outputs: dict[str, dict | None] = {}
    parsed_t1: _ParsedRoute | None = None
    parsed_backup: _ParsedRoute | None = None
    parsed_t2: tuple[_ParsedRoute, _ParsedRoute] | None = None

    def extract(state):
        nonlocal stem, tier, solution
        raw = solver.extract_stem(
            text=question, images=images, independent_reread=False
        )
        if isinstance(raw, dict):
            stem = StructuredStem.from_dict(raw)
            tier = raw.get("tier") or "T1"
            if tier == "T0" and not raw.get("needs_student_confirmation"):
                solution = VerifiedSolution(
                    stem=stem, tier="T0", status="ready", confidence="medium"
                )
        else:
            tier = "T1"
        if allow_language_direct and isinstance(raw, dict) and raw.get("target_scope"):
            state["target_scope"] = raw["target_scope"]
        language_direct = (
            allow_language_direct and images and tier == "T1" and isinstance(raw, dict)
            and raw.get("guardian_task") == "english_writing" and stem.subject == "english"
            and raw.get("needs_student_confirmation") is False
            and bool(stem.raw_text.strip())
        )
        if language_direct:
            # A compact passage locator is not a bank fingerprint or verified answer.
            state["mentor_language"] = True
            solution = VerifiedSolution(stem=stem, tier="T1", status="low_confidence", confidence="low")
        if solution is None and bank_lookup and not stem.needs_student_confirmation and (not images or isinstance(raw, dict)):
            hit = bank_lookup(stem=stem)
            if hit and hit.scope == "bank" and hit.status == "ready":
                solution = VerifiedSolution.from_dossier(hit)
        return {"tier": tier, "extracted": isinstance(raw, dict)}

    def choose(state):
        nonlocal reread_origin
        if state.get("mentor_language"):
            branch = "mentor_language"
        elif solution is not None:
            branch = "complete"
        elif images and stem.needs_student_confirmation and not stem.reread_verified:
            reread_origin = "select"
            branch = "reread"
        elif tier == "T2":
            branch = "complex"
        else:
            branch = "ordinary"
        state["branch"] = branch
        return GateDecision("allow", branch)

    def reread(state):
        nonlocal stem, disputed
        stem, disputed = _reread_stem(solver, stem, images)
        return {"verified": stem.reread_verified, "disputed": disputed}

    def reread_check(state):
        nonlocal solution
        if disputed:
            solution = VerifiedSolution(
                stem=stem,
                tier="T2" if tier == "T2" else "T1",
                status="low_confidence",
                confidence="low",
                evidence={
                    "stem_disputed": True,
                    "short_circuited": True,
                    "reread_origin": reread_origin,
                },
            )
            branch = "disputed"
        elif reread_origin == "verify":
            branch = "backup"
        else:
            branch = "resume_select"
        state["branch"] = branch
        return GateDecision("allow", branch)

    def solve_primary(state):
        node = executing_node.get()[1]
        hint = {
            steps.node_id("ordinary"): "T1",
            steps.node_id("primary"): "T2_algebraic",
        }[node]
        raw = _call_solve_route(solver, stem=stem, images=images, route_hint=hint)
        if hint.startswith("T2_"):
            return {"route_hint": hint, "route": raw}
        route_outputs[hint] = raw
        return {"route_hint": hint, "candidate": isinstance(raw, dict)}

    def solve_backup(state):
        node = executing_node.get()[1]
        hint = {
            steps.node_id("backup"): "T1_backup",
            steps.node_id("alternative"): "T2_alternative",
        }[node]
        feedback = (
            {"contradictions": list(parsed_t1.contradictions)}
            if hint == "T1_backup" and parsed_t1 and parsed_t1.contradictions
            else None
        )
        raw = _call_solve_route(
            solver, stem=stem, images=images, route_hint=hint, feedback=feedback
        )
        if hint.startswith("T2_"):
            return {"route_hint": hint, "route": raw}
        route_outputs[hint] = raw
        return {"route_hint": hint, "candidate": isinstance(raw, dict)}

    def verify_t1(state):
        nonlocal stem, parsed_t1, reread_origin
        raw_t1 = route_outputs.get("T1")
        if isinstance(raw_t1, dict) and raw_t1.get("subject"):
            stem = replace(stem, subject=str(raw_t1["subject"])[:32])
        parsed_t1 = _parse_and_verify_route(math_engine, raw_t1)
        has_t1_candidate = isinstance(raw_t1, dict) and bool(parsed_t1.approaches or parsed_t1.final_answers)
        if not has_t1_candidate:
            branch = "backup"
        elif parsed_t1.anchor_state == "contradicted":
            if images and not stem.reread_verified:
                reread_origin = "verify"
                branch = "reread"
            else:
                branch = "backup"
        else:
            branch = parsed_t1.anchor_state  # verified | not_applicable | unknown
        state["branch"] = branch
        return GateDecision("allow", branch)

    def verify_backup(state):
        nonlocal parsed_backup
        parsed_backup = _parse_and_verify_route(
            math_engine, route_outputs.get("T1_backup")
        )
        return GateDecision("allow", parsed_backup.anchor_state)

    def verify_t2(state):
        nonlocal parsed_t2
        def read_branch(key):
            result = state["results"].get(steps.node_id(key))
            return _parse_and_verify_route(math_engine, result.data.get("route") if result else None)

        p1, p2 = read_branch("primary"), read_branch("alternative")
        parsed_t2 = (p1, p2)
        comp = _compare_answers(math_engine, p1.final_answers, p2.final_answers)
        return GateDecision("allow", comp)

    def finish(state):
        nonlocal solution
        if solution is None:
            if parsed_t2 is not None:
                solution = _finalize_t2_routes(
                    stem=stem,
                    parsed_1=parsed_t2[0],
                    parsed_2=parsed_t2[1],
                    math_engine=math_engine,
                    stem_disputed=disputed,
                )
                timeouts = [hint for key, hint in (("primary", "T2_algebraic"), ("alternative", "T2_alternative"))
                            if steps.node_id(key) not in state["results"]]
                solution = replace(solution, evidence={**solution.evidence, "timed_out_routes": timeouts})
            elif parsed_backup is not None:
                solution = _finalize_single_route(
                    stem=stem,
                    parsed=parsed_backup,
                    used_backup=True,
                    prior_contradictions=parsed_t1.contradictions if parsed_t1 else (),
                )
            elif parsed_t1 is not None:
                solution = _finalize_single_route(
                    stem=stem,
                    parsed=parsed_t1,
                    used_backup=False,
                )
            else:
                solution = VerifiedSolution(
                    stem=stem,
                    tier="T2" if tier == "T2" else "T1",
                    status="failed",
                    confidence="low",
                    failure_reason="no_valid_approaches_produced",
                )
        if state.get("target_scope"):
            solution = replace(solution, evidence={**solution.evidence, "target_scope": state["target_scope"]})
        return {
            "tier": solution.tier,
            "status": solution.status,
            "confidence": solution.confidence,
        }

    execute_workflow(
        workflow_spec or load_catalog().spec(steps.WORKFLOW_ID),
        handlers={
            steps.EXTRACT: extract,
            steps.ROUTE: choose,
            steps.REREAD: reread,
            steps.REREAD_CHECK: reread_check,
            steps.PLANNER_ID: solve_primary,
            steps.BACKUP: solve_backup,
            steps.VERIFY: verify_t1,
            steps.VERIFY_BACKUP: verify_backup,
            steps.VERIFY_T2: verify_t2,
            steps.FINISH: finish,
        },
        conditions={
            branch: (lambda state, expected=branch: state.get("branch") == expected)
            for branch in steps.CONDITIONS
        },
        entry_node=steps.node_id("select") if question is None else None,
        parallel_runner=collect_solve_routes,
    )
    return solution


class ExecuteDossierSolveCommand:
    """Worker-invoked command executing T1 -> optional T2 heterogeneous consensus outside DB locks."""

    def __init__(
        self,
        db: Session,
        *,
        solver: ProblemSolverModelPort | None = None,
        math_engine: MathEnginePort | None = None,
    ):
        self.db = db
        self.repo = SqlProblemDossierRepository(db)
        self.solver = solver
        self.math_engine = math_engine

    def _solver(self) -> ProblemSolverModelPort:
        return self.solver or QwenProblemSolverGateway(math_engine=self.math_engine)

    def execute(self, *, dossier_id: str, images: list[str] | None = None) -> ProblemDossier:
        dossier = self.repo.get(dossier_id)
        if dossier is None:
            raise ValueError("dossier_not_found")
        if dossier.status == "ready":
            return dossier

        needs_initial_extract = bool(
            images
            and dossier.stem.subject == "general"
            and not dossier.stem.subproblems
            and not dossier.stem.diagram_summary
            and dossier.stem.stem_version == 1
        )
        solution = solve_and_verify_problem(
            stem=dossier.stem,
            images=images,
            solver=self._solver(),
            math_engine=self.math_engine,
            initial_tier=dossier.tier,
            question=dossier.stem.raw_text if needs_initial_extract else None,
        )
        if solution.status == "failed":
            failed = dossier.mark_failed(reason=solution.failure_reason or "solve_failed")
            return self.repo.save(failed)

        settled = dossier.complete_solve(
            approaches=solution.approaches,
            invariants=solution.invariants,
            scoring_points=solution.scoring_points,
            final_answers=solution.final_answers,
            confidence=solution.confidence,
            tier=solution.tier,
            evidence=solution.evidence,
            stem=solution.stem,
        )
        return self.repo.save(settled)
