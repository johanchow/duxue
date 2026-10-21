"""The answer-confirmation policy is shared by the tutor and its exit judge."""

from app.infrastructure.ai.prompts import PROMPTS


def test_tutor_allows_verified_open_response_but_not_option_probe():
    prompt = PROMPTS["tutoring.turn.system.v19"].text
    assert "计算题、问答题" in prompt
    assert "选择题、判断题" in prompt
    assert "独立核验" in prompt
    assert "不能逐项确认" in prompt


def test_leak_judge_distinguishes_open_response_from_option_probe():
    prompt = PROMPTS["tutoring.leak-judge.system.v6"].text
    assert "学生先前原话和本轮原话" in prompt
    assert "独立核验" in prompt
    assert "选择题、判断题" in prompt
    assert "错误答案" in prompt
    assert "未计算" in prompt
    assert "premature_conclusion" in prompt


def test_global_guide_rule_requires_one_student_executable_step():
    prompt = PROMPTS["tutoring.turn.system.v19"].text
    assert "每轮 guide" in prompt
    assert "只推进一个" in prompt
    assert "不提前宣布" in prompt


def test_stem_formulas_and_spatial_svg_boundary():
    turn_prompt = PROMPTS["tutoring.turn.system.v19"].text
    visual_judge_prompt = PROMPTS["tutoring.visual-leak-judge.system.v5"].text
    assert "一维常规公式" in turn_prompt
    assert "二维对位演算式与学科结构式" in turn_prompt
    assert "作业图尽量只摆已知量" in turn_prompt
    assert "最终待求变量用 ?，不能直接暴露" in turn_prompt
    assert "不要用 \\enclose{longdiv}" in turn_prompt
    assert "可带少量过程描述" in visual_judge_prompt
    assert "横线上方的商位也是待求变量" in visual_judge_prompt
