"""The one table of every LLM call the server makes, plus its single invocation path.

Read ``COMPONENTS`` below to see all model calls: id, version, default model,
risk tier, prompt, contracts and generation parameters.  Prompt bodies live in
``prompts.py`` and are referenced from here, never copied.

What this module owns: which model/prompt/parameters a call uses, and making the
call identifiable and observable.  What it does not own: workflow routing,
context authorization, domain policy or fallbacks; the caller keeps its own
output validation and fallback.

Secrets and endpoints are deployment settings (``settings.dashscope_api_key``
etc.), never part of a spec.  The default model is part of behaviour, so it is
reviewed code here.  ``AI_MODEL_OVERRIDES`` is an emergency switch that may
only target ``standard`` components; ``protected`` ones need a code change.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from functools import lru_cache
from typing import Literal

from app.bootstrap.settings import settings
from app.infrastructure.ai.errors import ModelGatewayError
from app.infrastructure.ai.prompts import PROMPTS, DynamicPrompt, PromptTemplate
from app.infrastructure.observability.telemetry import model_call_span, record_model_response

# DashScope model ids (see docs/technical/infra-ai-components.md §4.2.3).
# Thinking is turned off at the call: these calls return JSON on a latency budget.
PLUS = "qwen3.7-plus-2026-05-26"  # vision + instruction following: tutoring, intake, advice
REPLY_FLASH = "qwen3.8-flash"     # short multimodal replies on the wait path
TEXT_FLASH = "qwen-flash"         # closed routing; a decision model needs another protocol
TEXT_PLUS = "qwen-plus"           # leak judge; must stay a different model from PLUS

RiskTier = Literal["protected", "standard"]
AgentLabel = Literal["planning", "tutoring", "reflection"]


@dataclass(frozen=True)
class ComponentSpec:
    """Code-owned declaration of one structured model call.

    ``protected`` components sit on a child-safety path (answer protection and
    its independent leak check).  Their model, prompt and parameters change only
    through code review and regression, never through an override.
    """

    component_id: str
    version: str
    operation: str
    agent_label: AgentLabel
    risk_tier: RiskTier
    model: str
    prompt: PromptTemplate | DynamicPrompt
    input_contract: str
    output_contract: str
    max_tokens: int
    temperature: float
    # Text-only models: image parts are replaced by a placeholder before sending.
    accepts_images: bool = True
    # None uses ``settings.agent_model_timeout_seconds``.
    timeout_seconds: int | None = None
    # Intake calls were never gated by the agent switch; keep that behaviour.
    requires_agent_switch: bool = True

    @property
    def overridable(self) -> bool:
        return self.risk_tier == "standard"


class ComponentRegistry:
    def __init__(self, *specs: ComponentSpec):
        self._specs = {spec.component_id: spec for spec in specs}
        if len(self._specs) != len(specs):
            raise ValueError("duplicate AI component id")
        for spec in specs:
            if PROMPTS.get(spec.prompt.id) is not spec.prompt:
                raise ValueError(f"{spec.component_id}: prompt {spec.prompt.id} is not registered in prompts.py")

    def get(self, component_id: str) -> ComponentSpec:
        try:
            return self._specs[component_id]
        except KeyError as error:
            raise KeyError(f"unknown AI component: {component_id}") from error

    def all(self) -> tuple[ComponentSpec, ...]:
        return tuple(self._specs.values())


COMPONENTS = ComponentRegistry(
    # --- protected: child-safety path -------------------------------------
    ComponentSpec(
        component_id="tutoring.turn", version="v16", operation="tutor_turn",
        agent_label="tutoring", risk_tier="protected", model=PLUS,
        prompt=PROMPTS["tutoring.turn.system.v16"],
        input_contract="tutor-turn.v4", output_contract="tutor-turn-candidate.v4",
        max_tokens=1100, temperature=0.2,
    ),
    ComponentSpec(
        component_id="tutoring.leak-judge", version="v6", operation="tutor_leak_check",
        agent_label="tutoring", risk_tier="protected", model=TEXT_PLUS,
        prompt=PROMPTS["tutoring.leak-judge.system.v6"],
        input_contract="leak-judge-input.v5", output_contract="leak-judge-verdict.v2",
        max_tokens=80, temperature=0,
        accepts_images=False,
    ),
    ComponentSpec(
        component_id="tutoring.visual-leak-judge", version="v2", operation="tutor_visual_leak_check",
        agent_label="tutoring", risk_tier="protected", model=TEXT_PLUS,
        prompt=PROMPTS["tutoring.visual-leak-judge.system.v2"],
        input_contract="visual-leak-judge-input.v2", output_contract="leak-judge-verdict.v1",
        max_tokens=40, temperature=0.2,
        accepts_images=False,
    ),
    # --- standard ----------------------------------------------------------
    ComponentSpec(
        component_id="companion.intent", version="v1", operation="intent_proposal",
        agent_label="planning", risk_tier="standard", model=TEXT_FLASH,
        prompt=PROMPTS["companion.intent.system.v1"],
        input_contract="intent-input.v1", output_contract="intent-proposal.v1",
        max_tokens=60, temperature=0,
        accepts_images=False,
    ),
    ComponentSpec(
        component_id="planning.reply", version="v1", operation="agent_text",
        agent_label="planning", risk_tier="standard", model=REPLY_FLASH,
        prompt=PROMPTS["companion.agent-text.system.v1"],
        input_contract="agent-text-input.v1", output_contract="agent-text-candidate.v1",
        max_tokens=450, temperature=0.2,
    ),
    ComponentSpec(
        component_id="reflection.advice", version="v1", operation="agent_text",
        agent_label="reflection", risk_tier="standard", model=PLUS,
        prompt=PROMPTS["companion.agent-text.system.v1"],
        input_contract="agent-text-input.v1", output_contract="agent-text-candidate.v1",
        max_tokens=450, temperature=0.2,
        accepts_images=False,
    ),
    ComponentSpec(
        component_id="planning.intake", version="v1", operation="plan_intake",
        agent_label="planning", risk_tier="standard", model=PLUS,
        prompt=PROMPTS["planning.intake.prompt.v1"],
        input_contract="plan-intake-input.v1", output_contract="plan-intake-result.v1",
        max_tokens=1600, temperature=0, requires_agent_switch=False,
        timeout_seconds=60,
    ),
    ComponentSpec(
        component_id="task.intake", version="v1", operation="task_intake",
        agent_label="planning", risk_tier="standard", model=PLUS,
        prompt=PROMPTS["task.intake.prompt.v1"],
        input_contract="task-intake-input.v1", output_contract="task-intake-result.v1",
        max_tokens=1600, temperature=0, requires_agent_switch=False,
        timeout_seconds=60,
    ),
)


@lru_cache(maxsize=8)
def _parse_overrides(raw: str) -> dict[str, str]:
    if not raw.strip():
        return {}
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as error:
        raise ValueError("AI_MODEL_OVERRIDES must be a JSON object") from error
    if not isinstance(data, dict) or not all(isinstance(k, str) and isinstance(v, str) and v for k, v in data.items()):
        raise ValueError("AI_MODEL_OVERRIDES must map component ids to model names")
    for component_id in data:
        if not COMPONENTS.get(component_id).overridable:
            raise ValueError(f"AI_MODEL_OVERRIDES cannot target protected component {component_id}")
    return data


def validate_overrides(raw: str | None = None) -> None:
    """Fail fast at startup for an unknown id, protected target or malformed value."""
    _parse_overrides(settings.ai_model_overrides if raw is None else raw)


def resolve_model(spec: ComponentSpec, raw_overrides: str | None = None) -> tuple[str, Literal["registry", "env_override"]]:
    overrides = _parse_overrides(settings.ai_model_overrides if raw_overrides is None else raw_overrides)
    if spec.component_id in overrides:
        return overrides[spec.component_id], "env_override"
    return spec.model, "registry"


def model_for(component_id: str) -> str:
    """The model a component will use now; for trace/UI labels."""
    return resolve_model(COMPONENTS.get(component_id))[0]


def _without_images(user):
    """Text-only models reject image parts; say so in-band instead of failing the call."""
    if not isinstance(user, list):
        return user
    return [
        {"type": "text", "text": "（此图片未提供给本模型）"} if part.get("type") == "image_url" else part
        for part in user
    ]


def invoke_json_component(*, spec: ComponentSpec, user, client=None, settings_obj=None) -> dict:
    """Call a registered JSON component and return only a JSON object.

    A static prompt is sent as the system message; a dynamic prompt is rendered by
    the caller into ``user``.  Provider failures and malformed payloads use the
    stable ``ModelGatewayError`` vocabulary so application fallbacks keep their
    prior semantics.
    """
    runtime_settings = settings_obj or settings
    if settings_obj is None and spec.requires_agent_switch:
        if not runtime_settings.agent_model_enabled:
            raise ModelGatewayError("model_provider_disabled")
        if not runtime_settings.dashscope_api_key:
            raise ModelGatewayError("model_provider_not_configured")
    if client is None:
        from app.infrastructure.ai.client import dashscope_client
        client = dashscope_client(timeout=spec.timeout_seconds or runtime_settings.agent_model_timeout_seconds)

    model, model_source = resolve_model(spec, getattr(runtime_settings, "ai_model_overrides", ""))
    messages = [{"role": "user", "content": user if spec.accepts_images else _without_images(user)}]
    if isinstance(spec.prompt, PromptTemplate):
        messages.insert(0, {"role": "system", "content": spec.prompt.text})
    try:
        with model_call_span(
            operation=spec.operation, model=model, agent_type=spec.agent_label,
            component_id=spec.component_id, component_version=spec.version, model_source=model_source,
        ) as telemetry:
            response = client.chat.completions.create(
                model=model,
                messages=messages,
                temperature=spec.temperature,
                max_tokens=spec.max_tokens,
                response_format={"type": "json_object"},
                extra_body={"enable_thinking": False},
            )
            usage = response.usage
            telemetry["provider_request_id"] = getattr(response, "id", None)
            telemetry["tokens_in"] = getattr(usage, "prompt_tokens", None)
            telemetry["tokens_out"] = getattr(usage, "completion_tokens", None)
            raw = (response.choices[0].message.content or "").strip()
            record_model_response(
                agent_type=spec.agent_label, model=model, content=raw, operation=spec.operation,
                component_id=spec.component_id, component_version=spec.version,
            )
            payload = json.loads(raw)
    except (ValueError, KeyError, TypeError, IndexError, AttributeError) as error:
        raise ModelGatewayError("invalid_model_candidate") from error
    except ModelGatewayError:
        raise
    except Exception as error:
        raise ModelGatewayError("model_transport_error") from error
    if not isinstance(payload, dict):
        raise ModelGatewayError("invalid_model_candidate")
    return payload
