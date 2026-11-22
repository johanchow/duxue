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
    assert set(schema["required"]) == set(schema["properties"]) - {"math_consistent"}
    assert schema["properties"]["math_consistent"]["type"] == ["boolean", "null"]
    assert not schema["additionalProperties"]
    assert "leaks" not in schema["properties"] and "reason" not in schema["properties"]
    assert schema["properties"]["student_answer_correct"] == {
        "oneOf": [{"type": ["boolean", "null"]}, {"const": "partial"}]
    }


def test_global_guide_rule_requires_one_student_executable_step():
    prompt = PROMPTS["tutoring.turn.system.v20"].text
    assert "每轮 guide" in prompt
    assert "只推进一个" in prompt
    assert "不提前宣布" in prompt


def test_stem_formulas_and_spatial_svg_boundary():
    turn_prompt = PROMPTS["tutoring.turn.system.v20"].text
    visual_judge_prompt = PROMPTS["tutoring.visual-leak-judge.system.v6"].text
    assert "一维常规公式" in turn_prompt
    assert "二维对位演算式与学科结构式" in turn_prompt
    assert "作业图尽量只摆已知量" in turn_prompt
    assert "最终待求变量用 ?，不能直接暴露" in turn_prompt
    assert "不要用 \\enclose{longdiv}" in turn_prompt
    assert "可带少量过程描述" in visual_judge_prompt
    assert "横线上方的商位也是待求变量" in visual_judge_prompt


def test_submitted_feedback_upgrade_is_idempotent_and_preserves_other_components():
    from copy import deepcopy

    from app.agent_specs.admin_bundle import compile_bundle
    from app.agent_specs.configuration import read_snapshot
    from scripts.upgrade_submitted_feedback import upgrade

    original = read_snapshot()
    upgraded = upgrade(original)
    changed = {key for key, value in original["bundle"]["files"].items()
               if value != upgraded["bundle"]["files"][key]}
    assert changed == {"agents/tutoring.turn.json", "gates/tutoring.leak-judge.json"}
    turn_prompt = upgraded["bundle"]["files"]["agents/tutoring.turn.json"]["prompt"]["template"]
    assert "[submitted-feedback.v4]" in turn_prompt
    assert "只用一个中性问题追问能区分关键方法的最小细节" in turn_prompt
    assert upgrade(upgraded) == upgraded

    # Also verify upgrading a snapshot that already carries gaokao-blueprint & v3 rules
    v3_like = deepcopy(original)
    v3_like["bundle"]["files"]["agents/tutoring.turn.json"]["prompt"]["template"] += (
        "\n\n不得凭心算猜测整题正误。先按原题核对学生具体主张；可以用工具计算、可核查的反例或逐项对照的题面证据检验它。"
        "准确评价能核验的部分，仅对仍缺条件的部分请求补充\n\n"
        "[submitted-feedback.v3]\n旧规则。重写与配图均须保持已核验的状态和结论。"
    )
    v3_like["digest"] = compile_bundle(v3_like["bundle"]).digest
    v4_from_v3 = upgrade(v3_like)
    v4_prompt = v4_from_v3["bundle"]["files"]["agents/tutoring.turn.json"]["prompt"]["template"]
    assert "[submitted-feedback.v3]" not in v4_prompt
    assert "[submitted-feedback.v4]" in v4_prompt
    assert "不得凭心算猜测整题正误" not in v4_prompt
    assert "不得凭心算肯定学生答案是最终正确或最优的" in v4_prompt
    assert upgrade(v4_from_v3) == v4_from_v3

    with_thinking = upgrade(original, enable_thinking=True, thinking_budget=1536)
    turn_model = with_thinking["bundle"]["files"]["agents/tutoring.turn.json"]["models"][0]
    assert turn_model["enable_thinking"] is True
    assert turn_model["thinking_budget"] == 1536
    assert upgrade(with_thinking, enable_thinking=True, thinking_budget=1536) == with_thinking
