"""Guardian-visible work-product evidence. No inference of mastery or historical links."""

from collections import defaultdict
from datetime import datetime, time, timedelta, timezone
from zoneinfo import ZoneInfo

from fastapi import HTTPException

from app.infrastructure.persistence.models import (
    TutoringMessage,
    TutoringProblem,
    TutoringSession,
)


def _day_messages(db, ward_id, day, problem_id=None):
    start = datetime.combine(
        day, time.min, tzinfo=ZoneInfo("Asia/Shanghai")
    ).astimezone(timezone.utc)
    end = start + timedelta(days=1)
    query = (
        db.query(TutoringMessage, TutoringProblem)
        .join(TutoringProblem, TutoringMessage.problem_id == TutoringProblem.id)
        .join(
            TutoringSession, TutoringProblem.tutoring_session_id == TutoringSession.id
        )
        .filter(
            TutoringSession.ward_id == ward_id,
            TutoringMessage.tutoring_session_id == TutoringSession.id,
            TutoringMessage.created_at >= start,
            TutoringMessage.created_at < end,
            TutoringMessage.safety_blocked.is_(False),
            TutoringMessage.evidence_kind.in_(
                ["question", "guide", "attempt", "reply"]
            ),
        )
    )
    if problem_id is not None:
        query = query.filter(TutoringProblem.id == problem_id)
    return query.order_by(TutoringMessage.created_at, TutoringMessage.id).all()


def _group(db, ward_id, day, problem_id=None):
    groups = defaultdict(list)
    problems = {}
    for message, problem in _day_messages(db, ward_id, day, problem_id):
        if not message.content.strip():
            continue  # Image-only attempts need a separately authorized image projection.
        groups[problem.id].append(message)
        problems[problem.id] = problem
    # A guide alone or the first pre-guide attempt is not a thinking-process credential.
    eligible = {}
    for key, messages in groups.items():
        guided = False
        for message in messages:
            if message.role == "assistant" and message.evidence_kind == "guide":
                guided = True
            if guided and message.role == "ward" and message.evidence_kind == "attempt":
                eligible[key] = (problems[key], messages)
                break
    return eligible


def _summary(problem):
    return {
        "id": problem.id,
        "title": problem.summary or "本题推导记录",
        "status": problem.status,
        "basis": "guided_student_attempts",
    }


def list_evidence(db, ward_id, day):
    return {
        "items": [
            _summary(problem)
            for problem, _ in reversed(list(_group(db, ward_id, day).values()))
        ]
    }


def evidence_detail(db, ward_id, day, problem_id):
    entry = _group(db, ward_id, day, problem_id).get(problem_id)
    if entry is None:
        raise HTTPException(404, "thinking process not found")
    problem, messages = entry
    return {
        **_summary(problem),
        "messages": [
            {
                "id": message.id,
                "role": message.role,
                "content": message.content,
                "kind": message.evidence_kind,
                "created_at": message.created_at,
            }
            for message in messages
        ],
    }


def evening_evidence(db, ward_id, day):
    """All distinct asked problems plus process credentials; no mastery inference."""
    rows = _day_messages(db, ward_id, day)
    asked = {problem.id for message, problem in rows if message.evidence_kind == 'question'}
    credentials = list_evidence(db, ward_id, day)['items']
    return {
        'asked_count': len(asked),
        'verified_count': 0 if not asked else None,
        'certificates': [{**item, 'source_status': item['status'],
                          'status': 'in_progress' if item['status'] == 'open' else 'unverified'}
                         for item in credentials],
        'missing_reason': 'verification_source_unavailable' if asked else None,
        'source_refs': [{'problem_id': problem.id, 'last_turn_id': problem.last_turn_id,
                         'status': problem.status, 'message_id': message.id} for message, problem in rows],
    }
