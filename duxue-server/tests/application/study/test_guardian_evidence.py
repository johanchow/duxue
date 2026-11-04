from datetime import date, datetime, timedelta, timezone

from app.infrastructure.persistence.models import (
    TutoringMessage,
    TutoringProblem,
    TutoringSession,
)
from app.infrastructure.security.tokens import create_access_token
from tests.support.factories import create_guardian, create_study_session, create_ward

DAY = date(2026, 11, 3)
AT = datetime(2026, 11, 2, 16, 5, tzinfo=timezone.utc)  # Shanghai Nov 3


def _headers(user, role="guardian"):
    return {
        "Authorization": "Bearer "
        + create_access_token(
            user_id=user.id,
            role=role,
            ward_session_version=1 if role == "ward" else None,
        )
    }


def _evidence(db, ward):
    session = create_study_session(db, ward=ward)
    tutor = TutoringSession(ward_id=ward.id, study_session_id=session.id)
    db.add(tutor)
    db.flush()
    problem = TutoringProblem(
        tutoring_session_id=tutor.id, summary="分数应用题", status="submitted"
    )
    db.add(problem)
    db.flush()
    messages = []
    for offset, (role, kind, text) in enumerate(
        [
            ("ward", "question", "两个数量怎么比较？"),
            ("assistant", "guide", "先说说两个数量之间的关系。"),
            ("ward", "attempt", "我画了关系图，再列式。"),
            ("assistant", "reply", "请解释式子里的每一项。"),
        ]
    ):
        row = TutoringMessage(
            tutoring_session_id=tutor.id,
            problem_id=problem.id,
            role=role,
            evidence_kind=kind,
            content=text,
            created_at=AT + timedelta(seconds=offset),
        )
        db.add(row)
        messages.append(row)
    db.flush()
    return problem, tutor, messages


def test_bound_guardian_reads_only_that_days_problem_evidence_without_self_review(
    client, db
):
    guardian = create_guardian(db)
    ward = create_ward(db, guardian=guardian)
    problem, tutor, messages = _evidence(db, ward)
    db.add(
        TutoringMessage(tutoring_session_id=tutor.id, role="ward", content="私人闲聊")
    )
    db.add(
        TutoringMessage(
            tutoring_session_id=tutor.id,
            problem_id=problem.id,
            role="assistant",
            evidence_kind="guide",
            content="被拦截内容",
            safety_blocked=True,
            created_at=AT,
        )
    )
    db.commit()
    base = f"/wards/{ward.id}/tutoring-evidence"
    response = client.get(base, params={"date": str(DAY)}, headers=_headers(guardian))
    assert response.status_code == 200
    assert [row["id"] for row in response.json()["items"]] == [problem.id]
    assert response.json()["items"][0]["status"] == "submitted"  # never verified
    detail = client.get(
        f"{base}/{problem.id}", params={"date": str(DAY)}, headers=_headers(guardian)
    )
    assert detail.status_code == 200
    assert [row["content"] for row in detail.json()["messages"]] == [
        row.content for row in messages
    ]
    assert (
        client.get(
            base, params={"date": "2026-11-02"}, headers=_headers(guardian)
        ).json()["items"]
        == []
    )
    assert (
        client.get(
            f"{base}/{problem.id}",
            params={"date": "2026-11-02"},
            headers=_headers(guardian),
        ).status_code
        == 404
    )


def test_evidence_needs_a_student_attempt_after_a_guide_and_does_not_backfill_history(
    client, db
):
    guardian = create_guardian(db)
    ward = create_ward(db, guardian=guardian)
    problem, tutor, messages = _evidence(db, ward)
    messages[2].evidence_kind = "question"
    # Old unbound messages and aggregate counters are not proof.
    problem.hints_given, problem.substantive_attempts = 5, 4
    db.add(
        TutoringMessage(
            tutoring_session_id=tutor.id, role="ward", content="旧尝试", created_at=AT
        )
    )
    db.commit()
    response = client.get(
        f"/wards/{ward.id}/tutoring-evidence",
        params={"date": str(DAY)},
        headers=_headers(guardian),
    )
    assert response.json()["items"] == []


def test_evidence_authorization_and_foreign_problem(client, db):
    guardian, stranger = create_guardian(db), create_guardian(db)
    ward, other = create_ward(db, guardian=guardian), create_ward(db, guardian=stranger)
    _own, _, _ = _evidence(db, ward)
    foreign, _, _ = _evidence(db, other)
    db.commit()
    base = f"/wards/{ward.id}/tutoring-evidence"
    assert (
        client.get(
            base, params={"date": str(DAY)}, headers=_headers(stranger)
        ).status_code
        == 404
    )
    assert (
        client.get(
            base, params={"date": str(DAY)}, headers=_headers(ward, "ward")
        ).status_code
        == 401
    )
    assert (
        client.get(
            f"{base}/{foreign.id}",
            params={"date": str(DAY)},
            headers=_headers(guardian),
        ).status_code
        == 404
    )


def test_unbinding_revokes_shared_guardian_access_and_blank_attempts_are_not_text_evidence(
    client, db
):
    from app.infrastructure.persistence.models import GuardianWard

    owner, shared = create_guardian(db), create_guardian(db)
    ward = create_ward(db, guardian=owner)
    relation = GuardianWard(guardian_id=shared.id, ward_id=ward.id)
    db.add(relation)
    _problem, _, messages = _evidence(db, ward)
    db.commit()
    base = f"/wards/{ward.id}/tutoring-evidence"
    assert (
        len(
            client.get(
                base, params={"date": str(DAY)}, headers=_headers(shared)
            ).json()["items"]
        )
        == 1
    )
    db.delete(relation)
    db.commit()
    assert (
        client.get(
            base, params={"date": str(DAY)}, headers=_headers(shared)
        ).status_code
        == 404
    )
    messages[2].content = ""
    db.commit()
    assert (
        client.get(base, params={"date": str(DAY)}, headers=_headers(owner)).json()[
            "items"
        ]
        == []
    )
