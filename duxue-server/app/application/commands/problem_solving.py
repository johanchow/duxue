"""Application Commands for ProblemSolving: RequestSolve, ConfirmStem, ExecuteDossierSolve."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import replace

from sqlalchemy.orm import Session

from app.application.ports.math_engine import MathEnginePort, MathInput
from app.application.ports.problem_solving import (
    ProblemSolverModelPort,
    QwenProblemSolverGateway,
    SqlProblemDossierRepository,
)
from app.application.workflows.blueprint_planner import verify_milestone_anchor
from app.contexts.problem_solving.domain.dossier import (
    DossierConfidencePolicy,
    ProblemDossier,
    ScoringPoint,
    StructuredStem,
    compute_stem_fingerprint,
)
from app.contexts.tutoring.domain.blueprint import (
    Approach,
    Milestone,
    ProblemInvariant,
)
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
        imgs = [img for img in (images or []) if isinstance(img, str) and img]
        # Incorporate authorized image count/hashes into stem when text is minimal
        img_tag = f" [images:{len(imgs)}]" if imgs and not text.strip() else ""
        stem = StructuredStem(subject=subject, raw_text=(text.strip() + img_tag)[:4000])
        fp = compute_stem_fingerprint(stem)
        current_time = now()

        existing = self.repo.find_reusable(fingerprint=fp, ward_id=ward_id)
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


def _parse_and_verify_route(
    engine: MathEnginePort | None, raw: dict | None
) -> tuple[tuple[Approach, ...], tuple[ProblemInvariant, ...], tuple[ScoringPoint, ...], dict[str, str], bool]:
    if not isinstance(raw, dict):
        return (), (), (), {}, True
    approaches: list[Approach] = []
    for raw_app in (raw.get("approaches") or [])[:3]:
        if not isinstance(raw_app, dict) or not raw_app.get("id") or not raw_app.get("name"):
            continue
        milestones: list[Milestone] = []
        for raw_ms in (raw_app.get("milestones") or [])[:8]:
            if not isinstance(raw_ms, dict) or not raw_ms.get("id") or not raw_ms.get("goal"):
                continue
            v_status = verify_milestone_anchor(engine, raw_ms)
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
    elif approaches and approaches[0].milestones:
        last_target = approaches[0].milestones[-1].canonical_target
        if last_target:
            finals["main"] = last_target
    uncertain = bool(raw.get("uncertain", False))
    return tuple(approaches), invariants, scoring, finals, uncertain


def _answers_agree(
    engine: MathEnginePort | None, ans_a: dict[str, str], ans_b: dict[str, str]
) -> bool:
    if not ans_a or not ans_b or set(ans_a) != set(ans_b):
        return False
    for key, va in ans_a.items():
        vb = ans_b[key]
        if va.strip() == vb.strip():
            continue
        if engine is None:
            return False
        try:
            res = engine.execute(MathInput(op="equivalent", args={"left": va, "right": vb}))
            if not (res.status == "ok" and res.verdict == "equal" and not res.conditions):
                return False
        except Exception:  # noqa: BLE001
            return False
    return True


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
        return self.solver or QwenProblemSolverGateway()

    def execute(self, *, dossier_id: str, images: list[str] | None = None) -> ProblemDossier:
        dossier = self.repo.get(dossier_id)
        if dossier is None:
            raise ValueError("dossier_not_found")
        if dossier.status == "ready":
            return dossier

        imgs = [img for img in (images or []) if isinstance(img, str) and img]
        solver = self._solver()
        stem = dossier.stem
        tier = dossier.tier

        # Step 1: T1 initial single-route solve (unless already marked T2)
        t1_apps: tuple[Approach, ...] = ()
        t1_invs: tuple[ProblemInvariant, ...] = ()
        t1_sps: tuple[ScoringPoint, ...] = ()
        t1_finals: dict[str, str] = {}
        escalated_reason: str | None = None

        if tier == "T1":
            raw_t1 = solver.solve_route(stem=stem, images=imgs, route_hint="T1")
            if isinstance(raw_t1, dict) and raw_t1.get("subject"):
                stem = replace(stem, subject=str(raw_t1["subject"])[:32])
            t1_apps, t1_invs, t1_sps, t1_finals, t1_uncertain = _parse_and_verify_route(
                self.math_engine, raw_t1
            )
            if DossierConfidencePolicy.should_escalate_t1_to_t2(
                t1_apps, model_uncertain=t1_uncertain
            ):
                tier = "T2"
                escalated_reason = "t1_anchor_unverified_or_uncertain"
            else:
                # T1 all computable anchors verified! Note: single-route without bank match:
                # If all milestones are deterministically verified (`not _has_conceptual`), run 1 fast independent confirmation
                # only when T2 is needed; for T1 standard computation where every step is SymPy-verified, mark `medium` (ready)!
                has_only_verified_math = bool(t1_apps) and all(
                    ms.verification_status == "verified"
                    for app in t1_apps
                    for ms in app.milestones
                )
                conf = "medium" if has_only_verified_math else "low"
                settled = dossier.complete_solve(
                    approaches=t1_apps,
                    invariants=t1_invs,
                    scoring_points=t1_sps,
                    final_answers=t1_finals,
                    confidence=conf,
                    tier="T1",
                    evidence={
                        "route_count": 1,
                        "routes_consistent": True,
                        "all_anchors_verified": has_only_verified_math,
                    },
                    stem=stem,
                )
                return self.repo.save(settled)

        # Step 2: T2 high-difficulty / escalated path -> independent image reread (only when images exist!) + 2 diverse routes
        stem_disputed = False
        if imgs and not stem.reread_verified:
            reread_raw = solver.extract_stem(text=stem.raw_text, images=imgs, independent_reread=True)
            if isinstance(reread_raw, dict):
                reread_stem = StructuredStem.from_dict(reread_raw)
                if compute_stem_fingerprint(reread_stem) == compute_stem_fingerprint(stem):
                    stem = replace(stem, reread_verified=True, needs_student_confirmation=False)
                else:
                    stem_disputed = True
                    stem = replace(
                        stem,
                        reread_verified=False,
                        needs_student_confirmation=True,
                        disputed_conditions=(reread_stem.raw_text[:200],),
                    )

        raw_r1 = solver.solve_route(stem=stem, images=imgs, route_hint="T2_algebraic")
        raw_r2 = solver.solve_route(stem=stem, images=imgs, route_hint="T2_alternative")
        apps_1, invs_1, sps_1, finals_1, _ = _parse_and_verify_route(self.math_engine, raw_r1)
        apps_2, _invs_2, _sps_2, finals_2, _ = _parse_and_verify_route(self.math_engine, raw_r2)

        consistent = _answers_agree(self.math_engine, finals_1, finals_2)
        # Merge distinct method-diverse approaches when consistent so student's alternative method is recognized
        merged_apps = list(apps_1)
        if consistent and apps_2:
            existing_ids = {a.id for a in merged_apps}
            for alt_app in apps_2:
                alt_id = alt_app.id if alt_app.id not in existing_ids else f"alt_{alt_app.id}"[:32]
                merged_apps.append(replace(alt_app, id=alt_id))
        chosen_apps = tuple(merged_apps[:3]) or t1_apps
        chosen_invs = invs_1 or t1_invs
        chosen_sps = sps_1 or t1_sps
        chosen_finals = finals_1 or t1_finals

        if not chosen_apps:
            failed = dossier.mark_failed(reason="no_valid_approaches_produced")
            return self.repo.save(failed)

        confidence = DossierConfidencePolicy.evaluate_confidence(
            bank_matched=False,
            route_count=2,
            routes_consistent=consistent,
            approaches=chosen_apps,
            stem_disputed=stem_disputed,
        )
        settled = dossier.complete_solve(
            approaches=chosen_apps,
            invariants=chosen_invs,
            scoring_points=chosen_sps,
            final_answers=chosen_finals,
            confidence=confidence,
            tier="T2",
            evidence={
                "route_count": 2,
                "routes_consistent": consistent,
                "escalated_reason": escalated_reason,
                "stem_disputed": stem_disputed,
            },
            stem=stem,
        )
        return self.repo.save(settled)
