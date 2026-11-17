"""Application Ports & Repository mapping for the ProblemSolving Domain."""

from __future__ import annotations

from datetime import timezone
from typing import Protocol

from sqlalchemy.orm import Session

from app.contexts.problem_solving.domain.dossier import (
    ProblemDossier,
    ScoringPoint,
    StructuredStem,
)
from app.contexts.tutoring.domain.blueprint import Approach, ProblemInvariant
from app.infrastructure.persistence.models import ProblemDossierRecord, now


class ProblemSolverModelPort(Protocol):
    def extract_stem(
        self, *, text: str, images: list[str], independent_reread: bool = False
    ) -> dict | None: ...

    def solve_route(
        self, *, stem: StructuredStem, images: list[str], route_hint: str
    ) -> dict | None: ...


class QwenProblemSolverGateway(ProblemSolverModelPort):
    """Uses the registered `tutoring.blueprint-planner` component without student history."""

    def __init__(self, settings_obj=None):
        self._settings = settings_obj

    def _invoke(self, payload: dict, images: list[str]) -> dict | None:
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
        try:
            user = build_context(PLANNER_ID, payload=payload, images=images)
            return components.invoke_agent_component(
                spec=spec, user=user, settings_obj=self._settings
            ).unwrap()
        except Exception:  # noqa: BLE001
            return None

    def extract_stem(
        self, *, text: str, images: list[str], independent_reread: bool = False
    ) -> dict | None:
        raw = self._invoke(
            {
                "mode": "independent_stem_reread" if independent_reread else "stem_extract",
                "problem_text": text,
            },
            images,
        )
        if not isinstance(raw, dict):
            return None
        return {
            "subject": str(raw.get("subject") or "general"),
            "raw_text": str(raw.get("shared_stem_summary") or raw.get("raw_text") or text),
            "subproblems": list(raw.get("subproblems") or []),
            "diagram_summary": str(raw.get("diagram_summary") or ""),
        }

    def solve_route(
        self, *, stem: StructuredStem, images: list[str], route_hint: str
    ) -> dict | None:
        return self._invoke(
            {
                "mode": "independent_solve",
                "route_hint": route_hint,
                "stem": stem.to_dict(),
                "problem_text": stem.raw_text,
            },
            images,
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

    def find_reusable(self, *, fingerprint: str, ward_id: str) -> ProblemDossier | None:
        # Check authoritative bank first, then ward-private cache. Never cross-read other wards!
        bank_row = (
            self.db.query(ProblemDossierRecord)
            .filter_by(fingerprint=fingerprint, scope="bank", status="ready")
            .order_by(ProblemDossierRecord.updated_at.desc())
            .first()
        )
        if bank_row is not None:
            return self.to_domain(bank_row)
        ward_row = (
            self.db.query(ProblemDossierRecord)
            .filter_by(fingerprint=fingerprint, scope="ward", owner_ward_id=ward_id)
            .order_by(ProblemDossierRecord.updated_at.desc())
            .first()
        )
        return self.to_domain(ward_row) if ward_row is not None else None

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
