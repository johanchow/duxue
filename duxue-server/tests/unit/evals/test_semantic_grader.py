"""Evidence isolation and snapshot upgrades use fakes, never provider calls."""

import copy
import json

import pytest

from evals.grading import SemanticCheck
from evals.semantic import SemanticGrader
from tests.support.eval_cases import Backends, FixedScorer, make_case
from tests.support.fakes import StaticLeakJudge, StaticTutorModel, tutor_raw


def test_grader_sends_rubric_reference_and_original_pixels_to_its_own_component(
    monkeypatch,
):
    from app.infrastructure.ai import components

    captured = []
    monkeypatch.setattr(
        components,
        "invoke_json_component",
        lambda **kw: (
            captured.append(kw)
            or {"score": 4, "explanation": "依据图片", "evidence": ["page.png"]}
        ),
    )
    grader = SemanticGrader()
    rule = SemanticCheck(id="quality", type="score", rubric="一至五分标准", min_score=4)
    pixels = "data:image/png;base64,cGl4ZWxz"
    evidence = {"student_said": "当前问题", "response": {"message": "实际回复"}}
    assert (
        grader.grade(
            rule,
            evidence=evidence,
            image_pairs=[("page.png", pixels)],
            reference="参考正文",
        )["score"]
        == 4
    )
    call = captured[0]
    assert call["spec"].component_id == "evals.semantic-judge"
    payload = json.loads(call["user"][0]["text"])
    assert payload["evidence"] == evidence
    assert (
        payload["rubric"] == rule.rubric and payload["reference_response"] == "参考正文"
    )
    assert payload["image_manifest"] == [{"index": 1, "asset": "page.png"}]
    assert [
        part["image_url"]["url"] for part in call["user"] if part["type"] == "image_url"
    ] == [pixels]
    assert grader.metadata()["judge_prompt_digest"]


def test_insufficient_evidence_is_error_not_a_score(monkeypatch):
    from app.infrastructure.ai import components

    monkeypatch.setattr(
        components,
        "invoke_json_component",
        lambda **_: {"error": "insufficient_evidence"},
    )
    with pytest.raises(ValueError, match="insufficient_evidence"):
        SemanticGrader().grade(
            SemanticCheck(id="q", type="binary", rubric="明确标准", expected="pass"),
            evidence={},
            image_pairs=[],
        )


def test_grader_receives_case_constraints_visible_surfaces_and_typed_output(
    monkeypatch,
):
    from app.infrastructure.ai import components

    calls = []
    monkeypatch.setattr(
        components,
        "invoke_json_component",
        lambda **kw: (
            calls.append(kw)
            or {
                "score": 4,
                "explanation": "依据卡片",
                "evidence": ["response.lessons[0]"],
            }
        ),
    )
    criteria = [
        {"id": "protect", "type": "binary", "rubric": "不能泄露受保护的旧题答案"}
    ]
    SemanticGrader().grade(
        SemanticCheck(id="q", type="score", rubric="质量标准", min_score=4),
        evidence={"response": {"lessons": [{"source_text": "shoe"}]}},
        image_pairs=[],
        criteria=criteria,
    )
    payload = json.loads(calls[0]["user"])
    assert payload["case_criteria"] == criteria
    assert payload["delivery_contract"]["visible_fields"] == [
        "message",
        "visual",
        "lessons",
    ]
    assert payload["output_contract"]["required"] == [
        "score",
        "explanation",
        "evidence",
    ]


def test_runner_sends_all_semantic_criteria_only_to_grader():
    from evals.runner import run_sample
    from evals.grading import SemanticCheck

    case = make_case(
        {
            "id": "turn-criteria-00",
            "component": "tutoring.turn",
            "conversation_id": "test",
            "turn_index": 0,
            "student_said": "你好",
            "source": "synthetic",
            "expect": {"outcome_in": ["chat"]},
        }
    )
    case.grading.model_graded.append(
        SemanticCheck(
            id="specific",
            type="binary",
            rubric="PRIVATE_CASE_CRITERION",
            expected="pass",
        )
    )
    scorer = FixedScorer()
    model = StaticTutorModel(tutor_raw("chat", "你好", relation=None))
    sample = run_sample(
        case, Backends(tutor_model=model, semantic_grader=scorer), [], []
    )
    assert sample.passed
    assert scorer.calls[0][1]["criteria"][1]["rubric"] == "PRIVATE_CASE_CRITERION"
    assert "PRIVATE_CASE_CRITERION" not in json.dumps(model.calls)


def test_fallback_grading_never_reads_rejected_candidate_or_hidden_reference_in_generator():
    from evals.runner import run_sample
    from app.application.workflows.tutor_turn import fallback_text

    case = make_case(
        {
            "id": "turn-evidence-00",
            "component": "tutoring.turn",
            "conversation_id": "test",
            "turn_index": 0,
            "student_said": "怎么做",
            "context": {"problem": {"summary": "数学题"}},
            "source": "synthetic",
            "expect": {
                "outcome_in": ["fallback"],
                "response": {"message": "HIDDEN_REFERENCE"},
            },
        }
    )
    model = StaticTutorModel(tutor_raw("guide", "REJECTED_DRAFT"))
    scorer = FixedScorer()
    sampled = run_sample(
        case,
        Backends(
            tutor_model=model, leak_judge=StaticLeakJudge(True), semantic_grader=scorer
        ),
        [],
        [],
    )
    assert sampled.observation.outcome == "fallback"
    data = scorer.calls[0][1]
    assert data["reference"] == "HIDDEN_REFERENCE"
    assert (
        data["evidence"]["response"]["message"] == sampled.observation.delivered_content
    )
    assert data["evidence"]["response"]["message"] == fallback_text("leak_detected")
    assert "REJECTED_DRAFT" not in json.dumps(data["evidence"])
    assert "HIDDEN_REFERENCE" not in json.dumps(model.calls)
    assert data["evidence"]["response"]["lessons"] == []
    assert sampled.grading_result.meta["grading_latency_ms"] >= 0


def test_missing_grader_is_explicit_error_and_never_formal_pass():
    from evals.runner import run_sample

    case = make_case(
        {
            "id": "turn-evidence-00",
            "component": "tutoring.turn",
            "conversation_id": "test",
            "turn_index": 0,
            "student_said": "你好",
            "source": "synthetic",
            "expect": {"outcome_in": ["chat"]},
        }
    )
    sampled = run_sample(
        case,
        Backends(
            tutor_model=StaticTutorModel(tutor_raw("chat", "你好", relation=None)),
            semantic_grader=None,
        ),
        [],
        [],
    )
    assert sampled.grading_result.status == "error"
    assert sampled.grading_result.quality_passed is None


def test_bundle_upgrade_is_explicit_idempotent_and_preserves_existing_configuration():
    from app.agent_specs.admin_bundle import compile_bundle, digest
    from app.agent_specs.configuration import snapshot_bundle
    from scripts.upgrade_eval_bundle import upgrade

    bundle = snapshot_bundle()
    del bundle["files"]["agents/evals.semantic-judge.json"]
    del bundle["files"]["workflows/eval-grading.json"]
    old = {
        "id": "source-release",
        "kind": "release",
        "digest": digest(bundle),
        "bundle": bundle,
    }
    before = copy.deepcopy(old)
    result = upgrade(old)
    assert old == before
    assert (
        result["kind"] == "draft"
        and result["migration_source"]["id"] == "source-release"
    )
    assert result["digest"] == compile_bundle(result["bundle"]).digest
    for name, value in bundle["files"].items():
        assert result["bundle"]["files"][name] == value
    new = result["bundle"]["files"]["agents/evals.semantic-judge.json"]
    assert (
        new["models"][0]["name"]
        == bundle["files"]["gates/tutoring.leak-judge.json"]["models"][0]["name"]
    )
    assert new["tools"] == []
    assert upgrade(result) == result
    old["digest"] = "invalid"
    with pytest.raises(ValueError, match="digest"):
        upgrade(old)


def test_refresh_existing_grader_is_explicit_and_preserves_every_other_setting():
    from app.agent_specs.admin_bundle import compile_bundle
    from app.agent_specs.configuration import snapshot_bundle
    from scripts.upgrade_eval_bundle import upgrade, PROMPT

    bundle = snapshot_bundle()
    key = "agents/evals.semantic-judge.json"
    bundle["files"][key]["prompt"]["template"] = "old grader prompt"
    old = {
        "id": "old-grader",
        "kind": "draft",
        "bundle": bundle,
        "digest": compile_bundle(bundle).digest,
    }
    assert upgrade(old) == old
    revised = upgrade(old, refresh_grader=True)
    assert revised["bundle"]["files"][key]["prompt"]["template"] == PROMPT
    before, after = copy.deepcopy(bundle), copy.deepcopy(revised["bundle"])
    before["files"][key]["prompt"]["template"] = after["files"][key]["prompt"][
        "template"
    ]
    assert before == after
    assert revised["migration_source"]["digest"] == old["digest"]
    assert revised["digest"] == compile_bundle(revised["bundle"]).digest


def test_runner_records_real_tool_names_arguments_and_results():
    from evals.runner import run_sample
    from evals.grading import ToolCalled, ParameterMatch

    case = make_case(
        {
            "id": "turn-tools-00",
            "component": "tutoring.turn",
            "conversation_id": "test",
            "turn_index": 0,
            "student_said": "任务是什么",
            "source": "synthetic",
            "context": {"task_title": "数学作业", "task_active": True},
            "expect": {"outcome_in": ["chat"]},
        }
    )
    case.grading.deterministic.extend(
        [
            ToolCalled(
                id="called", assertion="tool_called", with_name="get_task_context"
            ),
            ParameterMatch(
                id="args",
                assertion="parameter_match",
                tool="get_task_context",
                param="test_marker",
                equals=7,
            ),
        ]
    )
    model = StaticTutorModel(
        {"tool": "get_task_context", "args": {"test_marker": 7}},
        tutor_raw("chat", "数学作业", relation=None),
    )
    sample = run_sample(case, Backends(tutor_model=model), [], [])
    assert sample.passed
    call = sample.observation.tool_calls[0]
    assert call["name"] == "get_task_context" and call["args"] == {"test_marker": 7}
    assert "数学作业" in json.dumps(call["result"], ensure_ascii=False)
