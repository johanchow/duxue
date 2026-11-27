"""Unit tests for Tutoring.MentorCourseware domain model and invariants."""

from __future__ import annotations

from uuid import uuid4

import pytest

from app.contexts.tutoring.domain.mentor_courseware import (
    CoursewareConflictError,
    CoursewareInvariantViolationError,
    CoursewareStep,
    CoursewareVersion,
    MentorCourseware,
    VerificationBaseline,
    VisualSpec,
)


def _baseline(answer: str = "2*sqrt(13)", confidence: str = "high") -> VerificationBaseline:
    return VerificationBaseline.create(
        confidence=confidence,  # type: ignore[arg-type]
        summary_answer=answer,
        stem_text="A(1,2), B(5,4), P on x-axis",
        subject="math",
        final_answers=[answer],
    )


def _step(
    sid: str,
    body: str,
    *,
    why: str | None = "化折为直",
    with_visual: bool = True,
) -> CoursewareStep:
    visual = (
        VisualSpec(
            kind="component_scene",
            payload={"component": "coord_plane_2d", "points": [{"id": "A", "x": 1, "y": 2}]},
            title="坐标系示意",
            alt="A(1,2) 与 x 轴",
            static_fallback_text="A(1,2) 位于 x 轴上方",
        )
        if with_visual
        else None
    )
    return CoursewareStep(step_id=sid, title=f"步骤 {sid}", action_what=body, thinking_why=why, visual_spec=visual)


def _version(baseline: VerificationBaseline, steps: list[CoursewareStep], summary: str = "初版") -> CoursewareVersion:
    return CoursewareVersion(
        version_no=0,
        parent_version_no=None,
        baseline_hash=baseline.baseline_hash,
        change_summary=summary,
        verification_status="verified",
        steps=tuple(steps),
    )


def test_initial_publish_and_flexible_structure_without_fixed_five_acts():
    cw = MentorCourseware.create(guardian_id=uuid4(), prompt_text="求 PA+PB 最小值")
    b1 = _baseline()
    cw.attach_baseline(b1)

    # Single natural step without thinking_why or visual is valid (no forced 5-act template)
    v1 = cw.publish_version(
        _version(b1, [_step("s1", "直接利用对称点化折为直", why=None, with_visual=False)]),
        revision_id=None,
        base_version_no=None,
        expected_state_revision=cw.state_revision,
        requires_reverify=False,
        reverify_passed=None,
    )
    assert cw.status == "ready"
    assert v1.version_no == 1
    assert cw.cursor == 0
    assert cw.current_baseline == b1


def test_undo_redo_releases_active_revision_and_blocks_stale_aba_publish():
    cw = MentorCourseware.create(guardian_id=uuid4(), prompt_text="将军饮马")
    b1 = _baseline()
    cw.attach_baseline(b1)
    cw.publish_version(
        _version(b1, [_step("s1", "v1 step")]),
        revision_id=None,
        base_version_no=None,
        expected_state_revision=cw.state_revision,
        requires_reverify=False,
        reverify_passed=None,
    )

    # Publish v2
    slot_v2 = cw.begin_revision(
        revision_id="rev-2",
        base_version_no=1,
        expected_state_revision=cw.state_revision,
        instruction="补充生活类比",
    )
    cw.publish_version(
        _version(b1, [_step("s1", "v2 step")], summary="补充类比"),
        revision_id=slot_v2.revision_id,
        base_version_no=slot_v2.base_version_no,
        expected_state_revision=slot_v2.started_state_revision,
        requires_reverify=False,
        reverify_passed=None,
    )

    # Start revision on v2, then Undo -> Redo back to v2 (ABA)
    slot_v3 = cw.begin_revision(
        revision_id="rev-3",
        base_version_no=2,
        expected_state_revision=cw.state_revision,
        instruction="改细一点",
    )
    assert cw.active_revision is not None

    # Undo immediately frees active_revision slot
    back = cw.undo(expected_state_revision=cw.state_revision)
    assert back.version_no == 1
    assert cw.active_revision is None

    # Redo back to v2: cursor is back to v2, but state_revision has advanced
    fwd = cw.redo(expected_state_revision=cw.state_revision)
    assert fwd.version_no == 2

    # Late worker trying to publish rev-3 must be rejected with revision_base_changed
    with pytest.raises(CoursewareConflictError) as exc:
        cw.publish_version(
            _version(b1, [_step("s1", "stale v3")], summary="迟到修订"),
            revision_id=slot_v3.revision_id,
            base_version_no=slot_v3.base_version_no,
            expected_state_revision=slot_v3.started_state_revision,
            requires_reverify=False,
            reverify_passed=None,
        )
    assert exc.value.code == "revision_base_changed"
    assert len(cw.versions) == 2
    assert cw.current_version.version_no == 2  # type: ignore[union-attr]


def test_branch_truncation_and_monotonic_version_no():
    cw = MentorCourseware.create(guardian_id=uuid4(), prompt_text="立体几何")
    b1 = _baseline()
    cw.attach_baseline(b1)
    cw.publish_version(
        _version(b1, [_step("s1", "v1")]),
        revision_id=None,
        base_version_no=None,
        expected_state_revision=cw.state_revision,
        requires_reverify=False,
        reverify_passed=None,
    )
    slot2 = cw.begin_revision(
        revision_id="r2", base_version_no=1, expected_state_revision=cw.state_revision, instruction="改v2"
    )
    cw.publish_version(
        _version(b1, [_step("s1", "v2")]),
        revision_id="r2",
        base_version_no=1,
        expected_state_revision=slot2.started_state_revision,
        requires_reverify=False,
        reverify_passed=None,
    )

    cw.undo(expected_state_revision=cw.state_revision)
    slot3 = cw.begin_revision(
        revision_id="r3", base_version_no=1, expected_state_revision=cw.state_revision, instruction="从v1分叉"
    )
    v3 = cw.publish_version(
        _version(b1, [_step("s1", "v3 from v1")]),
        revision_id="r3",
        base_version_no=1,
        expected_state_revision=slot3.started_state_revision,
        requires_reverify=False,
        reverify_passed=None,
    )
    # Old v2 truncated, monotonic version_no never reuses 2
    assert [v.version_no for v in cw.versions] == [1, 3]
    assert v3.parent_version_no == 1
    with pytest.raises(CoursewareConflictError) as exc:
        cw.redo(expected_state_revision=cw.state_revision)
    assert exc.value.code == "cursor_out_of_bounds"


def test_cross_version_immutable_baselines_do_not_mix_on_undo_redo():
    cw = MentorCourseware.create(guardian_id=uuid4(), prompt_text="换解法")
    b1 = _baseline(answer="2*sqrt(13)")
    b2 = _baseline(answer="sqrt(52) (相似法)")
    cw.attach_baseline(b1)
    cw.publish_version(
        _version(b1, [_step("s1", "坐标法")]),
        revision_id=None,
        base_version_no=None,
        expected_state_revision=cw.state_revision,
        requires_reverify=False,
        reverify_passed=None,
    )

    slot2 = cw.begin_revision(
        revision_id="r2", base_version_no=1, expected_state_revision=cw.state_revision, instruction="换相似法"
    )
    cw.publish_version(
        _version(b2, [_step("s1", "相似三角形法")]),
        revision_id="r2",
        base_version_no=1,
        expected_state_revision=slot2.started_state_revision,
        requires_reverify=True,
        reverify_passed=True,
        new_baseline=b2,
    )
    assert cw.current_baseline == b2

    cw.undo(expected_state_revision=cw.state_revision)
    assert cw.current_baseline == b1

    cw.redo(expected_state_revision=cw.state_revision)
    assert cw.current_baseline == b2


def test_verification_honesty_gate_blocks_unverified_and_marks_custom_on_override():
    cw = MentorCourseware.create(guardian_id=uuid4(), prompt_text="算错了测试")
    b1 = _baseline()
    cw.attach_baseline(b1)
    cw.publish_version(
        _version(b1, [_step("s1", "原解")]),
        revision_id=None,
        base_version_no=None,
        expected_state_revision=cw.state_revision,
        requires_reverify=False,
        reverify_passed=None,
    )

    slot = cw.begin_revision(
        revision_id="r-err", base_version_no=1, expected_state_revision=cw.state_revision, instruction="改成10"
    )
    with pytest.raises(CoursewareInvariantViolationError) as exc:
        cw.publish_version(
            _version(b1, [_step("s1", "答案是10")]),
            revision_id="r-err",
            base_version_no=1,
            expected_state_revision=slot.started_state_revision,
            requires_reverify=True,
            reverify_passed=False,
            allow_unverified_override=False,
        )
    assert exc.value.code == "reverify_failed"

    # Explicit user override allows publishing as unverified_custom, never verified
    v2 = cw.publish_version(
        _version(b1, [_step("s1", "自定义答案10")]),
        revision_id="r-err",
        base_version_no=1,
        expected_state_revision=slot.started_state_revision,
        requires_reverify=True,
        reverify_passed=False,
        allow_unverified_override=True,
    )
    assert v2.verification_status == "unverified_custom"


def test_p0_1_rejects_generated_js_and_roundtrips_serialization():
    cw = MentorCourseware.create(guardian_id=uuid4(), prompt_text="测试序列化")
    b1 = _baseline()
    cw.attach_baseline(b1)

    bad_visual = VisualSpec(kind="math_stage_script", payload={"code": "alert(1)"}, static_fallback_text="fallback")
    with pytest.raises(CoursewareInvariantViolationError) as exc:
        cw.publish_version(
            _version(b1, [CoursewareStep(step_id="s1", title="t", action_what="a", visual_spec=bad_visual)]),
            revision_id=None,
            base_version_no=None,
            expected_state_revision=cw.state_revision,
            requires_reverify=False,
            reverify_passed=None,
            allow_generated_js=False,
        )
    assert exc.value.code == "generated_js_disabled"

    cw.publish_version(
        _version(b1, [_step("s1", "ok")]),
        revision_id=None,
        base_version_no=None,
        expected_state_revision=cw.state_revision,
        requires_reverify=False,
        reverify_passed=None,
    )
    restored = MentorCourseware.from_dict(cw.to_dict())
    assert restored.courseware_id == cw.courseware_id
    assert restored.state_revision == cw.state_revision
    assert restored.current_version == cw.current_version
    assert restored.current_baseline == cw.current_baseline
