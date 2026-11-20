"""Tests for tutoring latency optimizations: parallel vetting, 0s default solve wait,
narrowed visual redraw review, and on-demand widget_guidelines loading."""

from __future__ import annotations

import threading

from app.agent_specs.admin_bundle import compile_bundle
from app.agent_specs.configuration import read_snapshot
from app.agent_specs.definitions import use_definitions
from app.agent_specs.subworkflows import VET_MATH_NODE
from app.application.workflows import tutor_loop
from app.application.workflows.tutor_loop import call_tutor_model, run_tutor_turn
from app.application.workflows.tutor_tools import TutorToolbox
from app.application.workflows.tutoring_workflow import TutoringWorkflow
from app.contexts.tutoring.domain.tutor_permit import AttemptSummary, TutorPermit
from scripts.upgrade_math_bundle import upgrade as enable_math
from scripts.upgrade_workflow_nodes import upgrade as upgrade_workflows
from tests.support.fakes import StaticTutorModel, StaticVisualLeakJudge, tutor_raw
from tests.unit.math_engine.test_workflow import Engine
from tests.unit.tutoring.test_tutor_visual import SEGMENT, STEPS

PROTECTED = TutorPermit(True, AttemptSummary())


def _parallel_math_bundle():
    return upgrade_workflows(enable_math(read_snapshot(), enable=True))["bundle"]


def _homework_with_visual():
    return tutor_raw("guide", "先看看线段图里谁多谁少？", relation="same", visual=SEGMENT)


def test_default_first_turn_solve_budget_is_zero(monkeypatch):
    monkeypatch.delenv("SOLVE_FIRST_TURN_BUDGET_SECONDS", raising=False)
    wf = TutoringWorkflow(db=None)
    assert wf.first_turn_solve_budget_seconds == 0.0

    monkeypatch.setenv("SOLVE_FIRST_TURN_BUDGET_SECONDS", "1.2")
    wf_override = TutoringWorkflow(db=None)
    assert wf_override.first_turn_solve_budget_seconds == 1.2


def test_math_text_and_visual_judges_run_concurrently():
    """A 3-party barrier only completes if math, text, and visual judges truly overlap."""
    barrier = threading.Barrier(3, timeout=2.0)

    class ConcurrentJudge(StaticVisualLeakJudge):
        def __init__(self):
            super().__init__(result=False, visual_result=False)
            self.math_calls = 0

        def check_math(self, *, text, context, images):
            self.math_calls += 1
            barrier.wait()
            return True

        def leaks(self, *, text, task_title, problem_summary, images=None):
            barrier.wait()
            return super().leaks(
                text=text, task_title=task_title, problem_summary=problem_summary, images=images
            )

        def visual_leaks(self, *, text, task_title, problem_summary):
            barrier.wait()
            return super().visual_leaks(
                text=text, task_title=task_title, problem_summary=problem_summary
            )

    bundle = _parallel_math_bundle()
    # Verify parallel topology is declared in the Admin workflow artifact itself.
    vet_edges = bundle["files"]["workflows/tutoring-vet.json"]["edges"]
    assert any(e["from"] == "tutoring-vet.authority" and e["to"] == VET_MATH_NODE for e in vet_edges)
    assert any(e["from"] == VET_MATH_NODE and e["to"] == "tutoring-vet.complete" for e in vet_edges)
    compiled = compile_bundle(bundle)
    judge = ConcurrentJudge()
    with use_definitions(compiled.catalog):
        tools = TutorToolbox(
            None, tutoring_session_id=None, problem=None, task_title=None, task_active=False,
            window=[], math_engine=Engine(),
        )
        result = run_tutor_turn(
            StaticTutorModel(_homework_with_visual()),
            {"turn_id": "t-concurrent"},
            "小明有3份，小红有5份",
            [], [], tools,
            permit=PROTECTED,
            leak_judge=judge,
            task_title="应用题",
            problem_summary="小明有3份，小红有5份，一共几份",
        )
    assert result.vetting is not None and result.vetting.failure is None
    assert result.vetting.visual is not None
    assert judge.math_calls == 1
    assert judge.calls == 1
    assert len(judge.visual_texts) == 1


def test_parallel_double_failure_preserves_math_precedence():
    """When both math and text judges deny concurrently, math_inconsistent wins deterministically."""

    class BothFailJudge(StaticVisualLeakJudge):
        def __init__(self):
            super().__init__(result=True, visual_result=True)
            self.math_calls = 0

        def check_math(self, *, text, context, images):
            self.math_calls += 1
            return False

    bundle = _parallel_math_bundle()
    compiled = compile_bundle(bundle)
    judge = BothFailJudge()
    with use_definitions(compiled.catalog):
        tools = TutorToolbox(
            None, tutoring_session_id=None, problem=None, task_title=None, task_active=False,
            window=[], math_engine=Engine(),
        )
        result = run_tutor_turn(
            StaticTutorModel(_homework_with_visual()),
            {"turn_id": "t-precedence"},
            "90-37=53对吗",
            [], [], tools,
            permit=PROTECTED,
            leak_judge=judge,
            task_title="数学作业",
            problem_summary="90-37=53",
        )
    assert result.vetting is not None
    assert result.vetting.failure == "math_inconsistent"
    assert result.vetting.leak_reason == "math_inconsistent"
    assert judge.math_calls >= 1


def test_authority_denial_short_circuits_before_any_judge(monkeypatch):
    """If local authority denies, no LLM judge (math, text, or visual) runs."""
    from app.application.workflows.tutor_turn import Verdict

    class CountingJudge(StaticVisualLeakJudge):
        def __init__(self):
            super().__init__(result=False, visual_result=False)
            self.math_calls = 0

        def check_math(self, *, text, context, images):
            self.math_calls += 1
            return True

    monkeypatch.setattr(tutor_loop, "check_authority", lambda c, p: Verdict(False, "authority_denied_test"))
    bundle = _parallel_math_bundle()
    compiled = compile_bundle(bundle)
    judge = CountingJudge()
    with use_definitions(compiled.catalog):
        tools = TutorToolbox(
            None, tutoring_session_id=None, problem=None, task_title=None, task_active=False,
            window=[], math_engine=Engine(),
        )
        result = run_tutor_turn(
            StaticTutorModel(_homework_with_visual()),
            {"turn_id": "t-auth-deny"},
            "直接告诉我答案",
            [], [], tools,
            permit=PROTECTED,
            leak_judge=judge,
            task_title="应用题",
            problem_summary="3+5=?",
        )
    assert result.vetting is not None and result.vetting.failure == "authority_denied_test"
    assert judge.math_calls == 0
    assert judge.calls == 0
    assert judge.visual_texts == []


def test_visual_redraw_reuses_approved_text_and_skips_text_judge():
    """Unchanged approved text on visual_redraw only re-runs visual_leak, not text_leak."""

    class RedrawJudge(StaticVisualLeakJudge):
        def visual_leaks(self, *, text, task_title, problem_summary):
            self.visual_texts.append(text)
            return len(self.visual_texts) == 1

    model = StaticTutorModel(_homework_with_visual(), _homework_with_visual())
    judge = RedrawJudge()
    tools = TutorToolbox(None, tutoring_session_id=None, problem=None, task_title=None, task_active=False, window=[])
    result = run_tutor_turn(
        model, {}, "{}", [], [], tools, permit=PROTECTED, leak_judge=judge,
        task_title="应用题", problem_summary="小明有3份，小红有5份，一共几份",
    )
    assert result.vetting is not None and result.vetting.failure is None
    assert result.vetting.visual is not None
    assert judge.calls == 1  # text_leak NOT repeated on unchanged redraw
    assert len(judge.visual_texts) == 2  # visual_leak ran for primary and redraw


def test_visual_redraw_altering_text_short_circuits_all_judges():
    """If redraw modifies approved content, reject immediately without calling any Judge."""

    class RedrawJudge(StaticVisualLeakJudge):
        def visual_leaks(self, *, text, task_title, problem_summary):
            self.visual_texts.append(text)
            return True

    changed = tutor_raw("guide", "我偷偷改了正文。", relation="same", visual=STEPS)
    model = StaticTutorModel(_homework_with_visual(), changed)
    judge = RedrawJudge()
    tools = TutorToolbox(None, tutoring_session_id=None, problem=None, task_title=None, task_active=False, window=[])
    result = run_tutor_turn(
        model, {}, "{}", [], [], tools, permit=PROTECTED, leak_judge=judge,
        task_title="应用题", problem_summary="小明有3份，小红有5份，一共几份",
    )
    assert result.vetting is not None and result.vetting.failure is None
    assert result.call.candidate.content == _homework_with_visual()["content"]
    assert result.vetting.visual is None
    assert result.vetting.visual_dropped == "visual_leak_detected"
    assert judge.calls == 1
    assert len(judge.visual_texts) == 1


def test_widget_guidelines_not_preloaded_on_first_call_even_with_visual_delivery(monkeypatch):
    from app.agent_specs import visual_delivery

    monkeypatch.setattr(visual_delivery, "enabled", lambda: True)
    model = StaticTutorModel(tutor_raw("guide", "先想想第一步？", relation="same"))
    tools = TutorToolbox(None, tutoring_session_id=None, problem=None, task_title=None, task_active=False, window=[])
    call = call_tutor_model(model, {}, "{}", [], [], tools)
    assert call.candidate is not None
    assert not any(
        obs.get("tool") == "widget_guidelines" for obs in (model.calls[0]["observations"] or [])
    )
    # Explicit preload_svg_guidelines=True (used by missing_visual_redraw) still preloads it.
    model2 = StaticTutorModel(tutor_raw("guide", "先想想第一步？", relation="same"))
    call2 = call_tutor_model(model2, {}, "{}", [], [], tools, preload_svg_guidelines=True)
    assert call2.candidate is not None
    assert any(
        obs.get("tool") == "widget_guidelines" for obs in (model2.calls[0]["observations"] or [])
    )
    assert tutor_loop is not None
