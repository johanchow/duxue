"""Read-only Guardian access to scoped teaching evidence."""

from datetime import date
from typing import Annotated

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.api.v1.common import Principal, current_guardian, get_db, owned_ward
from app.application.queries.tutoring_evidence import evidence_detail, list_evidence

router = APIRouter(tags=["tutoring"])


@router.get("/wards/{ward_id}/tutoring-evidence")
def guardian_evidence(
    ward_id: str,
    day: Annotated[date, Query(alias="date")],
    principal: Annotated[Principal, Depends(current_guardian)],
    db: Annotated[Session, Depends(get_db)],
):
    owned_ward(db, principal.user_id, ward_id)
    return list_evidence(db, ward_id, day)


@router.get("/wards/{ward_id}/tutoring-evidence/{problem_id}")
def guardian_evidence_detail(
    ward_id: str,
    problem_id: str,
    day: Annotated[date, Query(alias="date")],
    principal: Annotated[Principal, Depends(current_guardian)],
    db: Annotated[Session, Depends(get_db)],
):
    owned_ward(db, principal.user_id, ward_id)
    return evidence_detail(db, ward_id, day, problem_id)
