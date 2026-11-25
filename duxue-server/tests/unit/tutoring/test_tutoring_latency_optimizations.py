"""Unit tests for tutoring latency optimizations:
1. IntentProposal optional history_image_ref / thinking hints (backward compatible)
2. Skipping OSS history-image reads & tutoring.image-target when history_image_ref == "none"
3. Dynamic thinking downgrade on pure-text non-reasoning turns
4. Runtime stripping of [image-review.v1] system prompt block on image-free turns
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from app.agent_specs.contracts import validate_output
from app.agent_specs.definitions import load_definitions
from app.application.ports.companion import IntentProposal, RunInvocation
from app.application.workflows.tutoring_workflow import TutoringWorkflow
from app.infrastructure.ai.components import (
    ComponentSpec,
)
from app.infrastructure.ai.components import (
    invoke_json_component as _REAL_INVOKE_JSON_COMPONENT,
)
from app.infrastructure.ai.intent_classifier import parse_intent_payload
from app.infrastructure.ai.prompts import PromptTemplate
from app.infrastructure.ai.tutor_turn_model import (
    QwenTutorTurnGateway,
    _strip_image_review_section,
)


def test_parse_intent_payload_defaults_and_optional_hints():
    legacy = parse_intent_payload('{"intent": "tutoring"}')
    assert legacy == IntentProposal(
        intent="tutoring", history_image_ref="needed", thinking="default"
    )

    optimized = parse_intent_payload(
        '{"intent": "tutoring", "history_image_ref": "none", "thinking": "off"}'
    )
    assert optimized == IntentProposal(
        intent="tutoring", history_image_ref="none", thinking="off"
    )

    unknown = parse_intent_payload(
        '{"intent": "tutoring", "history_image_ref": "maybe", "thinking": "fast"}'
    )
    assert unknown == IntentProposal(
        intent="tutoring", history_image_ref="needed", thinking="default"
    )


def test_companion_intent_contract_accepts_legacy_and_hints():
    from copy import deepcopy

    from jsonschema.exceptions import ValidationError

    unit, _ = load_definitions().component("companion.intent")
    # Legacy fixture schema (intent only) still validates
    validate_output(unit, {"intent": "tutoring"})

    # Upgraded Admin schema with optional history_image_ref & thinking
    upgraded_schema = deepcopy(unit.output_schema)
    upgraded_schema["properties"]["history_image_ref"] = {"enum": ["none", "needed"]}
    upgraded_schema["properties"]["thinking"] = {"enum": ["default", "off"]}
    upgraded_unit = unit.model_copy(update={"output_schema": upgraded_schema})

    validate_output(upgraded_unit, {"intent": "tutoring"})
    validate_output(
        upgraded_unit,
        {"intent": "tutoring", "history_image_ref": "none", "thinking": "off"},
    )
    with pytest.raises((ValidationError, ValueError)):
        validate_output(upgraded_unit, {"intent": "tutoring", "history_image_ref": "invalid"})
    with pytest.raises((ValidationError, ValueError)):
        validate_output(upgraded_unit, {"intent": "tutoring", "thinking": "invalid"})


def test_strip_image_review_section_only_removes_image_review_block():
    prompt = (
        "\n[visual-delivery.v1]\n视觉规则第一行\n视觉规则第二行"
        "\n\n[image-review.v1]\n图片批改规则第一行\n图片批改规则第二行"
        "\n\n你是读学的陪学老师，面对的是一名小学或初中学生。"
    )
    stripped = _strip_image_review_section(prompt)
    assert "[visual-delivery.v1]" in stripped
    assert "视觉规则第二行" in stripped
    assert "[image-review.v1]" not in stripped
    assert "图片批改规则" not in stripped
    assert "你是读学的陪学老师" in stripped


def test_tutor_turn_gateway_strips_image_review_only_when_no_images(monkeypatch):
    prompt = (
        "[visual-delivery.v1]\n视觉规则"
        "\n\n[image-review.v1]\n图片批改规则"
        "\n\n你是读学的陪学老师。"
    )
    base_spec = ComponentSpec(
        component_id="tutoring.turn",
        version="v1",
        operation="tutor_turn",
        agent_label="tutoring",
        risk_tier="protected",
        model="deepseek-v4.1-flash-1017",
        prompt=PromptTemplate("tutoring.turn.system.test", prompt),
        input_contract="tutor-turn.v4",
        output_contract="tutor-turn-candidate.v4",
        max_tokens=1200,
        temperature=0.2,
        enable_thinking=True,
        thinking_budget=1536,
    )
    captured: list[ComponentSpec] = []

    def fake_invoke(*, spec, user, settings_obj=None):
        captured.append(spec)
        return SimpleNamespace(
            unwrap=lambda: {
                "act": "answer",
                "content": "美国实行联邦制和三权分立。",
                "turn": {"type": "non_work", "topic": "spontaneous_curiosity"},
            }
        )

    monkeypatch.setattr(
        "app.infrastructure.ai.components.invoke_agent_component", fake_invoke
    )
    gw = QwenTutorTurnGateway(spec=base_spec)

    # Pure-text turn with _disable_thinking=True: strips [image-review.v1] & disables thinking
    gw.complete(
        envelope={"_disable_thinking": True},
        instruction="说说美国体制",
        recent_utterances=[{"author": "ward", "text": "榕树长什么样？"}],
        current_images=[],
    )
    assert len(captured) == 1
    assert captured[0].enable_thinking is False
    assert captured[0].thinking_budget is None
    assert "[image-review.v1]" not in captured[0].prompt.text
    assert "[visual-delivery.v1]" in captured[0].prompt.text

    # Image turn: keeps [image-review.v1] and keeps thinking enabled
    gw.complete(
        envelope={},
        instruction="检查这道题",
        recent_utterances=[],
        current_images=["data:image/jpeg;base64,AAAA"],
    )
    assert len(captured) == 2
    assert captured[1].enable_thinking is True
    assert captured[1].thinking_budget == 1536
    assert "[image-review.v1]" in captured[1].prompt.text


def test_tutoring_workflow_skips_history_image_read_and_selector_when_none(monkeypatch):
    seen_budgets: list[int] = []
    selector_calls: list[dict] = []

    def fake_load_visible_utterances(
        db, *, ward_id, thread_id, exclude_turn_id, image_budget=8, read_image=None, **kwargs
    ):
        seen_budgets.append(image_budget)
        if image_budget == 0:
            return [
                {"author": "ward", "text": "有没有全部都做对？", "had_images": True},
                {"author": "ward", "text": "榕树长什么样？"},
            ]
        return [
            {
                "author": "ward",
                "text": "有没有全部都做对？",
                "image_urls": ["data:image/jpeg;base64,old1"],
            },
            {
                "author": "ward",
                "text": "这个有没有全部做对？",
                "image_urls": ["data:image/jpeg;base64,old2"],
            },
        ]

    monkeypatch.setattr(
        "app.application.queries.run_transcript.load_visible_utterances",
        fake_load_visible_utterances,
    )
    monkeypatch.setattr(
        "app.application.queries.run_transcript.current_turn_images",
        lambda ward_id, keys, read_image=None: [],
    )

    wf = TutoringWorkflow(
        db=SimpleNamespace(),
        image_target_selector=lambda window, content: (
            selector_calls.append({"window": window, "content": content})
            or {"target_image_ids": [], "ambiguous": False}
        ),
    )

    from app.application.workflows.tutoring_workflow import _TutoringTurn

    # Case 1: history_image_ref == "none" -> image_budget=0, selector NOT called
    inv_none = RunInvocation(
        run_id="r1",
        thread_id="t1",
        ward_id="w1",
        agent_type="tutoring",
        turn={"content": "说说美国的国家体制有什么特殊的地方？", "history_image_ref": "none"},
    )
    turn_none = _TutoringTurn(wf, inv_none)
    turn_none.turn = inv_none.turn
    turn_none.content = inv_none.turn["content"]
    assert turn_none.select_images() == "resolved"
    assert seen_budgets == [0]
    assert selector_calls == []
    assert turn_none.prepared.target.ids == ()

    # Case 2: compare_previous_image overrides history_image_ref="none"
    inv_compare = RunInvocation(
        run_id="r2",
        thread_id="t1",
        ward_id="w1",
        agent_type="tutoring",
        turn={
            "content": "对比上一张",
            "history_image_ref": "none",
            "tutoring_intent": "compare_previous_image",
        },
    )
    turn_compare = _TutoringTurn(wf, inv_compare)
    turn_compare.turn = inv_compare.turn
    turn_compare.content = inv_compare.turn["content"]
    assert turn_compare.select_images() == "resolved"
    assert seen_budgets == [0, 8]
    assert len(selector_calls) == 1

    # Case 3: default (omitted history_image_ref) -> backward-compatible image_budget=8
    inv_default = RunInvocation(
        run_id="r3",
        thread_id="t1",
        ward_id="w1",
        agent_type="tutoring",
        turn={"content": "看看上一张第2题"},
    )
    turn_default = _TutoringTurn(wf, inv_default)
    turn_default.turn = inv_default.turn
    turn_default.content = inv_default.turn["content"]
    assert turn_default.select_images() == "resolved"
    assert seen_budgets == [0, 8, 8]
    assert len(selector_calls) == 2


def test_tutoring_workflow_disables_thinking_only_on_text_turns_without_images():
    from app.application.ports.companion import ContextEnvelope
    from app.application.workflows.image_target import ImageTarget, PreparedImages
    from app.application.workflows.tutoring_workflow import _TutoringTurn
    from app.contexts.tutoring.domain.tutor_permit import TutorPermitPolicy

    captured_envelopes: list[dict] = []

    class CapturingWorkflow(TutoringWorkflow):
        def _resolve_active_dossier(self, **kwargs):
            return None, None

        def _dossier_mode_enabled(self) -> bool:
            return False

        def _run_model(self, envelope, instruction, window, images, tools, **checks):
            captured_envelopes.append(dict(envelope))

    wf = CapturingWorkflow(db=SimpleNamespace())
    base_envelope = ContextEnvelope(
        run={"run_id": "r1", "agent_type": "tutoring"},
        actor={"ward_id": "w1", "role": "ward"},
        objective={"agent_type": "tutoring"},
        session={},
    )

    def run_case(*, disable_thinking: bool, has_image: bool):
        inv = RunInvocation(
            run_id="r1",
            thread_id="t1",
            ward_id="w1",
            agent_type="tutoring",
            turn={"content": "说说美国体制", "disable_thinking": disable_thinking},
        )
        turn = _TutoringTurn(wf, inv)
        turn.turn = inv.turn
        turn.content = inv.turn["content"]
        turn.envelope = base_envelope
        turn.tutor = None
        turn.problem_row = None
        turn.task_title = None
        turn.task_active = False
        turn.permit = TutorPermitPolicy.permit(None)
        turn.keys_by_ref = {}
        turn.prepared = PreparedImages(
            target=ImageTarget((1,) if has_image else ()),
            window=[],
            images=["data:image/jpeg;base64,AAAA"] if has_image else [],
        )
        turn.generate()

    run_case(disable_thinking=True, has_image=False)
    run_case(disable_thinking=True, has_image=True)
    run_case(disable_thinking=False, has_image=False)

    assert captured_envelopes[0].get("_disable_thinking") is True
    assert captured_envelopes[1].get("_disable_thinking") is True
    assert captured_envelopes[2].get("_disable_thinking") is None


def test_admin_bundle_compiles_both_legacy_and_upgraded_companion_intent():
    import json

    from app.agent_specs.admin_bundle import compile_bundle
    from app.agent_specs.configuration import snapshot_path
    from scripts.upgrade_companion_intent_hints import upgrade

    record = json.loads(snapshot_path().read_text(encoding="utf-8"))
    # Legacy snapshot without history_image_ref/thinking still compiles unchanged
    legacy_compiled = compile_bundle(record["bundle"])
    assert legacy_compiled.digest == record["digest"]

    # Upgraded snapshot with optional history_image_ref & thinking also compiles cleanly
    upgraded = upgrade(record)
    upgraded_compiled = compile_bundle(upgraded["bundle"])
    assert upgraded_compiled.digest == upgraded["digest"]
    props = upgraded["bundle"]["files"]["agents/companion.intent.json"]["output_schema"]["properties"]
    assert props["history_image_ref"] == {"enum": ["none", "needed"]}
    assert props["thinking"] == {"enum": ["default", "off"]}


def test_leak_judge_fragment_names_selects_scenarios_in_stable_order():
    from app.infrastructure.ai.tutor_turn_model import _leak_judge_fragment_names

    assert _leak_judge_fragment_names(images=None, problem_summary='{"current_request": "抽样方法"}') == ()
    assert _leak_judge_fragment_names(
        images=None,
        problem_summary='{"math_review_required": true, "candidate_visual": {"kind": "svg"}}',
    ) == ("math_review", "visual_svg_geometry")
    assert _leak_judge_fragment_names(
        images=["data:image/jpeg;base64,AAA"],
        context={"candidate_visual": {"kind": "web_photo"}},
        force_math=True,
    ) == ("math_review", "image_review", "visual_svg_geometry", "web_photo")


def test_compose_system_prompt_preserves_prefix_and_handles_missing_fragments():
    import json
    from copy import deepcopy

    from app.agent_specs.admin_bundle import compile_bundle
    from app.agent_specs.configuration import snapshot_path
    from app.agent_specs.definitions import use_definitions
    from app.application.workflows.image_review import require_configuration
    from app.infrastructure.ai.prompts import compose_system_prompt

    record = json.loads(snapshot_path().read_text(encoding="utf-8"))
    bundle = deepcopy(record["bundle"])
    lj = bundle["files"]["gates/tutoring.leak-judge.json"]
    lj["prompt"]["template"] = "核心常驻规则\n[submitted-feedback.v1]"
    lj["prompt"]["fragments"] = {
        "math_review": {
            "id": "tutoring.leak-judge.fragment.math_review",
            "template": "[math.v1] 数学一致 math_consistent 规则",
            "variables": {},
        },
        "image_review": {
            "id": "tutoring.leak-judge.fragment.image_review",
            "template": "[image-review.v1] 图片核验规则",
            "variables": {},
        },
    }
    turn_doc = bundle["files"]["agents/tutoring.turn.json"]
    turn_doc["prompt"]["template"] = turn_doc["prompt"]["template"].replace("[image-review.v1]", "")
    turn_doc["prompt"].setdefault("fragments", {})["image_review"] = {
        "id": "tutoring.turn.fragment.image_review",
        "template": "[image-review.v1] 导师图片核验规则",
        "variables": {},
    }
    bundle["files"]["agents/tutoring.image-target.json"]["prompt"]["template"] += "\n[image-review.v1]"
    from app.agent_specs.admin_bundle import contract_compatibility

    bundle["compatibility"] = contract_compatibility(bundle["files"])

    # Both compile_bundle and require_configuration accept markers declared in fragments
    compiled = compile_bundle(bundle)
    require_configuration(bundle)

    with use_definitions(compiled.catalog):
        base = PromptTemplate("tutoring.leak-judge.system", "核心常驻规则")
        assert compose_system_prompt(base, "tutoring.leak-judge", ()) is base
        assert compose_system_prompt(base, "tutoring.leak-judge", ("nonexistent",)) is base
        composed = compose_system_prompt(
            base, "tutoring.leak-judge", ("math_review", "image_review", "nonexistent")
        )
        assert composed.text.startswith("核心常驻规则\n\n[math.v1]")
        assert "[image-review.v1] 图片核验规则" in composed.text


def test_pure_text_tutor_turn_drops_spurious_image_review_while_image_turn_validates(monkeypatch):
    import json
    from types import SimpleNamespace

    from app.infrastructure.ai import components
    from app.infrastructure.ai.components import ChatCompletionResult
    from app.infrastructure.ai.errors import ModelGatewayError
    from app.infrastructure.ai.tutor_turn_model import QwenTutorTurnGateway

    bad_payload = json.dumps(
        {
            "act": "guide",
            "content": "你的判断和依据都对。",
            "turn": {"type": "work", "relation": "new", "student_move": "attempt"},
            "image_review": {
                "conclusion": "not_checking",
                "scope": "阅读理解选择题",
                "coverage": "已核对学生的原文引用与推理",
                "questions": [],
            },
        },
        ensure_ascii=False,
    )

    monkeypatch.setattr(components, "invoke_json_component", _REAL_INVOKE_JSON_COMPONENT)
    monkeypatch.setattr("app.infrastructure.ai.client.dashscope_client", lambda **kw: object())
    monkeypatch.setattr(
        components,
        "complete_json_chat",
        lambda **kw: ChatCompletionResult(raw=bad_payload, raw_wire=bad_payload, finish_reason="stop", stream_completed=True),
    )
    settings_stub = SimpleNamespace(
        agent_model_enabled=True,
        dashscope_api_key="test-key",
        agent_model_timeout_seconds=10,
        ai_model_overrides="",
    )
    gw = QwenTutorTurnGateway(settings_obj=settings_stub)

    # Pure-text turn: spurious `image_review` is stripped before schema validation
    result = gw.complete(
        envelope={"subject": "english"},
        instruction="请检查学生的阅读理解推理",
        recent_utterances=[],
        current_images=[],
    )
    assert result["act"] == "guide"
    assert "image_review" not in result

    # Image turn: invalid `image_review` enum must still fail contract validation
    with pytest.raises(ModelGatewayError):
        gw.complete(
            envelope={"subject": "english"},
            instruction="请看图检查",
            recent_utterances=[],
            current_images=["data:image/jpeg;base64,AAAA"],
        )


def test_intent_context_sends_only_current_images_and_keeps_history_image_ids():
    import json
    from app.agent_specs.contexts import intent as build_intent_context

    parts = build_intent_context(
        content="这一面的多选题为什么错了？",
        focus_agent_type="tutoring",
        recent_utterances=[
            {"author": "ward", "text": "穷奇呢？", "image_urls": ["data:image/jpeg;base64,OLD1"]},
            {"author": "ward", "text": "九尾狐吗？", "image_urls": ["data:image/jpeg;base64,OLD2"]},
        ],
        current_images=["data:image/jpeg;base64,NEW1"],
    )
    image_parts_sent = [p for p in parts if p.get("type") == "image_url"]
    assert len(image_parts_sent) == 1
    assert image_parts_sent[0]["image_url"]["url"] == "data:image/jpeg;base64,NEW1"

    body = json.loads(parts[0]["text"])
    assert body["recent_utterances"][0]["image_ids"] == [1]
    assert body["recent_utterances"][1]["image_ids"] == [2]
    assert body["current_image_ids"] == [3]


def test_tutor_turn_gateway_strips_gaokao_for_primary_and_applies_thinking_budget(monkeypatch):
    prompt = (
        "[visual-delivery.v1]\n视觉规则"
        "\n\n[gaokao-blueprint-science.v1]\n高考理科蓝图规则"
        "\n\n[image-review.v1]\n图片批改规则"
        "\n\n你是读学的陪学老师。"
    )
    base_spec = ComponentSpec(
        component_id="tutoring.turn",
        version="v1",
        operation="tutor_turn",
        agent_label="tutoring",
        risk_tier="protected",
        model="deepseek-v4.1-flash-1017",
        prompt=PromptTemplate("tutoring.turn.system.test", prompt),
        input_contract="tutor-turn.v4",
        output_contract="tutor-turn-candidate.v4",
        max_tokens=1200,
        temperature=0.2,
        enable_thinking=True,
        thinking_budget=2048,
    )
    captured: list[ComponentSpec] = []

    def fake_invoke(*, spec, user, settings_obj=None):
        captured.append(spec)
        return SimpleNamespace(
            unwrap=lambda: {
                "act": "guide",
                "content": "我们一起看课文第一段。",
                "turn": {"type": "work", "relation": "new"},
            }
        )

    monkeypatch.setattr("app.infrastructure.ai.components.invoke_agent_component", fake_invoke)
    gw = QwenTutorTurnGateway(spec=base_spec)

    # Primary student without dossier: strips [gaokao-blueprint-science.v1] and applies _thinking_budget
    gw.complete(
        envelope={"actor": {"grade_stage": "primary"}, "_thinking_budget": 1024},
        instruction="多选题为什么错了？",
        recent_utterances=[],
        current_images=["data:image/jpeg;base64,AAAA"],
    )
    assert len(captured) == 1
    assert captured[0].enable_thinking is True
    assert captured[0].thinking_budget == 1024
    assert "[gaokao-blueprint-science.v1]" not in captured[0].prompt.text
    assert "[image-review.v1]" in captured[0].prompt.text

    # High-school student keeps [gaokao-blueprint-science.v1] and full thinking_budget
    gw.complete(
        envelope={"actor": {"grade_stage": "high"}},
        instruction="求导数",
        recent_utterances=[],
        current_images=["data:image/jpeg;base64,BBBB"],
    )
    assert len(captured) == 2
    assert captured[1].thinking_budget == 2048
    assert "[gaokao-blueprint-science.v1]" in captured[1].prompt.text


def test_leak_repair_never_echoes_placeholder_draft():
    import json
    from app.application.workflows.image_review import ImageReview
    from app.application.workflows.tutor_loop import Vetting, _leak_repair
    from app.application.workflows.tutor_turn import TutorTurnCandidate

    candidate = TutorTurnCandidate.model_validate({
        "act": "guide",
        "content": "待核验",
        "turn": {"type": "work", "relation": "new", "student_move": "request_hint", "depth": "reasoning"},
        "image_review": ImageReview(conclusion="uncertain", scope="specified", coverage="partial", questions=[]),
    })
    vetting = Vetting(candidate, None, "leak_detected", "choice_verdict")
    feedback = _leak_repair(vetting)
    parsed = json.loads(feedback)
    assert parsed["kind"] == "image_review_recheck"
    assert "待核验" not in feedback


def test_complete_intent_enables_vision_for_multimodal_model_with_current_images(monkeypatch):
    from app.infrastructure.ai.intent_classifier import complete_intent

    captured_specs: list[ComponentSpec] = []

    def fake_invoke(*, spec, user, settings_obj=None):
        captured_specs.append(spec)
        return SimpleNamespace(unwrap=lambda: {"intent": "tutoring", "history_image_ref": "none", "thinking": "off"})

    monkeypatch.setattr("app.infrastructure.ai.components.invoke_agent_component", fake_invoke)

    vision_spec = ComponentSpec(
        component_id="companion.intent", version="v1", operation="intent_proposal",
        agent_label="planning", risk_tier="standard", model="qwen3.8-flash",
        prompt=PromptTemplate("companion.intent.test", "router"),
        input_contract="intent-input.v1", output_contract="intent-proposal.v1",
        max_tokens=90, temperature=0.0, accepts_images=False,
    )
    complete_intent(
        content="多选题为什么错了？", focus_agent_type="tutoring",
        recent_utterances=[], current_images=["data:image/jpeg;base64,NEW1"], spec=vision_spec,
    )
    assert captured_specs[-1].accepts_images is True

    text_only_spec = ComponentSpec(
        component_id="companion.intent", version="v1", operation="intent_proposal",
        agent_label="planning", risk_tier="standard", model="qwen-flash",
        prompt=PromptTemplate("companion.intent.test", "router"),
        input_contract="intent-input.v1", output_contract="intent-proposal.v1",
        max_tokens=90, temperature=0.0, accepts_images=False,
    )
    complete_intent(
        content="多选题为什么错了？", focus_agent_type="tutoring",
        recent_utterances=[], current_images=["data:image/jpeg;base64,NEW1"], spec=text_only_spec,
    )
    assert captured_specs[-1].accepts_images is False
