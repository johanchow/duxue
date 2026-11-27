"""Unit tests for MentorCourseware commands, queries, and CAS repository."""

from __future__ import annotations

from uuid import uuid4

import pytest

from app.application.commands.mentor_courseware import (
    CoursewareForbiddenError,
    CreateMentorCoursewareInput,
    MentorCoursewareCommandService,
    MoveCoursewareCursorInput,
    RequestCoursewareRevisionInput,
)
from app.application.queries.mentor_courseware import MentorCoursewareQueryService
from app.contexts.tutoring.domain.mentor_courseware import (
    CoursewareConflictError,
    CoursewareStep,
    CoursewareVersion,
    VerificationBaseline,
    VisualSpec,
)
from app.infrastructure.persistence.mentor_courseware_store import (
    InMemoryCoursewareRepository,
    InMemoryProductionStatusStore,
)


def _setup():
    repo = InMemoryCoursewareRepository()
    status_store = InMemoryProductionStatusStore()
    cmds = MentorCoursewareCommandService(repo)
    queries = MentorCoursewareQueryService(repo, status_store)
    return repo, status_store, cmds, queries


def _sample_version(baseline: VerificationBaseline, text: str, summary: str = "初版") -> CoursewareVersion:
    return CoursewareVersion(
        version_no=0,
        parent_version_no=None,
        baseline_hash=baseline.baseline_hash,
        change_summary=summary,
        verification_status="verified",
        methodology_key="化折为直",
        steps=(
            CoursewareStep(
                step_id="s1",
                title="核心突破",
                thinking_why="同侧折线难以直接求最值",
                action_what=text,
                visual_spec=VisualSpec(
                    kind="component_scene",
                    payload={"component": "coord_plane_2d", "points": []},
                    static_fallback_text="静态坐标说明",
                ),
            ),
        ),
    )


def test_create_idempotency_and_cross_guardian_forbidden():
    _, _, cmds, queries = _setup()
    g1, g2 = uuid4(), uuid4()

    r1 = cmds.create(CreateMentorCoursewareInput(guardian_id=g1, command_id="cmd-1", prompt_text="立体几何题"))
    r2 = cmds.create(CreateMentorCoursewareInput(guardian_id=g1, command_id="cmd-1", prompt_text="立体几何题"))
    assert r1.courseware_id == r2.courseware_id
    assert r2.idempotent_replay is True

    with pytest.raises(CoursewareConflictError) as exc:
        cmds.create(CreateMentorCoursewareInput(guardian_id=g1, command_id="cmd-1", prompt_text="换了一道题"))
    assert exc.value.code == "idempotency_payload_mismatch"

    with pytest.raises(CoursewareForbiddenError):
        queries.get_view(courseware_id=r1.courseware_id, guardian_id=g2)


def test_full_lifecycle_cas_undo_redo_and_view_projection():
    _, _, cmds, queries = _setup()
    g = uuid4()
    created = cmds.create(CreateMentorCoursewareInput(guardian_id=g, command_id="c1", prompt_text="将军饮马"))

    b1 = VerificationBaseline.create(confidence="high", summary_answer="2√13", final_answers=["2√13"])
    cw = cmds.attach_baseline(courseware_id=created.courseware_id, baseline=b1)

    # Phase 1 view already shows verification_summary before v1 is published
    view_p1 = queries.get_view(courseware_id=created.courseware_id, guardian_id=g)
    assert view_p1["status"] == "drafting"
    assert view_p1["verification_summary"]["summary_answer"] == "2√13"

    cmds.publish_version(
        courseware_id=created.courseware_id,
        revision_id=None,
        base_version_no=None,
        expected_state_revision=cw.state_revision,
        candidate_version=_sample_version(b1, "作对称点 A'"),
        requires_reverify=False,
        reverify_passed=None,
    )

    view_v1 = queries.get_view(courseware_id=created.courseware_id, guardian_id=g)
    assert view_v1["status"] == "ready"
    assert view_v1["history_controls"]["can_undo"] is False
    assert len(view_v1["current_version"]["outline"]) == 1

    # Request revision -> publish v2
    rev = cmds.request_revision(
        RequestCoursewareRevisionInput(
            guardian_id=g,
            courseware_id=created.courseware_id,
            command_id="rev-cmd-1",
            instruction="补充类比",
            base_version_no=1,
            expected_state_revision=view_v1["state_revision"],
        )
    )
    # Idempotent replay returns same slot
    rev_replay = cmds.request_revision(
        RequestCoursewareRevisionInput(
            guardian_id=g,
            courseware_id=created.courseware_id,
            command_id="rev-cmd-1",
            instruction="补充类比",
            base_version_no=1,
            expected_state_revision=view_v1["state_revision"],
        )
    )
    assert rev_replay.revision_id == rev.revision_id
    assert rev_replay.idempotent_replay is True

    cmds.publish_version(
        courseware_id=created.courseware_id,
        revision_id=rev.revision_id,
        base_version_no=rev.base_version_no,
        expected_state_revision=rev.started_state_revision,
        candidate_version=_sample_version(b1, "小马喝水对称点 A'", summary="补类比"),
        requires_reverify=False,
        reverify_passed=None,
    )

    view_v2 = queries.get_view(courseware_id=created.courseware_id, guardian_id=g)
    assert view_v2["current_version"]["version_no"] == 2
    assert view_v2["history_controls"]["can_undo"] is True

    # Idempotent Undo
    cmds.undo(
        MoveCoursewareCursorInput(
            guardian_id=g,
            courseware_id=created.courseware_id,
            command_id="undo-1",
            expected_state_revision=view_v2["state_revision"],
        )
    )
    cmds.undo(
        MoveCoursewareCursorInput(
            guardian_id=g,
            courseware_id=created.courseware_id,
            command_id="undo-1",
            expected_state_revision=view_v2["state_revision"],
        )
    )
    view_back = queries.get_view(courseware_id=created.courseware_id, guardian_id=g)
    assert view_back["current_version"]["version_no"] == 1
    assert view_back["history_controls"]["can_redo"] is True
