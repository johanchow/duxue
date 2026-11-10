"""Scoring must fail closed and never treat metadata as semantics."""

import pytest
from pydantic import ValidationError
from evals.grading import Grading, evaluate, aggregate


def config(**kwargs):
    return Grading.model_validate(
        {
            "deterministic": [
                {
                    "id": "kind",
                    "field": "outcome",
                    "op": "in",
                    "expected": ["hint_like"],
                }
            ],
            **kwargs,
        }
    )


@pytest.mark.parametrize(
    "rule",
    [
        {"id": "x", "field": "arbitrary", "op": "eq", "expected": 1},
        {"id": "x", "field": "answer_protected", "op": "eq", "expected": 1},
        {"id": "x", "field": "outcome", "op": "in", "expected": ["made_up"]},
        {"id": "x", "field": "selected_images", "op": "lte", "expected": 1},
    ],
)
def test_reject_invalid_field_types(rule):
    with pytest.raises(ValidationError):
        config(deterministic=[rule])


def test_missing_tool_capture_is_error_not_empty_list():
    grading = config(
        deterministic=[
            {
                "id": "tools",
                "assert": "no_forbidden_tools",
                "forbidden": ["raw_sql_query"],
            }
        ]
    )
    assert evaluate(grading, {}).status == "error"
    assert evaluate(grading, {"tool_calls": []}).status == "pass"


def test_parameter_match_requires_same_call():
    grading = config(
        deterministic=[
            {
                "id": "args",
                "assert": "parameter_match",
                "tool": "math",
                "param": "op",
                "equals": "simplify",
            }
        ]
    )
    assert (
        evaluate(
            grading,
            {
                "tool_calls": [
                    {"name": "math", "args": {"op": "solve"}},
                    {"name": "other", "args": {"op": "simplify"}},
                ]
            },
        ).status
        == "fail"
    )


def test_semantic_result_is_scored_by_code_and_uncalibrated():
    grading = config(
        model_graded=[
            {
                "id": "quality",
                "type": "score",
                "rubric": "1=错误；5=正确且有效",
                "min_score": 4,
            }
        ]
    )
    result = evaluate(
        grading,
        {"outcome": "hint_like"},
        judge=lambda rule: {
            "score": 3,
            "explanation": "无法行动",
            "evidence": ["回复没有下一步"],
        },
    )
    assert result.status == "fail"
    assert result.calibration_status == "uncalibrated"
    assert result.quality_passed is None


@pytest.mark.parametrize(
    "reply",
    [
        None,
        {"score": True},
        {"score": 6, "explanation": "x", "evidence": ["y"]},
        {"score": 5, "explanation": "x", "evidence": []},
    ],
)
def test_invalid_semantic_verdict_is_error(reply):
    grading = config(
        model_graded=[{"id": "q", "type": "score", "rubric": "标准", "min_score": 4}]
    )
    assert (
        evaluate(grading, {"outcome": "hint_like"}, judge=lambda _: reply).status
        == "error"
    )


def test_unrun_and_error_never_pass():
    assert aggregate(["pass", "not_run"]) == "not_run"
    assert aggregate(["pass", "error"]) == "error"
    assert aggregate(["fail", "error"]) == "fail"
    assert aggregate([]) == "not_run"


def test_missing_or_duplicate_rules_rejected():
    with pytest.raises(ValidationError):
        config(deterministic=[])
    with pytest.raises(ValidationError):
        config(
            model_graded=[
                {"id": "kind", "type": "binary", "rubric": "标准", "expected": "pass"}
            ]
        )


def test_teaching_grading_requires_an_explicit_fallback_boundary():
    grading = config(
        deterministic=[
            {"id": "shape", "field": "visual_present", "op": "eq", "expected": False}
        ],
        model_graded=[
            {"id": "q", "type": "binary", "rubric": "标准", "expected": "pass"}
        ],
    )
    with pytest.raises(ValueError, match="fallback boundary"):
        grading.for_component("tutoring.turn")


def test_tool_called_and_forbidden_tools_use_actual_calls():
    grading = config(
        deterministic=[
            {"id": "required", "assert": "tool_called", "with_name": "lookup_history"},
            {
                "id": "forbidden",
                "assert": "no_forbidden_tools",
                "forbidden": ["raw_sql_query"],
            },
        ]
    )
    assert (
        evaluate(
            grading, {"tool_calls": [{"name": "lookup_history", "args": {}}]}
        ).status
        == "pass"
    )
    assert (
        evaluate(
            grading,
            {
                "tool_calls": [
                    {"name": "lookup_history", "args": {}},
                    {"name": "raw_sql_query", "args": {}},
                ]
            },
        ).status
        == "fail"
    )
