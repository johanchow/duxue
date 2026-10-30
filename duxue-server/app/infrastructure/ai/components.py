"""Invoke configured model components through one observable gateway.

Model parameters and Prompt bodies come from agent_specs/agents and gates.
Secrets and provider endpoints remain deployment settings. The emergency
AI_MODEL_OVERRIDES switch applies only to standard components.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from functools import lru_cache
from typing import Literal

from jsonschema.exceptions import ValidationError as JSONSchemaValidationError

from app.agent_specs.contracts import validate_input, validate_output
from app.agent_specs.definitions import load_definitions
from app.bootstrap.settings import settings
from app.infrastructure.ai.errors import ModelGatewayError
from app.infrastructure.ai.prompts import PROMPTS, DynamicPrompt, PromptTemplate
from app.infrastructure.observability.telemetry import (
    model_call_span,
    record_model_response,
)

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


def _load_components() -> ComponentRegistry:
    from app.agent_specs.definitions import load_definitions

    specs = []
    for unit in load_definitions().units.values():
        for model in unit.models:
            specs.append(ComponentSpec(
                component_id=model.component_id,
                version=model.version or unit.version,
                operation=model.operation or unit.operation,
                agent_label=unit.agent_label,
                risk_tier=unit.risk_tier,
                model=model.name,
                prompt=PROMPTS[unit.prompt.id],
                input_contract=unit.input_contract,
                output_contract=unit.output_contract,
                max_tokens=model.max_output_tokens,
                temperature=model.temperature,
                accepts_images=unit.accepts_images,
                timeout_seconds=model.timeout_ms // 1000,
                requires_agent_switch=unit.requires_agent_switch,
            ))
    return ComponentRegistry(*specs)


COMPONENTS = _load_components()

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
    unit, _model_index = load_definitions().component(spec.component_id)
    validate_input(unit, user)
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
            component_id=spec.component_id, component_version=spec.version,
            prompt_id=spec.prompt.id, model_source=model_source,
            input_payload=messages,
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
            if not isinstance(payload, dict):
                raise TypeError("model returned a non-object")
            validate_output(unit, payload)
    except (ValueError, KeyError, TypeError, IndexError, AttributeError, JSONSchemaValidationError) as error:
        raise ModelGatewayError("invalid_model_candidate") from error
    except ModelGatewayError:
        raise
    except Exception as error:
        raise ModelGatewayError("model_transport_error") from error
    return payload


def invoke_agent_component(*, spec: ComponentSpec, user, client=None, settings_obj=None):
    """Wrap validated Agent data; adapters may unwrap to preserve existing ports."""
    from app.agent_specs.results import AgentResult, completed, validate_result
    unit, _ = load_definitions().component(spec.component_id)
    if unit.kind != "agent":
        raise ValueError(f"{unit.id}: Judge calls use the Gate protocol")
    options = {}
    if client is not None:
        options["client"] = client
    if settings_obj is not None:
        options["settings_obj"] = settings_obj
    try:
        payload = invoke_json_component(spec=spec, user=user, **options)
    except ModelGatewayError as error:
        code = str(error) if str(error) in unit.error_codes else "agent_execution_failed"
        return validate_result(AgentResult(status="failed", error_code=code))
    return completed(payload, needs_input=payload.get("clarification_required") is True or payload.get("act") == "clarify")
