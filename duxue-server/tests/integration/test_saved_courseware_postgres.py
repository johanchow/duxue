from datetime import datetime, timedelta, timezone
from uuid import uuid4

import pytest
from sqlalchemy import select, update

from app.application.commands.mentor_courseware import MentorCoursewareCommandService
from app.contexts.tutoring.domain.mentor_courseware import (
    CoursewareConflictError,
    MentorCourseware,
)
from app.infrastructure.persistence.artifact_tables import artifacts as coursewares, versions
from app.infrastructure.persistence.pg_courseware import PgCoursewareRepository
from tests.integration.test_gateway_postgres import (  # noqa: F401
    migrated_engine,
    postgres_url,
)
from tests.unit.tutoring.test_guardian_courseware_api import _make_client


def test_saved_version_photo_and_expiry_transactions(migrated_engine):  # noqa: F811
    verify_courseware_transactions(migrated_engine)


def verify_courseware_transactions(engine):
    owner = uuid4()
    repo = PgCoursewareRepository(engine)
    cmd = MentorCoursewareCommandService(repo)
    client = _make_client([owner], repo)
    from uuid import UUID

    cid = UUID(
        client.post(
            "/guardian/courseware",
            json={"command_id": "first", "prompt_text": "测试独立课件"},
        ).json()["courseware_id"]
    )
    v1 = repo.get(cid)

    def unavailable(keys):
        raise OSError("temporary object unavailable")

    with pytest.raises(OSError):
        cmd.change_library(owner, cid, "save", "s", "", v1.state_revision, unavailable)
    assert repo.list_saved(owner) == []
    photos = ["dGVzdA=="]
    cmd.change_library(
        owner, cid, "save", "s", "", v1.state_revision, lambda keys: (photos, None)
    )
    fresh = PgCoursewareRepository(engine)
    saved = fresh.get(cid)
    assert saved.current_version == v1.current_version
    assert fresh.saved_photos(owner, cid) == photos
    assert not fresh.saved_photos(uuid4(), cid)
    with pytest.raises(CoursewareConflictError):
        fresh.save_cas(v1, expected_state_revision=v1.state_revision)
    path = f"/guardian/courseware/{cid}"
    assert (
        client.post(
            path + "/revisions",
            json={
                "command_id": "rev",
                "instruction": "拆细第一步",
                "base_version_no": 1,
                "expected_state_revision": saved.state_revision,
            },
        ).status_code
        == 202
    )
    revised = fresh.get(cid)
    assert revised.current_version.version_no == 2
    for op, expected in [("undo", 1), ("redo", 2)]:
        assert (
            client.post(
                path + "/" + op,
                json={
                    "command_id": op,
                    "expected_state_revision": fresh.get(cid).state_revision,
                },
            ).status_code
            == 200
        )
        assert fresh.get(cid).current_version.version_no == expected
    cmd.change_library(
        owner, cid, "delete", "del", "", fresh.get(cid).state_revision, None
    )
    assert fresh.get(cid) is None
    with pytest.raises(CoursewareConflictError):
        fresh.save_cas(revised, expected_state_revision=revised.state_revision)
    with engine.connect() as conn:
        assert (
            conn.scalar(
                select(versions.c.version_no).where(versions.c.artifact_id == cid)
            )
            is None
        )
    temp = MentorCourseware.create(guardian_id=owner, prompt_text="过期测试")
    repo.create(temp, command_id="expiry")
    with engine.begin() as conn:
        conn.execute(
            update(coursewares)
            .where(coursewares.c.artifact_id == temp.courseware_id)
            .values(expires_at=datetime.now(timezone.utc) - timedelta(seconds=1))
        )
    assert fresh.get(temp.courseware_id) is None
    # Limit the business-database probe to rows owned by this test.
    with engine.begin() as conn:
        conn.execute(
            coursewares.delete().where(
                coursewares.c.artifact_id == temp.courseware_id
            )
        )


def test_saved_courseware_survives_source_thread_deletion(migrated_engine, monkeypatch):  # noqa: F811
    from sqlalchemy.orm import Session
    from app.api.deps import Principal, current_guardian_or_ward, get_db
    from app.api.v1 import conversations, guardian_courseware, guardian_experience
    from app.infrastructure.persistence.models import Guardian, User

    owner = uuid4()
    principal = Principal(user_id=str(owner), role="guardian")
    with Session(migrated_engine) as db:
        db.add(User(id=str(owner), type="guardian"))
        db.flush()
        db.add(Guardian(id=str(owner), name="老师", email=f"{owner}@example.org", role="guardian"))
        db.commit()

    def session():
        with Session(migrated_engine) as db:
            yield db

    client = _make_client([owner], PgCoursewareRepository(migrated_engine))
    commands, queries, _ = client.app.dependency_overrides[guardian_courseware.get_courseware_services]()
    monkeypatch.setattr(guardian_courseware, "_commands", commands)
    monkeypatch.setattr(guardian_courseware, "_queries", queries)
    client.app.include_router(conversations.router)
    client.app.include_router(guardian_experience.router)
    client.app.dependency_overrides[current_guardian_or_ward] = lambda: principal
    client.app.dependency_overrides[get_db] = session
    monkeypatch.setattr(guardian_experience, "experience_turn", lambda **kw: {"content": "画图理解通分"})
    root = "/v1/conversations"
    thread = client.post(root, json={}).json()["thread_id"]
    answer = client.post("/guardian/experience/turn", json={
        "thread_id": thread, "mode": "guardian_explain", "content": "演示通分", "command_id": "turn-a",
    }).json()
    courseware = client.post("/guardian/courseware", json={
        "command_id": "turn-" + answer["message_id"], "prompt_text": "演示通分",
    }).json()["courseware_id"]
    view = client.get("/guardian/courseware/" + courseware).json()
    assert view["status"] == "ready"
    assert client.post(f"/guardian/courseware/{courseware}/save", json={
        "command_id": "save", "expected_state_revision": view["state_revision"],
    }).is_success
    messages = client.get(f"{root}/{thread}/messages").json()["items"]
    assert messages[-1]["courseware_id"] == courseware
    assert client.delete(f"{root}/{thread}").status_code == 204
    assert client.get(f"{root}/{thread}/messages").status_code == 404
    assert client.get("/guardian/courseware/" + courseware).json()["retention_status"] == "saved"


def test_story_source_thread_is_id_only(migrated_engine):
    from sqlalchemy import inspect
    from app.infrastructure.persistence.models import CreativeWork

    assert not CreativeWork.__table__.c.source_thread_id.foreign_keys
    inspector = inspect(migrated_engine)
    constraints = inspector.get_foreign_keys("edu_artifacts")
    assert not any("source_thread_id" in key["constrained_columns"] for key in constraints)
    assert any(key["column_names"] == ["source_thread_id"] for key in inspector.get_indexes("edu_artifacts"))


def test_late_ward_reply_cannot_reappear_after_an_independent_clear(migrated_engine):
    from fastapi import HTTPException
    from sqlalchemy.orm import Session
    from app.application.commands.companion_history import clear_history
    from app.application.process_managers.companion_coordinator import CompanionCoordinator
    from app.infrastructure.persistence.models import CompanionMessage
    from tests.support.factories import create_ward
    from tests.support.fakes import FakeWorkflowDispatcher, StaticIntentClassifier

    with Session(migrated_engine) as db:
        ward = create_ward(db)
        db.commit()
        owner = ward.id

        class ClearingDispatcher(FakeWorkflowDispatcher):
            def invoke(self, invocation):
                with Session(migrated_engine) as writer:
                    clear_history(writer, ward_id=owner, command_id=str(uuid4()))
                return super().invoke(invocation)

        coordinator = CompanionCoordinator(db, dispatcher=ClearingDispatcher(), classifier=StaticIntentClassifier("tutoring"))
        with pytest.raises(HTTPException) as failure:
            coordinator.handle(ward_id=owner, content="先给我提示", thread_id=None, expected_thread_version=0, route_hint="tutoring")
        assert failure.value.status_code == 409
        with Session(migrated_engine) as reader:
            from app.api.v1.companion import current_companion_messages
            from app.api.deps import Principal
            messages = current_companion_messages(before_thread_version=None, limit=50, principal=Principal(owner, "ward"), db=reader)
            assert messages["messages"] == []
            assert reader.query(CompanionMessage).filter_by(ward_id=owner, author_type="companion").count() == 0
