"""Application Ports & Repository mapping for the ProblemSolving Domain."""

from __future__ import annotations

from datetime import timezone
from typing import Protocol

from sqlalchemy.orm import Session

from app.contexts.problem_solving.domain.dossier import (
    ProblemDossier,
    ScoringPoint,
    StructuredStem,
    compute_stem_fingerprint,
)
from app.contexts.tutoring.domain.blueprint import Approach, ProblemInvariant
from app.infrastructure.ai.errors import ModelTimeBudgetExceeded
from app.infrastructure.persistence.models import ProblemDossierRecord, now


class ProblemSolverModelPort(Protocol):
    def extract_stem(
        self, *, text: str, images: list[str], independent_reread: bool = False
    ) -> dict | None: ...

    def solve_route(
        self,
        *,
        stem: StructuredStem,
        images: list[str],
        route_hint: str,
        feedback: dict | None = None,
    ) -> dict | None: ...


class QwenProblemSolverGateway(ProblemSolverModelPort):
    """Uses registered ProblemSolving components without student history."""

    def __init__(self, settings_obj=None):
        self._settings = settings_obj

    def _invoke(
        self,
        payload: dict,
        images: list[str],
        *,
        use_reread_model: bool = False,
        use_backup_model: bool = False,
        retry_on_timeout: bool = True,
    ) -> dict | None:
        from app.agent_specs.blueprint_steps import BACKUP, EXTRACT, REREAD
        from app.agent_specs.contexts import build_context
        from app.agent_specs.definitions import load_definitions
        from app.agent_specs.gaokao_contracts import PLANNER_ID, REREAD_ID
        from app.infrastructure.ai import components
        from app.infrastructure.ai.errors import ModelGatewayError

        defs = load_definitions()
        if PLANNER_ID not in defs.units:
            return None
        target_component = (
            REREAD_ID if use_reread_model and REREAD_ID in defs.components else PLANNER_ID
        )
        unit = PLANNER_ID
        if EXTRACT in defs.units and payload["mode"] in {"stem_extract", "independent_stem_reread"}:
            unit = REREAD if use_reread_model else EXTRACT
            target_component = unit
        elif use_backup_model and BACKUP in defs.units:
            unit = BACKUP
            target_component = BACKUP
        spec = components.COMPONENTS.get(target_component)
        if spec is None:
            return None
        user = build_context(unit, payload=payload, images=images)
        max_attempts = 2 if retry_on_timeout else 1
        for attempt in range(max_attempts):
            try:
                return components.invoke_agent_component(
                    spec=spec, user=user, settings_obj=self._settings
                ).unwrap()
            except ModelTimeBudgetExceeded:
                raise
            except (TimeoutError, ModelGatewayError) as exc:
                is_retryable = isinstance(exc, TimeoutError) or (
                    isinstance(exc, ModelGatewayError) and str(exc) == "model_transport_error"
                )
                if is_retryable and attempt + 1 < max_attempts:
                    continue
                return None
            except Exception:  # noqa: BLE001
                return None
        return None

    def extract_stem(
        self, *, text: str, images: list[str], independent_reread: bool = False
    ) -> dict | None:
        raw = self._invoke(
            {
                "mode": "independent_stem_reread" if independent_reread else "stem_extract",
                "problem_text": text,
                "extraction_instructions": (
                    "本轮只独立复读关键数值、符号、角标与全部设问，无需求解。"
                    "输出 subject、shared_stem_summary、subproblems、needs_student_confirmation。"
                    if independent_reread
                    else "本轮只转写与分类，无需求解。输出 subject、shared_stem_summary（完整转写题面、数值及设问）、"
                    "subproblems、diagram_summary、needs_student_confirmation，approaches 固定为空数组。"
                    "纯概念、发音或事实查询标为 tier=T0，普通题标为 T1，确需多条独立推导核验的复杂题标为 T2。"
                ),
            },
            images,
            use_reread_model=independent_reread,
        )
        if not isinstance(raw, dict):
            return None
        return {
            "tier": raw.get("tier"),
            "needs_student_confirmation": raw.get("needs_student_confirmation") is True,
            "subject": str(raw.get("subject") or "general"),
            "raw_text": str(raw.get("shared_stem_summary") or raw.get("raw_text") or text),
            "subproblems": list(raw.get("subproblems") or []),
            "diagram_summary": str(raw.get("diagram_summary") or ""),
        }

    def solve_route(
        self,
        *,
        stem: StructuredStem,
        images: list[str],
        route_hint: str,
        feedback: dict | None = None,
    ) -> dict | None:
        payload: dict = {
            "mode": "independent_solve",
            "route_hint": route_hint,
            "route_instructions": "只输出当前路线，保留必要的核验锚点。不要重复转写题面或生成其他路线。",
            "stem": stem.to_dict(),
            "problem_text": stem.raw_text,
        }
        if feedback:
            payload["contradiction_feedback"] = feedback
        return self._invoke(
            payload,
            images,
            use_backup_model=route_hint in {"T1_backup", "T2_alternative"},
        )


def _ensure_utc(dt):
    if dt is None:
        return None
    return dt.replace(tzinfo=timezone.utc) if dt.tzinfo is None else dt


class SqlProblemDossierRepository:
    def __init__(self, db: Session):
        self.db = db

    @staticmethod
    def to_domain(row: ProblemDossierRecord) -> ProblemDossier:
        approaches = tuple(
            Approach.from_dict(a)
            for a in (row.approaches or [])
            if isinstance(a, dict) and a.get("id") and a.get("name")
        )
        invariants = tuple(
            ProblemInvariant.from_dict(i)
            for i in (row.invariants or [])
            if isinstance(i, dict) and i.get("id") and i.get("expression")
        )
        scoring = tuple(
            ScoringPoint.from_dict(sp)
            for sp in (row.scoring_points or [])
            if isinstance(sp, dict) and sp.get("id") and sp.get("step")
        )
        return ProblemDossier(
            dossier_id=row.id,
            fingerprint=row.fingerprint,
            scope=row.scope,  # type: ignore[arg-type]
            owner_ward_id=row.owner_ward_id,
            stem=StructuredStem.from_dict(row.stem or {}),
            subject=row.subject,
            tier=row.tier,  # type: ignore[arg-type]
            approaches=approaches,
            invariants=invariants,
            scoring_points=scoring,
            final_answers=dict(row.final_answers or {}),
            confidence=row.confidence,  # type: ignore[arg-type]
            status=row.status,  # type: ignore[arg-type]
            evidence=dict(row.evidence or {}),
            solver_version=row.solver_version,
            lease_until=_ensure_utc(row.lease_until),
        )

    def get(self, dossier_id: str) -> ProblemDossier | None:
        row = self.db.get(ProblemDossierRecord, dossier_id)
        return self.to_domain(row) if row is not None else None

    def _matching(self, query, stem: StructuredStem) -> ProblemDossier | None:
        fingerprint = compute_stem_fingerprint(stem)
        keys = (fingerprint, compute_stem_fingerprint(stem, legacy=True))
        candidates = query.filter(ProblemDossierRecord.fingerprint.in_(keys)).order_by(
            ProblemDossierRecord.updated_at.desc()
        )
        for row in candidates:
            if compute_stem_fingerprint(StructuredStem.from_dict(row.stem or {})) == fingerprint:
                return self.to_domain(row)
        return None

    def find_bank_ready(self, *, stem: StructuredStem) -> ProblemDossier | None:
        query = self.db.query(ProblemDossierRecord).filter_by(scope="bank", status="ready")
        return self._matching(query, stem)

    def find_reusable(self, *, stem: StructuredStem, ward_id: str) -> ProblemDossier | None:
        bank = self.find_bank_ready(stem=stem)
        if bank is not None:
            return bank
        query = self.db.query(ProblemDossierRecord).filter_by(scope="ward", owner_ward_id=ward_id)
        return self._matching(query, stem)

    def save(self, dossier: ProblemDossier) -> ProblemDossier:
        row = self.db.get(ProblemDossierRecord, dossier.dossier_id)
        if row is None:
            row = ProblemDossierRecord(id=dossier.dossier_id)
            self.db.add(row)
        row.fingerprint = dossier.fingerprint
        row.scope = dossier.scope
        row.owner_ward_id = dossier.owner_ward_id
        row.subject = dossier.subject
        row.tier = dossier.tier
        row.stem = dossier.stem.to_dict()
        row.approaches = [a.to_dict() for a in dossier.approaches]
        row.invariants = [i.to_dict() for i in dossier.invariants]
        row.scoring_points = [sp.to_dict() for sp in dossier.scoring_points]
        row.final_answers = dict(dossier.final_answers)
        row.confidence = dossier.confidence
        row.status = dossier.status
        row.evidence = dict(dossier.evidence)
        row.solver_version = dossier.solver_version
        row.lease_until = dossier.lease_until
        row.updated_at = now()
        self.db.flush()
        return self.to_domain(row)
