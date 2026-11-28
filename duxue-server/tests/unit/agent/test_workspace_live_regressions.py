"""Regressions found through the Android core-journey acceptance."""

from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from app.agent_specs.education_workspace import SkillChoice
from app.application.agent.selected_skill import run_adult_composite_turn
from app.application.workflows import education_workspace as workspace


@pytest.mark.parametrize("comparison", ["consistent", "incomparable"])
def test_arithmetic_operator_can_verify_a_surviving_solver_candidate(
    monkeypatch, comparison
):
    solution = SimpleNamespace(
        status="low_confidence",
        confidence="low",
        final_answers={"main": "57"},
        evidence={"comparison": comparison, "stem_disputed": False},
    )
    engine = Mock()
    engine.check_arithmetic.return_value = ["equal"]
    monkeypatch.setattr(workspace, "solve_and_verify_problem", lambda **_: solution)
    monkeypatch.setattr(workspace, "_resolve_math_engine", lambda: engine)
    assert workspace.verify("23 + 34 =") == {"main": "57"}
    engine.check_arithmetic.assert_called_once_with([("23 + 34", "57")], 3)


@pytest.mark.parametrize("verdict", ["unknown", "not_equal"])
def test_surviving_candidate_without_operator_proof_stays_unverified(
    monkeypatch, verdict
):
    solution = SimpleNamespace(
        status="low_confidence",
        confidence="low",
        final_answers={"main": "57"},
        evidence={"comparison": "incomparable", "stem_disputed": False},
    )
    engine = Mock()
    engine.check_arithmetic.return_value = [verdict]
    monkeypatch.setattr(workspace, "solve_and_verify_problem", lambda **_: solution)
    monkeypatch.setattr(workspace, "_resolve_math_engine", lambda: engine)
    assert workspace.verify("题面缺少必要图形条件") == {}


def test_disputed_stem_cannot_be_certified_by_arithmetic_fallback(monkeypatch):
    solution = SimpleNamespace(
        status="low_confidence",
        confidence="low",
        final_answers={"main": "57"},
        evidence={"comparison": "incomparable", "stem_disputed": True},
    )
    engine = Mock()
    engine.check_arithmetic.return_value = ["equal"]
    monkeypatch.setattr(workspace, "solve_and_verify_problem", lambda **_: solution)
    monkeypatch.setattr(workspace, "_resolve_math_engine", lambda: engine)
    assert workspace.verify("23 + 34 =") == {}
    engine.check_arithmetic.assert_not_called()


def test_courseware_handoff_cannot_claim_generation_has_completed(monkeypatch):
    document = workspace.Document(
        "lesson_pack",
        "加法教案",
        [
            {
                "kind": "variant_question",
                "status": "needs_manual_review",
                "needs_manual_review": True,
            },
        ],
    )
    monkeypatch.setattr(workspace, "build_document", lambda **_: document)
    choices = iter(
        [
            SkillChoice(
                action="run_skill",
                skill="edu.interactive_courseware",
                sub_goal="演示加法",
            ),
            SkillChoice(
                action="finish",
                skill="general",
                finish_reason="all_done",
                answer="ALREADY_GENERATED_UNSAVED_COURSEWARE",
            ),
        ]
    )
    monkeypatch.setattr(workspace, "choose_skill", lambda **_: next(choices))
    result = run_adult_composite_turn(
        role="guardian",
        owner="test",
        thread_id=None,
        message="备课并制作演示",
        attachments=[],
        previous=None,
        invoke_domain=dict,
        initial_choice=SkillChoice(action="run_skill", skill="edu.lesson_pack"),
    )
    assert result.recommend_courseware
    assert result.documents == (document,)
    assert "ALREADY_GENERATED_UNSAVED_COURSEWARE" not in result.summary_content
    assert "加法教案" in result.summary_content
    assert "打开课件编辑器" in result.summary_content
