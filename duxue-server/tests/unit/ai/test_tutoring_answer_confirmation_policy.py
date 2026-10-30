"""The answer-confirmation policy is shared by the tutor and its exit judge."""

from app.infrastructure.ai.prompts import PROMPTS


def test_tutor_allows_verified_open_response_but_not_option_probe():
    prompt = PROMPTS["tutoring.turn.system.v20"].text
    assert "计算题、问答题" in prompt
    assert "选择题、判断题" in prompt
    assert "独立核验" in prompt
    assert "不能逐项确认" in prompt


def test_leak_judge_exposes_facts_instead_of_choosing_its_reason():
    from app.agent_specs.definitions import load_definitions
    unit = load_definitions().units["tutoring.leak-judge"]
    schema = unit.provider_output_schema
    assert set(schema["required"]) == set(schema["properties"])
    assert not schema["additionalProperties"]
    assert "leaks" not in schema["properties"] and "reason" not in schema["properties"]
    assert schema["properties"]["student_answer_correct"]["type"] == ["boolean", "null"]


def test_global_guide_rule_requires_one_student_executable_step():
    prompt = PROMPTS["tutoring.turn.system.v20"].text
    assert "每轮 guide" in prompt
    assert "只推进一个" in prompt
    assert "不提前宣布" in prompt


def test_stem_formulas_and_spatial_svg_boundary():
    turn_prompt = PROMPTS["tutoring.turn.system.v20"].text
    visual_judge_prompt = PROMPTS["tutoring.visual-leak-judge.system.v5"].text
    assert "一维常规公式" in turn_prompt
    assert "二维对位演算式与学科结构式" in turn_prompt
    assert "作业图尽量只摆已知量" in turn_prompt
    assert "最终待求变量用 ?，不能直接暴露" in turn_prompt
    assert "不要用 \\enclose{longdiv}" in turn_prompt
    assert "可带少量过程描述" in visual_judge_prompt
    assert "横线上方的商位也是待求变量" in visual_judge_prompt
