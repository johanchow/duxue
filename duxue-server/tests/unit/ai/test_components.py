from __future__ import annotations

import json
from types import SimpleNamespace

import pytest

from app.infrastructure.ai import components
from app.infrastructure.ai.components import (
    COMPONENTS,
    invoke_json_component,
    resolve_model,
    validate_overrides,
)
from app.infrastructure.ai.errors import ModelGatewayError
from app.infrastructure.ai.prompts import PromptTemplate
from tests.support.fakes import leak_judge_facts


class _Client:
    def __init__(self, content: str, finish_reason: str | None = "stop"):
        self.content = content
        self.finish_reason = finish_reason
        self.calls: list[dict] = []
        self.chat = SimpleNamespace(completions=SimpleNamespace(create=self.create))

    def create(self, **kwargs):
        self.calls.append(kwargs)
        return SimpleNamespace(
            id="provider-request-1",
            usage=SimpleNamespace(prompt_tokens=7, completion_tokens=3),
            choices=[
                SimpleNamespace(
                    finish_reason=self.finish_reason,
                    message=SimpleNamespace(content=self.content),
                )
            ],
        )


def _settings(overrides: str = ""):
    return SimpleNamespace(agent_model_timeout_seconds=8, ai_model_overrides=overrides)


@pytest.fixture
def spans(monkeypatch):
    captured: dict = {}

    class Span:
        def __init__(self, **kwargs):
            captured["span"] = kwargs

        def __enter__(self):
            return captured

        def __exit__(self, *_args):
            return False

    monkeypatch.setattr(components, "model_call_span", Span)
    monkeypatch.setattr(components, "record_model_response", lambda **kwargs: captured.update(response=kwargs))
    return captured


def test_registry_lists_every_call_with_stable_identity():
    ids = {spec.component_id for spec in COMPONENTS.all()}
    assert ids == {
        "tutoring.turn", "tutoring.turn-backup", "tutoring.leak-judge", "tutoring.visual-leak-judge", "companion.intent", "companion.scene-switch",
        "planning.intake", "task.intake", "evals.semantic-judge",
        "evaluation.review-aspects", "tutoring.image-target", "study.sprint-intake",
    }
    for spec in COMPONENTS.all():
        assert spec.version.startswith("v") and spec.model and spec.input_contract and spec.output_contract
        assert spec.prompt.id.rsplit(".", 1)[1].startswith("v")


def test_child_safety_components_are_protected_and_not_overridable():
    for component_id in ("tutoring.turn", "tutoring.turn-backup", "tutoring.leak-judge", "tutoring.visual-leak-judge"):
        spec = COMPONENTS.get(component_id)
        assert spec.risk_tier == "protected" and not spec.overridable
    assert COMPONENTS.get("planning.intake").overridable


def test_environment_cannot_override_a_snapshot_model():
    spec = COMPONENTS.get("planning.intake")
    raw = json.dumps({"planning.intake": "model-x"})
    assert resolve_model(spec, raw) == (spec.model, "config_snapshot")
    assert resolve_model(spec, "") == (spec.model, "config_snapshot")


@pytest.mark.parametrize("raw", [
    '{"tutoring.turn": "m"}', '{"tutoring.leak-judge": "m"}', '{"no.such": "m"}',
    "not-json", "[]", '{"planning.intake": ""}', '{"planning.intake": 3}',
])
def test_invalid_overrides_fail_at_load(raw):
    with pytest.raises((ValueError, KeyError)):
        validate_overrides(raw)


def test_invoke_sends_static_prompt_as_system_and_uses_spec(spans):
    spec = COMPONENTS.get("companion.intent")
    client = _Client('{"intent": "tutoring"}')
    payload = invoke_json_component(spec=spec, user="hi", client=client, settings_obj=_settings())

    assert payload == {"intent": "tutoring"}
    call = client.calls[0]
    assert call["model"] == spec.model
    assert call["temperature"] == spec.temperature and call["max_tokens"] == spec.max_tokens
    assert call["extra_body"] == {"enable_thinking": False}
    assert call["messages"][0] == {"role": "system", "content": spec.prompt.text}
    assert call["messages"][1] == {"role": "user", "content": "hi"}
    assert spans["span"]["component_id"] == "companion.intent"
    assert spans["span"]["component_version"] == "v9"
    assert spans["span"]["prompt_id"] == spec.prompt.id
    assert spans["span"]["definition_digest"] == spec.definition_digest
    assert spans["span"]["model_source"] == "config_snapshot"


def test_real_generation_export_keeps_sent_messages_prompt_id_and_raw_reply(monkeypatch):
    from langfuse._client.span_exporter import LangfuseTransformingSpanExporter
    from opentelemetry.sdk.trace import TracerProvider
    from opentelemetry.sdk.trace.export import SimpleSpanProcessor
    from opentelemetry.sdk.trace.export.in_memory_span_exporter import (
        InMemorySpanExporter,
    )

    from app.infrastructure.observability import telemetry

    monkeypatch.setenv("OTEL_SDK_DISABLED", "false")
    source = InMemorySpanExporter()
    provider = TracerProvider()
    provider.add_span_processor(SimpleSpanProcessor(source))
    monkeypatch.setattr(telemetry.trace, "get_tracer", provider.get_tracer)
    monkeypatch.setattr(telemetry, "_write_debug_audit", lambda *_args: None)
    spec = COMPONENTS.get("tutoring.turn")
    raw = '{"act":"chat","content":"先说说你的想法。"}'
    with telemetry.agent_turn_span():
        invoke_json_component(spec=spec, user="孩子的原话", client=_Client(raw), settings_obj=_settings())

    generation = next(s for s in source.get_finished_spans() if s.name == "llm.request")
    transformed = InMemorySpanExporter()
    LangfuseTransformingSpanExporter(
        exporter=transformed, media_manager=None, mask_otel_spans=None,
    ).export([generation])
    exported = transformed.get_finished_spans()[0]
    assert exported.attributes["ai.prompt_id"] == spec.prompt.id
    assert exported.attributes["ai.definition_digest"] == spec.definition_digest
    assert exported.attributes["langfuse.observation.metadata.definition_digest"] == spec.definition_digest
    assert json.loads(exported.attributes["langfuse.observation.input"]) == [
        {"role": "system", "content": spec.prompt.text},
        {"role": "user", "content": "孩子的原话"},
    ]
    assert exported.attributes["langfuse.observation.output"] == raw


def test_dynamic_prompt_uses_only_the_snapshot_model(spans):
    spec = COMPONENTS.get("task.intake")
    client = _Client('{"assistant_text":"已整理。"}')
    invoke_json_component(
        spec=spec, user=[{"type": "text", "text": "rendered"}], client=client,
        settings_obj=_settings(json.dumps({"task.intake": "model-x"})),
    )
    call = client.calls[0]
    assert [m["role"] for m in call["messages"]] == ["user"]
    assert call["model"] == spec.model
    assert spans["span"]["model_source"] == "config_snapshot"


@pytest.mark.parametrize("content", ["", "[]", "not-json"])
def test_invalid_provider_output_maps_to_stable_error(content):
    with pytest.raises(ModelGatewayError, match="invalid_model_candidate"):
        invoke_json_component(
            spec=COMPONENTS.get("companion.intent"), user="u", client=_Client(content), settings_obj=_settings(),
        )


def test_provider_failure_maps_to_transport_error():
    client = _Client('{"act":"chat","content":"先说说你的想法。"}')
    client.chat.completions.create = lambda **_: (_ for _ in ()).throw(RuntimeError("boom"))
    with pytest.raises(ModelGatewayError, match="model_transport_error"):
        invoke_json_component(spec=COMPONENTS.get("companion.intent"), user="u", client=client, settings_obj=_settings())


def test_agent_switch_gates_only_components_that_always_required_it(monkeypatch):
    monkeypatch.setattr(components, "settings", SimpleNamespace(
        agent_model_enabled=False, dashscope_api_key="k", agent_model_timeout_seconds=8, ai_model_overrides="",
    ))
    with pytest.raises(ModelGatewayError, match="model_provider_disabled"):
        invoke_json_component(spec=COMPONENTS.get("tutoring.turn"), user="u")
    assert not COMPONENTS.get("task.intake").requires_agent_switch
    assert not COMPONENTS.get("planning.intake").requires_agent_switch


def test_intent_component_returns_the_existing_json_boundary(monkeypatch):
    from app.infrastructure.ai import intent_classifier

    seen: dict = {}
    monkeypatch.setattr(
        intent_classifier.components, "invoke_json_component",
        lambda **kwargs: seen.update(kwargs) or {"intent": "tutoring"},
    )
    assert intent_classifier.complete_intent(content="这题怎么做", focus_agent_type=None) == '{"intent": "tutoring"}'
    assert seen["spec"].component_id == "companion.intent"


def test_tutoring_components_keep_existing_success_and_failure_boundaries(monkeypatch):
    from app.infrastructure.ai import tutor_turn_model

    seen: list[str] = []

    def succeed(**kwargs):
        seen.append(kwargs["spec"].component_id)
        return {"act": "hint"} if kwargs["spec"].component_id == "tutoring.turn" else leak_judge_facts()

    monkeypatch.setattr(tutor_turn_model.components, "invoke_json_component", succeed)
    assert tutor_turn_model.QwenTutorTurnGateway().complete(envelope={}, instruction="说明") == {"act": "hint"}
    assert tutor_turn_model.QwenLeakJudge().leaks(text="提示", task_title=None, problem_summary=None) == {
        "leaks": False, "reason": "none", "answer_protected": True,
    }
    assert seen == ["tutoring.turn", "tutoring.leak-judge"]

    captured: dict = {}
    monkeypatch.setattr(
        tutor_turn_model.components, "invoke_json_component",
        lambda **kwargs: captured.update(kwargs) or leak_judge_facts(),
    )
    assert tutor_turn_model.QwenLeakJudge().leaks(
        text="你写的答案对吗？", task_title=None, problem_summary=None,
        images=["data:image/jpeg;base64,YXV0aG9yaXplZA=="],
    ) == {"leaks": False, "reason": "none", "answer_protected": True}
    assert isinstance(captured["user"], list)
    assert captured["user"][-1]["image_url"]["url"] == "data:image/jpeg;base64,YXV0aG9yaXplZA=="

    monkeypatch.setattr(
        tutor_turn_model.components, "invoke_json_component",
        lambda **_kwargs: leak_judge_facts(premature_conclusion=True),
    )
    assert tutor_turn_model.QwenLeakJudge().leaks(text="这是答案", task_title=None, problem_summary=None) == {
        "leaks": True, "reason": "premature_conclusion", "answer_protected": True,
    }

    monkeypatch.setattr(
        tutor_turn_model.components, "invoke_json_component",
        lambda **_kwargs: (_ for _ in ()).throw(ModelGatewayError("model_transport_error")),
    )
    assert tutor_turn_model.QwenLeakJudge().leaks(text="提示", task_title=None, problem_summary=None) is None


def test_intake_services_map_gateway_errors_to_their_user_messages(monkeypatch):
    from app.api.schemas import TaskIntakeRequest
    from app.application.commands import task_intake

    request = TaskIntakeRequest(content="数学作业", history=[], tasks=[])
    for code, message in [("invalid_model_candidate", "格式异常"), ("model_transport_error", "暂不可用")]:
        monkeypatch.setattr(
            task_intake.components, "invoke_json_component",
            lambda code=code, **_k: (_ for _ in ()).throw(ModelGatewayError(code)),
        )
        with pytest.raises(task_intake.TaskIntakeError, match=message):
            task_intake.TaskIntakeService().respond(wards=[], request=request)


def test_static_prompts_are_templates():
    assert isinstance(COMPONENTS.get("tutoring.turn").prompt, PromptTemplate)


def test_model_assignment_matrix():
    """Deliberate choices; change one only with a reason and its regression."""
    matrix = {
        c.component_id: (c.model, c.accepts_images) for c in COMPONENTS.all()
    }
    assert matrix == {
        "tutoring.turn": ("qwen3.7-plus-2026-05-26", True),
        "evals.semantic-judge": ("qwen3.8-flash", True),
        "tutoring.image-target": ("qwen3.8-flash", True),
        "tutoring.turn-backup": ("qwen3.8-flash", True),
        "tutoring.leak-judge": ("qwen3.8-flash", True),
        "tutoring.visual-leak-judge": ("qwen-plus", False),
        "companion.intent": ("qwen-flash", False),
        "companion.scene-switch": ("qwen3.8-flash", True),
        "planning.intake": ("qwen3.7-plus-2026-05-26", True),
        "task.intake": ("qwen3.7-plus-2026-05-26", True),
            "evaluation.review-aspects": ("qwen-flash", False),
        "study.sprint-intake": ("qwen-flash", False),
    }
    # The judge must not share a model with the generator it audits.
    for judge in ("tutoring.leak-judge", "tutoring.visual-leak-judge"):
        assert COMPONENTS.get(judge).model != COMPONENTS.get("tutoring.turn").model


def test_text_only_components_never_send_image_parts(spans):
    user = [
        {"type": "text", "text": "{}"},
        {"type": "text", "text": "图片1："},
        {"type": "image_url", "image_url": {"url": "data:secret"}},
    ]
    client = _Client('{"intent": "tutoring"}')
    invoke_json_component(spec=COMPONENTS.get("companion.intent"), user=user, client=client, settings_obj=_settings())
    sent = client.calls[0]["messages"][1]["content"]
    assert all(part["type"] == "text" for part in sent)
    assert "data:secret" not in json.dumps(sent)

    client = _Client('{"act":"chat","content":"先说说你的想法。"}')
    invoke_json_component(spec=COMPONENTS.get("tutoring.turn"), user=user, client=client, settings_obj=_settings())
    assert client.calls[0]["messages"][1]["content"] == user

    client = _Client(json.dumps(leak_judge_facts()))
    invoke_json_component(spec=COMPONENTS.get("tutoring.leak-judge"), user=user, client=client, settings_obj=_settings())
    assert client.calls[0]["messages"][1]["content"] == user


def test_intake_components_get_a_longer_timeout_than_the_default():
    assert COMPONENTS.get("planning.intake").timeout_seconds == 60
    assert COMPONENTS.get("task.intake").timeout_seconds == 60


def test_thinking_mode_streams_chunks_hides_cot_and_records_reasoning_tokens(monkeypatch):
    from dataclasses import replace

    from opentelemetry.sdk.trace import TracerProvider
    from opentelemetry.sdk.trace.export import SimpleSpanProcessor
    from opentelemetry.sdk.trace.export.in_memory_span_exporter import (
        InMemorySpanExporter,
    )

    from app.infrastructure.observability import telemetry

    class StreamingClient:
        def __init__(self):
            self.calls: list[dict] = []
            self.chat = SimpleNamespace(completions=SimpleNamespace(create=self.create))

        def create(self, **kwargs):
            self.calls.append(kwargs)
            return iter(
                [
                    SimpleNamespace(
                        id="req-think-1",
                        choices=[
                            SimpleNamespace(
                                finish_reason=None,
                                delta=SimpleNamespace(
                                    reasoning_content="SECRET_COT_STEP_1", content=None
                                ),
                            )
                        ],
                        usage=None,
                    ),
                    SimpleNamespace(
                        id="req-think-1",
                        choices=[
                            SimpleNamespace(
                                finish_reason=None,
                                delta=SimpleNamespace(
                                    reasoning_content=None, content="```json\n{\"intent\":"
                                ),
                            )
                        ],
                        usage=None,
                    ),
                    SimpleNamespace(
                        id="req-think-1",
                        choices=[
                            SimpleNamespace(
                                finish_reason="stop",
                                delta=SimpleNamespace(
                                    reasoning_content=None, content="\"tutoring\"}\n```"
                                ),
                            )
                        ],
                        usage=SimpleNamespace(
                            prompt_tokens=20,
                            completion_tokens=55,
                            completion_tokens_details=SimpleNamespace(
                                reasoning_tokens=42
                            ),
                        ),
                    ),
                ]
            )

    monkeypatch.setenv("OTEL_SDK_DISABLED", "false")
    exporter = InMemorySpanExporter()
    provider = TracerProvider()
    provider.add_span_processor(SimpleSpanProcessor(exporter))
    monkeypatch.setattr(telemetry.trace, "get_tracer", provider.get_tracer)
    monkeypatch.setattr(telemetry, "_write_debug_audit", lambda *_args: None)

    spec = replace(
        COMPONENTS.get("companion.intent"),
        enable_thinking=True,
        thinking_budget=2048,
    )
    client = StreamingClient()
    payload = invoke_json_component(
        spec=spec, user="这道导数压轴题怎么做", client=client, settings_obj=_settings()
    )
    assert payload == {"intent": "tutoring"}
    call = client.calls[0]
    assert call["stream"] is True
    assert "response_format" not in call
    assert call["stream_options"] == {"include_usage": True}
    assert call["extra_body"] == {"enable_thinking": True, "thinking_budget": 2048}

    generation = next(
        s for s in exporter.get_finished_spans() if s.name == "llm.request"
    )
    assert 0 <= generation.attributes["llm.first_token_ms"] <= generation.attributes["llm.first_content_ms"] <= generation.attributes["llm.duration_ms"]
    assert generation.attributes["llm.provider_request_id"] == "req-think-1"
    assert generation.attributes["llm.finish_reason"] == "stop"
    assert generation.attributes["llm.stream_completed"] is True
    assert generation.attributes["llm.outcome"] == "ok"
    assert generation.attributes["llm.enable_thinking"] is True
    assert generation.attributes["llm.thinking_budget"] == 2048
    assert generation.attributes["llm.tokens_answer"] == 13
    assert generation.attributes["llm.tokens_reasoning"] == 42
    assert json.loads(generation.attributes["langfuse.observation.usage_details"]) == {
        "input": 20,
        "output": 55,
        "answer": 13,
        "reasoning": 42,
    }
    assert "SECRET_COT_STEP_1" not in json.dumps(dict(generation.attributes))


def test_completion_evidence_enforces_termination_and_separates_failure_kinds():
    from dataclasses import replace

    from app.infrastructure.ai.components import capture_llm_calls

    thinking_intent = replace(COMPONENTS.get("companion.intent"), enable_thinking=True)
    tutor_spec = replace(COMPONENTS.get("tutoring.turn"), enable_thinking=True)

    # 1. length: budget exhausted -> never delivered, classified as length_truncated
    class LengthStream:
        chat = SimpleNamespace(
            completions=SimpleNamespace(
                create=lambda **_kw: iter(
                    [
                        SimpleNamespace(
                            id="req-len-1",
                            choices=[
                                SimpleNamespace(
                                    finish_reason="length",
                                    delta=SimpleNamespace(content='{"intent":"tutoring"}'),
                                )
                            ],
                            usage=SimpleNamespace(
                                prompt_tokens=10,
                                completion_tokens=100,
                                completion_tokens_details={"reasoning_tokens": 90},
                            ),
                        )
                    ]
                )
            )
        )

    from app.agent_specs.execution_trace import Recorder
    recording = Recorder()
    with recording.capture(), capture_llm_calls() as calls:
        with pytest.raises(ModelGatewayError, match="invalid_model_candidate"):
            invoke_json_component(
                spec=thinking_intent,
                user="u",
                client=LengthStream(),
                settings_obj=_settings(),
            )
    assert len(calls) == 1
    assert recording.timings()[0]["outcome"] == "length_truncated"
    assert recording.timings()[0]["first_content_ms"] >= 0
    assert calls[0]["provider_request_id"] == "req-len-1"
    assert calls[0]["finish_reason"] == "length"
    assert calls[0]["stream_completed"] is True
    assert calls[0]["tokens_answer"] == 10
    assert calls[0]["tokens_reasoning"] == 90
    assert calls[0]["outcome"] == "length_truncated"

    # 2. No finish_reason: incomplete stream -> never parsed/delivered, transport error
    class IncompleteStream:
        chat = SimpleNamespace(
            completions=SimpleNamespace(
                create=lambda **_kw: iter(
                    [
                        SimpleNamespace(
                            id="req-inc-1",
                            choices=[
                                SimpleNamespace(
                                    finish_reason=None,
                                    delta=SimpleNamespace(content='{"intent":"tutoring"}'),
                                )
                            ],
                            usage=None,
                        )
                    ]
                )
            )
        )

    with capture_llm_calls() as calls:
        with pytest.raises(ModelGatewayError, match="model_transport_error"):
            invoke_json_component(
                spec=thinking_intent,
                user="u",
                client=IncompleteStream(),
                settings_obj=_settings(),
            )
    assert calls[0]["provider_request_id"] == "req-inc-1"
    assert calls[0]["finish_reason"] is None
    assert calls[0]["stream_completed"] is False
    assert calls[0]["outcome"] == "incomplete_stream"

    # 3. Mid-stream API exception -> preserves request_id, classified as api_error
    def broken_iter():
        yield SimpleNamespace(
            id="req-err-1",
            choices=[SimpleNamespace(finish_reason=None, delta=SimpleNamespace(content="{"))],
            usage=None,
        )
        raise RuntimeError("DashScope stream aborted")

    class ErrorStream:
        chat = SimpleNamespace(completions=SimpleNamespace(create=lambda **_kw: broken_iter()))

    with capture_llm_calls() as calls:
        with pytest.raises(ModelGatewayError, match="model_transport_error"):
            invoke_json_component(
                spec=thinking_intent,
                user="u",
                client=ErrorStream(),
                settings_obj=_settings(),
            )
    assert calls[0]["provider_request_id"] == "req-err-1"
    assert calls[0]["stream_completed"] is False
    assert calls[0]["outcome"] == "api_error"
    assert calls[0]["error_type"] == "RuntimeError"

    # 4. stop + invalid JSON vs stop + contract error
    with capture_llm_calls() as calls:
        with pytest.raises(ModelGatewayError, match="invalid_model_candidate"):
            invoke_json_component(
                spec=COMPONENTS.get("companion.intent"),
                user="u",
                client=_Client("{bad json", finish_reason="stop"),
                settings_obj=_settings(),
            )
        with pytest.raises(ModelGatewayError, match="invalid_model_candidate"):
            invoke_json_component(
                spec=COMPONENTS.get("companion.intent"),
                user="u",
                client=_Client('{"intent":"not_in_enum"}', finish_reason="stop"),
                settings_obj=_settings(),
            )
    assert [c["outcome"] for c in calls] == ["json_parse_error", "contract_error"]

    # 5. stop + valid JSON + structured-decoding whitespace gap (pure wire syntax, no punctuation guessing)
    gap_raw = '{"act":"guide","content":"不过题目问的是"   \n   ,"turn":{"type":"work","relation":"new"}}'
    normal_raw = '{"act":"guide","content":"先看第一句","turn":{"type":"work","relation":"new"}}'
    with capture_llm_calls() as calls:
        invoke_json_component(
            spec=tutor_spec,
            user="孩子的原话",
            client=_Client(gap_raw, finish_reason="stop"),
            settings_obj=_settings(),
        )
        invoke_json_component(
            spec=tutor_spec,
            user="孩子的原话",
            client=_Client(normal_raw, finish_reason="stop"),
            settings_obj=_settings(),
        )
    assert [c["outcome"] for c in calls] == ["stop_wire_gap", "ok"]
    assert [c["abrupt_detail"] for c in calls] == [
        "structured_decode_gap",
        None,
    ]


def test_stream_timing_ignores_metadata_and_survives_interruption(monkeypatch):
    ticks = iter([0.0, 0.25, 1.5])
    monkeypatch.setattr(components, "perf_counter", lambda: next(ticks))

    def chunks(**kwargs):
        yield SimpleNamespace(choices=[])
        for delta in (
            SimpleNamespace(content=""),
            SimpleNamespace(reasoning_content="private"),
            SimpleNamespace(content="{"),
        ):
            yield SimpleNamespace(choices=[SimpleNamespace(delta=delta)])
        raise TimeoutError()

    client = SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=chunks)))
    usage = {}
    with pytest.raises(TimeoutError):
        components.complete_json_chat(client=client, model="test", messages=[], temperature=0,
                                      max_tokens=10, enable_thinking=True, telemetry=usage)
    assert usage["first_token_ms"] == 250
    assert usage["first_content_ms"] == 1500
    assert "private" not in repr(usage)

    usage = {}
    components.complete_json_chat(client=_Client("{}"), model="test", messages=[], temperature=0,
                                  max_tokens=10, telemetry=usage)
    assert "first_token_ms" not in usage and "first_content_ms" not in usage
