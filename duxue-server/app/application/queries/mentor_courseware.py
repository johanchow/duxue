"""CQRS Read Queries for Tutoring.MentorCourseware."""

from __future__ import annotations

from typing import Any
from uuid import UUID

from app.application.commands.mentor_courseware import (
    CoursewareForbiddenError,
    CoursewareNotFoundError,
)
from app.application.ports.mentor_courseware import (
    MentorCoursewareRepository,
    ProductionStatusStore,
)


class MentorCoursewareQueryService:
    """Read-only projection service; never mutates aggregate state."""

    def __init__(
        self,
        repo: MentorCoursewareRepository,
        status_store: ProductionStatusStore,
    ) -> None:
        self._repo = repo
        self._status_store = status_store

    def get_view(self, *, courseware_id: UUID, guardian_id: UUID) -> dict[str, Any]:
        cw = self._repo.get(courseware_id)
        if cw is None:
            raise CoursewareNotFoundError(courseware_id)
        if cw.guardian_id != guardian_id:
            raise CoursewareForbiddenError()

        cur = cw.current_version
        baseline = cw.current_baseline

        verification_summary = (
            {
                "baseline_hash": baseline.baseline_hash,
                "confidence": baseline.confidence,
                "summary_answer": baseline.summary_answer,
                "stem_text": baseline.stem_text,
                "subject": baseline.subject,
                "final_answers": list(baseline.final_answers),
            }
            if baseline is not None
            else None
        )

        current_version_dto = (
            {
                "version_no": cur.version_no,
                "parent_version_no": cur.parent_version_no,
                "baseline_hash": cur.baseline_hash,
                "change_summary": cur.change_summary,
                "verification_status": cur.verification_status,
                "methodology_key": cur.methodology_key,
                "outline": [
                    {
                        "step_id": s.step_id,
                        "title": s.title,
                        "pedagogical_role": s.pedagogical_role,
                        "has_visual": s.visual_spec is not None,
                    }
                    for s in cur.steps
                ],
                "steps": [s.to_dict() for s in cur.steps],
                "created_at": cur.created_at,
            }
            if cur is not None
            else None
        )

        return {
            "courseware_id": str(cw.courseware_id),
            "status": cw.status,
            "state_revision": cw.state_revision,
            "verification_summary": verification_summary,
            "current_version": current_version_dto,
            "history_controls": {
                "cursor": cw.cursor,
                "total_versions": len(cw.versions),
                "can_undo": cw.cursor > 0,
                "can_redo": 0 <= cw.cursor < len(cw.versions) - 1,
                "version_summaries": [
                    {
                        "version_no": v.version_no,
                        "change_summary": v.change_summary,
                        "verification_status": v.verification_status,
                    }
                    for v in cw.versions
                ],
            },
            "active_revision_pending": cw.active_revision is not None,
            "active_revision_id": cw.active_revision.revision_id if cw.active_revision else None,
            "failure_reason": cw.failure_reason,
            "degraded_text": cw.degraded_text,
        }

    def get_status(self, *, courseware_id: UUID, guardian_id: UUID) -> dict[str, Any]:
        cw = self._repo.get(courseware_id)
        if cw is None:
            raise CoursewareNotFoundError(courseware_id)
        if cw.guardian_id != guardian_id:
            raise CoursewareForbiddenError()
        snap = self._status_store.get_status(courseware_id)
        if snap is not None:
            return snap.to_dict()
        return {
            "courseware_id": str(courseware_id),
            "stage": "ready" if cw.status == "ready" else ("failed" if cw.status == "failed" else "queued"),
            "message": "课件已就绪" if cw.status == "ready" else ("制作失败" if cw.status == "failed" else "正在排队准备"),
            "revision_id": cw.active_revision.revision_id if cw.active_revision else None,
            "updated_at": cw.created_at,
            "error_code": cw.failure_reason,
        }
