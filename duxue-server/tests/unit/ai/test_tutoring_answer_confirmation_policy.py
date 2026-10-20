"""The answer-confirmation policy is shared by the tutor and its exit judge."""

from app.infrastructure.ai.prompts import PROMPTS


def test_tutor_allows_verified_open_response_but_not_option_probe():
    prompt = PROMPTS["tutoring.turn.system.v15"].text
    assert "计算题、问答题" in prompt
    assert "选择题、判断题" in prompt
    assert "独立核验" in prompt
    assert "不能逐项确认" in prompt


def test_leak_judge_distinguishes_open_response_from_option_probe():
    prompt = PROMPTS["tutoring.leak-judge.system.v5"].text
    assert "孩子本轮提出" in prompt
    assert "独立核验" in prompt
    assert "选择题、判断题" in prompt
    assert "错误答案" in prompt
