from __future__ import annotations

import json
from types import SimpleNamespace

import pytest

from app.infrastructure.ai import components
from app.infrastructure.ai.components import COMPONENTS, invoke_json_component, resolve_model, validate_overrides
from app.infrastructure.ai.errors import ModelGatewayError
from app.infrastructure.ai.prompts import PromptTemplate


# conftest patches ``generate`` for every test; keep the real one for this module.
from app.infrastructure.ai.model_gateway import QwenAgentModelGateway
_REAL_GENERATE = QwenAgentModelGateway.generate


class _Client:
    def __init__(self, content: str):
        self.content = content
        self.calls: list[dict] = []
        self.chat = SimpleNamespace(completions=SimpleNamespace(create=self.create))

    def create(self, **kwargs):
        self.calls.append(kwargs)
        return SimpleNamespace(
            id="provider-request-1",
            usage=SimpleNamespace(prompt_tokens=7, completion_tokens=3),
            choices=[SimpleNamespace(message=SimpleNamespace(content=self.content))],
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
        "tutoring.turn", "tutoring.leak-judge", "companion.intent",
        "planning.reply", "reflection.advice", "planning.intake", "task.intake",
    }
    for spec in COMPONENTS.all():
        assert spec.version == "v1" and spec.model and spec.input_contract and spec.output_contract
        assert spec.prompt.id.endswith(".v1")


def test_child_safety_components_are_protected_and_not_overridable():
    for component_id in ("tutoring.turn", "tutoring.leak-judge"):
        spec = COMPONENTS.get(component_id)
        assert spec.risk_tier == "protected" and not spec.overridable
    assert COMPONENTS.get("planning.intake").overridable


def test_override_applies_to_standard_component_and_is_marked():
    spec = COMPONENTS.get("planning.intake")
    raw = json.dumps({"planning.intake": "model-x"})
    assert resolve_model(spec, raw) == ("model-x", "env_override")
    assert resolve_model(spec, "") == (spec.model, "registry")


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
    assert spans["span"]["component_version"] == "v1"
    assert spans["span"]["model_source"] == "registry"


def test_invoke_dynamic_prompt_has_no_system_message_and_records_override(spans):
    spec = COMPONENTS.get("task.intake")
    client = _Client("{}")
    invoke_json_component(
        spec=spec, user=[{"type": "text", "text": "rendered"}], client=client,
        settings_obj=_settings(json.dumps({"task.intake": "model-x"})),
    )
    call = client.calls[0]
    assert [m["role"] for m in call["messages"]] == ["user"]
    assert call["model"] == "model-x"
    assert spans["span"]["model_source"] == "env_override"


@pytest.mark.parametrize("content", ["", "[]", "not-json"])
def test_invalid_provider_output_maps_to_stable_error(content):
    with pytest.raises(ModelGatewayError, match="invalid_model_candidate"):
        invoke_json_component(
            spec=COMPONENTS.get("companion.intent"), user="u", client=_Client(content), settings_obj=_settings(),
        )


def test_provider_failure_maps_to_transport_error():
    client = _Client("{}")
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
        return {"act": "hint"} if kwargs["spec"].component_id == "tutoring.turn" else {"leaks": False}

    monkeypatch.setattr(tutor_turn_model.components, "invoke_json_component", succeed)
    assert tutor_turn_model.QwenTutorTurnGateway().complete(envelope={}, instruction="说明") == {"act": "hint"}
    assert tutor_turn_model.QwenLeakJudge().leaks(text="提示", task_title=None, problem_summary=None) is False
    assert seen == ["tutoring.turn", "tutoring.leak-judge"]

    monkeypatch.setattr(
        tutor_turn_model.components, "invoke_json_component",
        lambda **_kwargs: (_ for _ in ()).throw(ModelGatewayError("model_transport_error")),
    )
    assert tutor_turn_model.QwenLeakJudge().leaks(text="提示", task_title=None, problem_summary=None) is None


@pytest.mark.parametrize("agent_type,component_id", [("planning", "planning.reply"), ("reflection", "reflection.advice")])
def test_agent_text_gateway_uses_registered_component_and_validates(monkeypatch, agent_type, component_id):
    from app.infrastructure.ai import model_gateway

    seen: dict = {}
    monkeypatch.setattr(
        model_gateway.components, "invoke_json_component",
        lambda **kwargs: seen.update(kwargs) or {"content": "好的"},
    )
    candidate = _REAL_GENERATE(QwenAgentModelGateway(), agent_type=agent_type, envelope={}, instruction="i")
    assert candidate.content == "好的" and seen["spec"].component_id == component_id

    monkeypatch.setattr(model_gateway.components, "invoke_json_component", lambda **_: {"content": ""})
    with pytest.raises(ModelGatewayError, match="invalid_model_candidate"):
        _REAL_GENERATE(QwenAgentModelGateway(), agent_type=agent_type, envelope={}, instruction="i")


def test_intake_services_map_gateway_errors_to_their_user_messages(monkeypatch):
    from app.api.schemas import TaskIntakeRequest
    from app.application.commands import task_intake

    request = TaskIntakeRequest(content="数学作业", history=[], tasks=[])
    for code, message in [("invalid_model_candidate", "格式异常"), ("model_transport_error", "暂不可用")]:
        monkeypatch.setattr(
            task_intake.components, "invoke_json_component",
            lambda **_k: (_ for _ in ()).throw(ModelGatewayError(code)),
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
        "tutoring.leak-judge": ("qwen-plus", False),
        "companion.intent": ("qwen-flash", False),
        "planning.reply": ("qwen3.8-flash", True),
        "reflection.advice": ("qwen3.7-plus-2026-05-26", False),
        "planning.intake": ("qwen3.7-plus-2026-05-26", True),
        "task.intake": ("qwen3.7-plus-2026-05-26", True),
    }
    # The judge must not share a model with the generator it audits.
    assert COMPONENTS.get("tutoring.leak-judge").model != COMPONENTS.get("tutoring.turn").model


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

    client = _Client("{}")
    invoke_json_component(spec=COMPONENTS.get("tutoring.turn"), user=user, client=client, settings_obj=_settings())
    assert client.calls[0]["messages"][1]["content"] == user


def test_intake_components_get_a_longer_timeout_than_the_default():
    assert COMPONENTS.get("planning.intake").timeout_seconds == 60
    assert COMPONENTS.get("task.intake").timeout_seconds == 60
