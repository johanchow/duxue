"""Dedicated `solving` Celery queue tasks for asynchronous ProblemDossier execution."""

from __future__ import annotations

import logging

from app.application.commands.problem_solving import ExecuteDossierSolveCommand
from app.bootstrap.math_engine import math_engine
from app.infrastructure.persistence.database import SessionLocal

logger = logging.getLogger(__name__)

SOLVING_QUEUE = "solving"
SOLVE_TASK_NAME = "duxue.solve_problem_dossier"


def solve_problem_dossier(dossier_id: str, attachment_keys: list[str] | None = None) -> dict:
    """Worker entrypoint bound to the `solving` queue; never passes raw image bytes through Redis."""
    from app.agent_specs.release_runtime import pin_release

    images: list[str] = []
    db = SessionLocal()
    try:
        from app.infrastructure.persistence.models import ProblemDossierRecord

        row = db.get(ProblemDossierRecord, dossier_id)
        if row is None:
            logger.warning("solve_problem_dossier: dossier %s not found in DB", dossier_id)
            return {"status": "not_found", "dossier_id": dossier_id}
        if attachment_keys and row.owner_ward_id:
            from app.application.queries.run_transcript import current_turn_images

            images = [
                img
                for img in current_turn_images(row.owner_ward_id, attachment_keys)
                if isinstance(img, str) and img
            ]
        with pin_release():
            settled = ExecuteDossierSolveCommand(
                db, math_engine=math_engine()
            ).execute(dossier_id=dossier_id, images=images)
            db.commit()
            return {
                "dossier_id": settled.dossier_id,
                "status": settled.status,
                "confidence": settled.confidence,
                "tier": settled.tier,
            }
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


def enqueue_solve_dossier(
    dossier_id: str,
    *,
    attachment_keys: list[str] | None = None,
    images: list[str] | None = None,  # unused on wire; accepted for signature compatibility
) -> None:
    del images  # Image bytes NEVER enter Redis broker payloads!
    from app.workers.celery_tasks import celery_app

    celery_app.send_task(
        SOLVE_TASK_NAME,
        args=[dossier_id],
        kwargs={"attachment_keys": list(attachment_keys or [])},
        queue=SOLVING_QUEUE,
    )
