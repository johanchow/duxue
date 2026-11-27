from datetime import datetime, timedelta, timezone
from uuid import uuid4

import pytest
from sqlalchemy import select, update

from app.application.commands.mentor_courseware import MentorCoursewareCommandService
from app.contexts.tutoring.domain.mentor_courseware import (
    CoursewareConflictError,
    MentorCourseware,
)
from app.infrastructure.persistence.courseware_tables import coursewares, versions
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
                select(versions.c.version_no).where(versions.c.courseware_id == cid)
            )
            is None
        )
    temp = MentorCourseware.create(guardian_id=owner, prompt_text="过期测试")
    repo.create(temp, command_id="expiry")
    with engine.begin() as conn:
        conn.execute(
            update(coursewares)
            .where(coursewares.c.courseware_id == temp.courseware_id)
            .values(expires_at=datetime.now(timezone.utc) - timedelta(seconds=1))
        )
    assert fresh.get(temp.courseware_id) is None
    # Limit the business-database probe to rows owned by this test.
    with engine.begin() as conn:
        conn.execute(
            coursewares.delete().where(
                coursewares.c.courseware_id == temp.courseware_id
            )
        )
