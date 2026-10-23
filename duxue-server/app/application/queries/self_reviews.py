"""Authorized, current-version views of Ward-confirmed self reviews."""

from __future__ import annotations

from datetime import date, timedelta

from fastapi import HTTPException
from sqlalchemy.orm import Session

from app.infrastructure.persistence.models import SelfReview, SelfReviewAspect, SelfReviewVersion


def get_recent_self_reviews(
    db: Session, *, actor_id: str, actor_role: str, ward_id: str,
    use_case: str, end_date: date, days: int = 5,
    task_ref: str | None = None, topic_ref: str | None = None,
    item_budget: int = 8,
    char_budget: int = 2000,
) -> list[dict]:
    if actor_role != "ward" or actor_id != ward_id:
        raise HTTPException(403, "review is visible only to its Ward")
    if use_case not in {"ward_history", "reflection", "tutoring", "planning"}:
        raise HTTPException(422, "unsupported review use case")
    if not 1 <= days <= 30 or not 1 <= item_budget <= 20 or not 100 <= char_budget <= 8000:
        raise HTTPException(422, "invalid review query budget")
    reviews = db.query(SelfReview).filter(
        SelfReview.ward_id == ward_id,
        SelfReview.review_date >= end_date - timedelta(days=days - 1),
        SelfReview.review_date <= end_date,
    ).order_by(SelfReview.review_date.desc()).all()
    result: list[dict] = []
    used_chars = 0
    for review in reviews:
        version = db.query(SelfReviewVersion).filter_by(
            review_id=review.id, version=review.version,
        ).one_or_none()
        if version is None:
            continue  # Legacy feeling-only rows are not confirmed six-dimensional reviews.
        aspects = db.query(SelfReviewAspect).filter_by(
            review_id=review.id, review_version=review.version,
        ).order_by(SelfReviewAspect.created_at).all()
        for aspect in aspects:
            if use_case == "planning" and aspect.dimension != "next_intent":
                continue
            if task_ref and aspect.task_ref != task_ref:
                continue
            if topic_ref and aspect.topic_ref != topic_ref:
                continue
            row_chars = len(aspect.statement) + len(aspect.source_quote)
            if used_chars + row_chars > char_budget:
                continue
            result.append({
                "review_id": review.id, "version": review.version,
                "review_date": review.review_date.isoformat(),
                "aspect_id": aspect.id, "dimension": aspect.dimension,
                "statement": aspect.statement, "source_quote": aspect.source_quote,
                "task_ref": aspect.task_ref, "topic_ref": aspect.topic_ref,
                "source": "ward_self_report",
            })
            used_chars += row_chars
            if len(result) >= item_budget:
                return result
    return result
