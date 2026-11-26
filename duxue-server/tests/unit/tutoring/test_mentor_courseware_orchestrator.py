"""Unit tests for MentorCoursewareOrchestrator cross-domain flows & localized revision fidelity."""

from __future__ import annotations

from uuid import UUID, uuid4

from app.application.commands.mentor_courseware import (
    CreateMentorCoursewareInput,
    MentorCoursewareCommandService,
    MoveCoursewareCursorInput,
    RequestCoursewareRevisionInput,
)
from app.application.ports.mentor_courseware import (
    DirectorDraftResult,
    PedagogicalDirectorPort,
    PedagogicalJudgePort,
    PedagogicalJudgeResult,
    ProblemVerificationPort,
)
from app.application.process_managers.mentor_courseware_orchestrator import (
    MentorCoursewareOrchestrator,
)
from app.application.queries.mentor_courseware import MentorCoursewareQueryService
from app.contexts.tutoring.domain.mentor_courseware import (
    CoursewareStep,
    VerificationBaseline,
    VisualSpec,
)
from app.infrastructure.ai.mentor_courseware_adapters import ComponentSceneMediaRenderer
from app.infrastructure.persistence.mentor_courseware_store import (
    InMemoryCoursewareRepository,
    InMemoryProductionStatusStore,
)


class _StubVerifier(ProblemVerificationPort):
    def __init__(self, *, reverify_ok: bool = True) -> None:
        self.solve_calls = 0
        self.reverify_calls = 0
        self.reverify_ok = reverify_ok

    def solve_and_verify(self, *, prompt_text: str, attachment_keys: tuple[str, ...], guardian_id: UUID):
        self.solve_calls += 1
        return VerificationBaseline.create(
            confidence="high",
            summary_answer="2√13",
            stem_text=prompt_text,
            subject="math",
            final_answers=["2√13"],
        )

    def reverify_revision(self, *, baseline, instruction, draft_steps):
        self.reverify_calls += 1
        if not self.reverify_ok:
            return False, None, "引擎核验不通过"
        nb = VerificationBaseline.create(
            confidence="high",
            summary_answer="2√13 (相似法复核)",
            stem_text=baseline.stem_text,
            subject="math",
            final_answers=["2√13"],
        )
        return True, nb, "ok"


class _StubDirector(PedagogicalDirectorPort):
    def __init__(self, *, requires_reverify: bool = False, bad_component: bool = False) -> None:
        self.requires_reverify = requires_reverify
        self.bad_component = bad_component
        self.revision_calls = 0

    def draft_initial(self, *, prompt_text, baseline, target_grade_hint=None):
        comp = "unknown_widget" if self.bad_component else "solid_geometry_3d"
        return DirectorDraftResult(
            change_summary="初版课件",
            methodology_key="空间降维",
            steps=(
                CoursewareStep(
                    step_id="s1",
                    title="建立空间直观",
                    thinking_why="先看清正方体表面相邻面关系",
                    action_what="把正方体两个相邻面展平到同一平面",
                    visual_spec=VisualSpec(
                        kind="component_scene",
                        payload={"component": comp, "shape": "cube", "unfold": True},
                        title="正方体展开",
                        alt="正方体表面展开示意",
                        static_fallback_text="正方体展开为长2宽1矩形",
                    ),
                ),
                CoursewareStep(
                    step_id="s2",
                    title="计算最短路",
                    thinking_why="两点之间线段最短",
                    action_what="勾股定理求对角线 √(2²+1²)=√5",
                ),
            ),
        )

    def draft_revision(self, *, current_version, baseline, instruction, target_step_id=None, critique=None):
        self.revision_calls += 1
        steps = list(current_version.steps)
        # Only modify s2; keep s1 untouched
        updated_s2 = CoursewareStep(
            step_id="s2",
            title="计算最短路（已修订）",
            thinking_why="两点之间线段最短",
            action_what=f"按要求修订：{instruction}",
        )
        return DirectorDraftResult(
            change_summary="局部修订 s2",
            methodology_key=current_version.methodology_key,
            steps=(steps[0], updated_s2),
            requires_reverify=self.requires_reverify,
            target_step_ids=("s2",),
        )


class _StubJudge(PedagogicalJudgePort):
    def __init__(self, *, fail_first: bool = False) -> None:
        self.fail_first = fail_first
        self.calls = 0

    def review(self, *, prompt_text, baseline, draft):
        self.calls += 1
        if self.fail_first and self.calls == 1:
            return PedagogicalJudgeResult(passed=False, critique="s2 缺少思考依据")
        return PedagogicalJudgeResult(passed=True)


def _build(*, reverify_ok=True, requires_reverify=False, fail_first=False, bad_component=False):
    repo = InMemoryCoursewareRepository()
    status_store = InMemoryProductionStatusStore()
    cmds = MentorCoursewareCommandService(repo)
    queries = MentorCoursewareQueryService(repo, status_store)
    verifier = _StubVerifier(reverify_ok=reverify_ok)
    director = _StubDirector(requires_reverify=requires_reverify, bad_component=bad_component)
    judge = _StubJudge(fail_first=fail_first)
    orch = MentorCoursewareOrchestrator(
        repo=repo,
        commands=cmds,
        status_store=status_store,
        verifier=verifier,
        director=director,
        judge=judge,
        renderer=ComponentSceneMediaRenderer(),
    )
    return repo, cmds, queries, verifier, director, judge, orch


def test_initial_flow_with_judge_repair_and_expression_revision_skips_solving():
    _, cmds, queries, verifier, director, judge, orch = _build(fail_first=True)
    g = uuid4()
    created = cmds.create(CreateMentorCoursewareInput(guardian_id=g, command_id="c1", prompt_text="正方体最短路径"))

    orch.run_initial(created.courseware_id)
    assert verifier.solve_calls == 1
    assert judge.calls == 1
    assert director.revision_calls == 1  # bounded 1 repair triggered by judge

    v1 = queries.get_view(courseware_id=created.courseware_id, guardian_id=g)
    assert v1["status"] == "ready"
    s1_hash_v1 = v1["current_version"]["steps"][0]["content_hash"]

    # Expression-only revision skips ProblemSolving and preserves s1 verbatim
    rev = cmds.request_revision(
        RequestCoursewareRevisionInput(
            guardian_id=g,
            courseware_id=created.courseware_id,
            command_id="r1",
            instruction="把 s2 讲得更通俗",
            base_version_no=1,
            expected_state_revision=v1["state_revision"],
            target_step_id="s2",
        )
    )
    orch.run_revision(
        courseware_id=created.courseware_id,
        revision_id=rev.revision_id,
        base_version_no=rev.base_version_no,
        started_state_revision=rev.started_state_revision,
        instruction="把 s2 讲得更通俗",
        target_step_id="s2",
    )
    assert verifier.reverify_calls == 0  # skipped ProblemSolving!
    v2 = queries.get_view(courseware_id=created.courseware_id, guardian_id=g)
    assert v2["current_version"]["version_no"] == 2
    assert v2["current_version"]["steps"][0]["content_hash"] == s1_hash_v1


def test_math_correction_triggers_reverify_and_stale_revision_after_undo_is_discarded():
    _, cmds, queries, verifier, _, _, orch = _build(requires_reverify=True, reverify_ok=False)
    g = uuid4()
    created = cmds.create(CreateMentorCoursewareInput(guardian_id=g, command_id="c2", prompt_text="数学题"))
    orch.run_initial(created.courseware_id)
    v1 = queries.get_view(courseware_id=created.courseware_id, guardian_id=g)

    # Failed reverify without override fails revision and keeps v1 intact
    rev = cmds.request_revision(
        RequestCoursewareRevisionInput(
            guardian_id=g,
            courseware_id=created.courseware_id,
            command_id="r-err",
            instruction="答案改成 10",
            base_version_no=1,
            expected_state_revision=v1["state_revision"],
        )
    )
    orch.run_revision(
        courseware_id=created.courseware_id,
        revision_id=rev.revision_id,
        base_version_no=1,
        started_state_revision=rev.started_state_revision,
        instruction="答案改成 10",
        allow_unverified_override=False,
    )
    assert verifier.reverify_calls == 1
    after_fail = queries.get_view(courseware_id=created.courseware_id, guardian_id=g)
    assert after_fail["current_version"]["version_no"] == 1
    assert after_fail["active_revision_pending"] is False

    # With explicit override -> publishes v2 as unverified_custom
    rev2 = cmds.request_revision(
        RequestCoursewareRevisionInput(
            guardian_id=g,
            courseware_id=created.courseware_id,
            command_id="r-override",
            instruction="答案改成 10",
            base_version_no=1,
            expected_state_revision=after_fail["state_revision"],
            allow_unverified_override=True,
        )
    )
    orch.run_revision(
        courseware_id=created.courseware_id,
        revision_id=rev2.revision_id,
        base_version_no=1,
        started_state_revision=rev2.started_state_revision,
        instruction="答案改成 10",
        allow_unverified_override=True,
    )
    v2 = queries.get_view(courseware_id=created.courseware_id, guardian_id=g)
    assert v2["current_version"]["verification_status"] == "unverified_custom"

    # Start rev3 on v2, then Undo to v1 before worker finishes -> late rev3 silently discarded
    rev3 = cmds.request_revision(
        RequestCoursewareRevisionInput(
            guardian_id=g,
            courseware_id=created.courseware_id,
            command_id="r-stale",
            instruction="再改改",
            base_version_no=2,
            expected_state_revision=v2["state_revision"],
        )
    )
    cmds.undo(
        MoveCoursewareCursorInput(
            guardian_id=g,
            courseware_id=created.courseware_id,
            command_id="u1",
            expected_state_revision=rev3.started_state_revision,
        )
    )
    orch.run_revision(
        courseware_id=created.courseware_id,
        revision_id=rev3.revision_id,
        base_version_no=2,
        started_state_revision=rev3.started_state_revision,
        instruction="再改改",
        allow_unverified_override=True,
    )
    final_view = queries.get_view(courseware_id=created.courseware_id, guardian_id=g)
    assert final_view["current_version"]["version_no"] == 1
    assert final_view["history_controls"]["total_versions"] == 2


def test_unsupported_component_degrades_single_step_to_static_without_failing_courseware():
    _, cmds, queries, _, _, _, orch = _build(bad_component=True)
    g = uuid4()
    created = cmds.create(CreateMentorCoursewareInput(guardian_id=g, command_id="c3", prompt_text="降级测试"))
    orch.run_initial(created.courseware_id)
    v1 = queries.get_view(courseware_id=created.courseware_id, guardian_id=g)
    assert v1["status"] == "ready"
    assert v1["current_version"]["steps"][0]["visual_spec"]["kind"] == "layered_svg"
    assert v1["current_version"]["steps"][0]["visual_spec"]["payload"]["degraded"] is True
