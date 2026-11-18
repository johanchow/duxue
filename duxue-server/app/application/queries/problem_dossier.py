"""Authorized CQRS read queries for ProblemSolving (`GetProblemDossier`)."""

from __future__ import annotations

from sqlalchemy.orm import Session

from app.application.ports.problem_solving import SqlProblemDossierRepository
from app.contexts.problem_solving.domain.dossier import ProblemDossier


class GetProblemDossierQuery:
    def __init__(self, db: Session):
        self.repo = SqlProblemDossierRepository(db)

    def find_bank_ready(self, *, fingerprint: str) -> ProblemDossier | None:
        """Read-only lookup strictly restricted to `scope='bank'` and `status='ready'`."""
        return self.repo.find_bank_ready(fingerprint=fingerprint)

    def get_for_ward(self, *, ward_id: str, dossier_id: str) -> ProblemDossier | None:
        dossier = self.repo.get(dossier_id)
        if dossier is None:
            return None
        if dossier.scope == "ward" and dossier.owner_ward_id != ward_id:
            raise PermissionError("unauthorized_ward_dossier_access")
        return dossier

    def tutoring_view(
        self,
        *,
        ward_id: str,
        dossier_id: str | None,
        student_progress: dict[str, str] | None = None,
    ) -> tuple[ProblemDossier | None, dict | None]:
        if not dossier_id:
            return None, None
        dossier = self.get_for_ward(ward_id=ward_id, dossier_id=dossier_id)
        if dossier is None:
            return None, None
        return dossier, dossier.tutoring_projection(student_progress=student_progress)
