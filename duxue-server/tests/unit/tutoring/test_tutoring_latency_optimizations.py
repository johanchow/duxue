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
from app.infrastructure.ai.components import ComponentSpec
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
    assert captured_envelopes[1].get("_disable_thinking") is None
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
