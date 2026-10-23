"""Evaluation-owned writes for Ward-confirmed daily reviews."""

from __future__ import annotations

from datetime import date

from fastapi import HTTPException
from sqlalchemy.orm import Session

from app.infrastructure.persistence.models import (
    SelfReview, SelfReviewAspect, SelfReviewVersion, Task, now,
)

DIMENSIONS = frozenset({
    "understanding", "strategy", "time_help", "affect", "context", "next_intent",
})


def confirm_self_review(
    db: Session, *, ward_id: str, review_date: date, raw_expression: str,
    aspects: list[dict], expected_version: int | None,
    source_message_id: str | None = None, feeling: str = "",
) -> SelfReview:
    raw = raw_expression.strip()
    if not raw or len(raw) > 4000:
        raise HTTPException(422, "summary must contain 1 to 4000 characters")
    if len(aspects) > 18:
        raise HTTPException(422, "too many summary aspects")
    prepared: list[dict] = []
    for aspect in aspects:
        dimension = aspect.get("dimension")
        statement = str(aspect.get("statement") or "").strip()
        quote = str(aspect.get("source_quote") or "").strip()
        if dimension not in DIMENSIONS or not statement or len(statement) > 300:
            raise HTTPException(422, "invalid summary aspect")
        if not quote or quote not in raw:
            raise HTTPException(422, "aspect quote must occur in Ward expression")
        task_ref = aspect.get("task_ref")
        if task_ref:
            task = db.get(Task, task_ref)
            if task is None or task.ward_id != ward_id:
                raise HTTPException(422, "aspect task does not belong to Ward")
        prepared.append({
            "dimension": dimension, "statement": statement,
            "source_quote": quote, "task_ref": task_ref,
            "topic_ref": aspect.get("topic_ref"),
        })

    review = db.query(SelfReview).filter_by(
        ward_id=ward_id, review_date=review_date,
    ).with_for_update().one_or_none()
    current_version = review.version if review else 0
    if expected_version is not None and expected_version != current_version:
        raise HTTPException(409, "summary changed; refresh before saving")
    if review is None:
        review = SelfReview(
            ward_id=ward_id, review_date=review_date,
            feeling=feeling, reflection=raw, version=1, submitted_at=now(),
        )
        db.add(review)
        db.flush()
    else:
        review.version += 1
        review.feeling = feeling or review.feeling
        review.reflection = raw
        review.submitted_at = now()
    db.add(SelfReviewVersion(
        review_id=review.id, version=review.version,
        raw_expression=raw, source_message_id=source_message_id,
        confirmed_at=now(),
    ))
    db.flush()
    for aspect in prepared:
        db.add(SelfReviewAspect(
            review_id=review.id, review_version=review.version, **aspect,
        ))
    return review
