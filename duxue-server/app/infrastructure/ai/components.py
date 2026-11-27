"""Invoke configured model components through one observable gateway.

Model parameters and Prompt bodies come from immutable Admin snapshots.
Secrets and provider endpoints remain deployment settings.
"""

from __future__ import annotations

import json
import logging
import re
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass
from time import perf_counter
from typing import Any, Literal

from jsonschema.exceptions import ValidationError as JSONSchemaValidationError

from app.agent_specs.contracts import validate_input, validate_output
from app.agent_specs.definitions import active_definitions, load_definitions
from app.bootstrap.settings import settings
from app.infrastructure.ai.client import remaining_model_time
from app.infrastructure.ai.errors import ModelGatewayError, ModelTimeBudgetExceeded
from app.infrastructure.ai.prompts import PROMPTS, DynamicPrompt, PromptTemplate
from app.infrastructure.observability.telemetry import (
    model_call_span,
    record_model_rejection,
    record_model_response,
)

RiskTier = Literal["protected", "standard"]
AgentLabel = Literal["planning", "tutoring", "reflection"]


@dataclass(frozen=True)
class ComponentSpec:
    """Code-owned declaration of one structured model call.

    ``protected`` components sit on a child-safety path (answer protection and
    its independent leak check). Their model, prompt and parameters come from
    an approved complete configuration artifact; environment overrides cannot
    change a pinned snapshot or bypass code-owned safety gates.
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
    definition_digest: str | None = None
    enable_thinking: bool = False
    thinking_budget: int | None = None
    reasoning_effort: str | None = None
    thinking_effort: Literal["off", "low", "medium", "high"] | None = None

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
        if self._specs and active_definitions() is None:
            return self._specs[component_id]
        definitions = load_definitions()
        unit, index = definitions.component(component_id)
        model = unit.models[index]
        from app.infrastructure.ai.thinking_policy import resolve_provider_thinking

        effort = model.thinking_effort or resolve_provider_thinking(
            model.name, enable_thinking=model.enable_thinking,
            thinking_budget=model.thinking_budget,
        ).effective_effort
        return ComponentSpec(
            component_id, model.version or unit.version, model.operation or unit.operation,
            unit.agent_label, unit.risk_tier, model.name, PROMPTS[unit.prompt.id],
            unit.input_contract, unit.output_contract, model.max_output_tokens,
            model.temperature, unit.accepts_images, model.timeout_ms // 1000,
            unit.requires_agent_switch, definitions.definition_digest(component_id),
            thinking_effort=effort,
        )

    def all(self) -> tuple[ComponentSpec, ...]:
        identifiers = self._specs or load_definitions().components
        return tuple(self.get(identifier) for identifier in identifiers)


COMPONENTS = ComponentRegistry()


def validate_overrides(raw: str | None = None) -> None:
    """Reject the retired hidden configuration source before serving requests."""
    value = settings.ai_model_overrides if raw is None else raw
    if value.strip() and json.loads(value) != {}:
        raise ValueError("AI_MODEL_OVERRIDES已停用，请在Admin配置模型，评测使用显式--model")


def resolve_model(spec: ComponentSpec, raw_overrides: str | None = None) -> tuple[str, Literal["config_snapshot"]]:
    # A model experiment is an explicit ComponentSpec copy in the eval process.
    # Process environment must never override an Admin snapshot.
    return spec.model, "config_snapshot"


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


CompletionOutcome = Literal[
    "ok",
    "stop_wire_gap",
    "length_truncated",
    "incomplete_stream",
    "non_stop_finish",
    "api_error",
    "json_parse_error",
    "contract_error",
]
COMPLETION_OUTCOMES: tuple[CompletionOutcome, ...] = (
    "ok",
    "stop_wire_gap",
    "length_truncated",
    "incomplete_stream",
    "non_stop_finish",
    "api_error",
    "json_parse_error",
    "contract_error",
)

_llm_call_log: ContextVar[list[dict[str, Any]] | None] = ContextVar(
    "duxue_llm_call_log", default=None
)
# Deterministic JSON wire-format check only (never prose punctuation heuristics):
# In compact single-line JSON, constrained-decoding premature string closure emits
# multi-character whitespace/newline padding right between closing `"` and `,` or `}`.
_DECODE_WHITESPACE_GAP = re.compile(
    r'"(?:\\.|[^"\\])*"(?:[ \t]*[\r\n]+[ \t\r\n]*,|[ \t]{2,}[,}])'
)
_PRETTY_JSON_PREFIX = re.compile(r"^\{\s*\r?\n\s+\"")


@contextmanager
def capture_llm_calls() -> Iterator[list[dict[str, Any]]]:
    """Collect per-call completion and failure-stage records within a scope."""
    records: list[dict[str, Any]] = []
    token = _llm_call_log.set(records)
    try:
        yield records
    finally:
        _llm_call_log.reset(token)


def _record_call_evidence(entry: dict[str, Any]) -> None:
    sink = _llm_call_log.get()
    if sink is not None:
        sink.append(entry)


@dataclass(frozen=True)
class ChatCompletionResult:
    raw: str
    raw_wire: str = ""
    finish_reason: str | None = None
    stream_completed: bool = False
    provider_request_id: str | None = None
    tokens_in: int | None = None
    tokens_out: int | None = None
    tokens_reasoning: int | None = None
    tokens_answer: int | None = None


def _reasoning_tokens(usage: Any) -> int | None:
    if usage is None:
        return None
    details = getattr(usage, "completion_tokens_details", None)
    if isinstance(details, dict):
        value = details.get("reasoning_tokens")
    else:
        value = getattr(details, "reasoning_tokens", None)
    return value if type(value) is int else None


def _answer_tokens(tokens_out: int | None, tokens_reasoning: int | None) -> int | None:
    if tokens_out is None:
        return None
    return max(0, tokens_out - (tokens_reasoning or 0))


def _unwrap_json_fence(raw: str) -> str:
    """Strip a single outer Markdown code fence when a thinking model wraps JSON."""
    text = raw.strip()
    if not (text.startswith("```") and text.endswith("```")):
        return text
    lines = text.splitlines()
    if (
        len(lines) >= 2
        and lines[0].strip().lower() in {"```", "```json"}
        and lines[-1].strip() == "```"
    ):
        return "\n".join(lines[1:-1]).strip()
    return text


def has_json_wire_whitespace_gap(raw_wire: str) -> bool:
    """Detect constrained-decoding whitespace padding between a closed string and `,`/`}`.

    Pure JSON wire-format syntax check; never inspects natural-language prose or punctuation.
    """
    stripped_wire = _unwrap_json_fence(raw_wire)
    return bool(
        stripped_wire.startswith("{")
        and not _PRETTY_JSON_PREFIX.match(stripped_wire)
        and _DECODE_WHITESPACE_GAP.search(stripped_wire)
    )


def complete_json_chat(
    *,
    client: Any = None,
    timeout: float | None = None,
    model: str,
    messages: list[dict[str, Any]],
    temperature: float,
    max_tokens: int,
    enable_thinking: bool = False,
    thinking_budget: int | None = None,
    reasoning_effort: str | None = None,
    thinking_effort: Literal["off", "low", "medium", "high"] | None = None,
    telemetry: dict[str, Any] | None = None,
) -> ChatCompletionResult:
    """Execute one structured JSON chat completion.

    DashScope hybrid/thinking models require streaming when ``enable_thinking=True``.
    Whether ``response_format={"type": "json_object"}`` is sent alongside thinking is
    governed per model family by ``resolved_thinking.supports_json_object_with_thinking``
    (enabled for verified DeepSeek models; disabled for Qwen hybrid-thinking models to
    avoid constrained-decoding quote truncation and HTTP 400 aborts).
    ``reasoning_content`` is intentionally discarded so chain-of-thought text never
    enters Ward-visible output or production trace payloads.
    """
    from app.infrastructure.ai.thinking_policy import resolve_provider_thinking

    resolved_thinking = resolve_provider_thinking(
        model,
        effort=thinking_effort,
        enable_thinking=enable_thinking,
        thinking_budget=thinking_budget,
        reasoning_effort=reasoning_effort,
    )
    enable_thinking = resolved_thinking.enable_thinking
    thinking_budget = resolved_thinking.thinking_budget
    reasoning_effort = resolved_thinking.reasoning_effort

    if client is None:
        from app.infrastructure.ai.client import dashscope_client

        with dashscope_client(timeout=timeout) as owned_client:
            return complete_json_chat(
                client=owned_client,
                model=model,
                messages=messages,
                temperature=temperature,
                max_tokens=max_tokens,
                enable_thinking=enable_thinking,
                thinking_budget=thinking_budget,
                reasoning_effort=reasoning_effort,
                thinking_effort=None,
                telemetry=telemetry,
            )

    if not enable_thinking:
        response = client.chat.completions.create(
            model=model,
            messages=messages,
            temperature=temperature,
            max_tokens=max_tokens,
            response_format={"type": "json_object"},
            extra_body={"enable_thinking": False},
        )
        usage = getattr(response, "usage", None)
        choice = response.choices[0]
        raw_wire = choice.message.content or ""
        finish_reason = getattr(choice, "finish_reason", None)
        tokens_in = getattr(usage, "prompt_tokens", None)
        tokens_out = getattr(usage, "completion_tokens", None)
        tokens_reasoning = _reasoning_tokens(usage)
        tokens_answer = _answer_tokens(tokens_out, tokens_reasoning)
        result = ChatCompletionResult(
            raw=raw_wire.strip(),
            raw_wire=raw_wire,
            finish_reason=finish_reason,
            stream_completed=finish_reason is not None,
            provider_request_id=getattr(response, "id", None),
            tokens_in=tokens_in,
            tokens_out=tokens_out,
            tokens_reasoning=tokens_reasoning,
            tokens_answer=tokens_answer,
        )
        if telemetry is not None:
            telemetry.update(
                provider_request_id=result.provider_request_id,
                finish_reason=result.finish_reason,
                stream_completed=result.stream_completed,
                tokens_in=result.tokens_in,
                tokens_out=result.tokens_out,
                tokens_reasoning=result.tokens_reasoning,
                tokens_answer=result.tokens_answer,
            )
        return result

    extra_body: dict[str, Any] = {"enable_thinking": True}
    if reasoning_effort is not None:
        extra_body["reasoning_effort"] = reasoning_effort
    if thinking_budget is not None:
        extra_body["thinking_budget"] = thinking_budget
    request_kwargs: dict[str, Any] = {
        "model": model,
        "messages": messages,
        "temperature": temperature,
        "max_tokens": max_tokens,
        "stream": True,
        "stream_options": {"include_usage": True},
        "extra_body": extra_body,
    }
    if resolved_thinking.supports_json_object_with_thinking:
        request_kwargs["response_format"] = {"type": "json_object"}
    started = perf_counter()
    response = client.chat.completions.create(**request_kwargs)
    if hasattr(response, "choices"):
        usage = getattr(response, "usage", None)
        choice = response.choices[0]
        raw_wire = choice.message.content or ""
        finish_reason = getattr(choice, "finish_reason", None)
        tokens_in = getattr(usage, "prompt_tokens", None)
        tokens_out = getattr(usage, "completion_tokens", None)
        tokens_reasoning = _reasoning_tokens(usage)
        tokens_answer = _answer_tokens(tokens_out, tokens_reasoning)
        result = ChatCompletionResult(
            raw=_unwrap_json_fence(raw_wire),
            raw_wire=raw_wire,
            finish_reason=finish_reason,
            stream_completed=finish_reason is not None,
            provider_request_id=getattr(response, "id", None),
            tokens_in=tokens_in,
            tokens_out=tokens_out,
            tokens_reasoning=tokens_reasoning,
            tokens_answer=tokens_answer,
        )
        if telemetry is not None:
            telemetry.update(
                provider_request_id=result.provider_request_id,
                finish_reason=result.finish_reason,
                stream_completed=result.stream_completed,
                tokens_in=result.tokens_in,
                tokens_out=result.tokens_out,
                tokens_reasoning=result.tokens_reasoning,
                tokens_answer=result.tokens_answer,
            )
        return result

    parts: list[str] = []
    request_id: str | None = None
    finish_reason: str | None = None
    usage: Any = None
    try:
        for chunk in response:
            remaining_model_time()
            request_id = getattr(chunk, "id", None) or request_id
            chunk_usage = getattr(chunk, "usage", None)
            if chunk_usage is not None:
                usage = chunk_usage
            choices = getattr(chunk, "choices", None) or []
            if not choices:
                continue
            choice = choices[0]
            finish_reason = getattr(choice, "finish_reason", None) or finish_reason
            delta = getattr(choice, "delta", None) or getattr(choice, "message", None)
            if delta is not None:
                piece = getattr(delta, "content", None)
                if telemetry is not None and "first_token_ms" not in telemetry:
                    if piece or getattr(delta, "reasoning_content", None):
                        telemetry["first_token_ms"] = round((perf_counter() - started) * 1000)
                if piece:
                    if telemetry is not None and not parts:
                        telemetry["first_content_ms"] = round((perf_counter() - started) * 1000)
                    parts.append(piece)
    finally:
        tokens_in = getattr(usage, "prompt_tokens", None)
        tokens_out = getattr(usage, "completion_tokens", None)
        tokens_reasoning = _reasoning_tokens(usage)
        tokens_answer = _answer_tokens(tokens_out, tokens_reasoning)
        if telemetry is not None:
            telemetry.update(
                provider_request_id=request_id,
                finish_reason=finish_reason,
                stream_completed=finish_reason is not None,
                tokens_in=tokens_in,
                tokens_out=tokens_out,
                tokens_reasoning=tokens_reasoning,
                tokens_answer=tokens_answer,
            )

    raw_wire = "".join(parts)
    return ChatCompletionResult(
        raw=_unwrap_json_fence(raw_wire),
        raw_wire=raw_wire,
        finish_reason=finish_reason,
        stream_completed=finish_reason is not None,
        provider_request_id=request_id,
        tokens_in=tokens_in,
        tokens_out=tokens_out,
        tokens_reasoning=tokens_reasoning,
        tokens_answer=tokens_answer,
    )


def validate_json_completion(
    completion: ChatCompletionResult,
    *,
    unit_id: str | None = None,
    validate_payload: Callable[[dict[str, Any]], None] | None = None,
) -> tuple[dict[str, Any], CompletionOutcome, str | None]:
    """Enforce termination gates and classify JSON/contract/wire outcomes."""
    if not completion.stream_completed or completion.finish_reason is None:
        raise _CompletionClassifiedError("incomplete_stream", "model_transport_error")
    if completion.finish_reason == "length":
        raise _CompletionClassifiedError("length_truncated", "invalid_model_candidate")
    if completion.finish_reason != "stop":
        raise _CompletionClassifiedError("non_stop_finish", "invalid_model_candidate")

    simple_review = False
    if unit_id == "tutoring.mentor-review":
        from app.agent_specs.guardian_contracts import (
            MENTOR_REPAIR_ID,
            normalize_review_shape,
            review_json_object,
        )

        simple_review = MENTOR_REPAIR_ID not in load_definitions().units
    try:
        payload = json.loads(completion.raw, object_pairs_hook=review_json_object if simple_review else None)
    except ValueError as error:
        raise _CompletionClassifiedError(
            "json_parse_error",
            "invalid_model_candidate",
            detail=f"{type(error).__name__}: {error}",
        ) from error
    if simple_review:
        payload = normalize_review_shape(payload)

    try:
        if not isinstance(payload, dict):
            raise TypeError("model returned a non-object")
        if validate_payload is not None:
            validate_payload(payload)
    except (
        ValueError,
        KeyError,
        TypeError,
        IndexError,
        AttributeError,
        JSONSchemaValidationError,
    ) as error:
        raise _CompletionClassifiedError(
            "contract_error", "invalid_model_candidate"
        ) from error

    wire_gap = has_json_wire_whitespace_gap(completion.raw_wire)
    outcome: CompletionOutcome = "stop_wire_gap" if wire_gap else "ok"
    detail = "structured_decode_gap" if wire_gap else None
    return payload, outcome, detail


_JSON_SYNTAX_REPAIR_SYSTEM_PROMPT = (
    "你是严格的 JSON 语法修复器。给定一段因语法错误（例如未转义双引号、LaTeX 反斜杠、"
    "多余逗号、缺少括号或前后夹杂非 JSON 文本）导致无法被 JSON 解析器解析的原始输出，"
    "请仅修复其 JSON 语法，使其成为严格合法的单个 JSON 对象。\n"
    "硬性规则：\n"
    "1. 严禁修改、增删、改写或捏造任何语义事实、数字、结论、字段名或字段结构；\n"
    "2. 仅输出修复后的合法 JSON 对象，不要添加任何解释或 Markdown 代码块。"
)


def _preview_raw(text: str, *, limit: int = 280) -> str:
    compact = " ".join(text.split())
    if len(compact) <= limit:
        return compact
    return f"{compact[:limit]}..."


def _resolve_json_repair_model(runtime_settings) -> tuple[str, str]:
    try:
        backup_spec = COMPONENTS.get("tutoring.turn-backup")
        return resolve_model(backup_spec, getattr(runtime_settings, "ai_model_overrides", ""))
    except Exception:  # noqa: BLE001
        return "qwen3.8-flash", "default"


def _try_repair_json_syntax(
    *,
    raw: str,
    json_error: str | None,
    client,
    runtime_settings,
) -> ChatCompletionResult | None:
    """Attempt a fast text-only JSON syntax repair without altering semantic facts."""
    repair_model, model_source = _resolve_json_repair_model(runtime_settings)
    user_content = f"JSON 解析错误：{json_error or 'invalid JSON'}\n\n待修复原始输出：\n{raw}"
    repair_messages = [
        {"role": "system", "content": _JSON_SYNTAX_REPAIR_SYSTEM_PROMPT},
        {"role": "user", "content": user_content},
    ]
    from app.infrastructure.ai.client import observe_transport

    try:
        with model_call_span(
            operation="json_syntax_repair",
            model=repair_model,
            agent_type="json_syntax_repair",
            component_id=None,
            prompt_id="json_syntax_repair.v1",
            model_source=model_source,
            enable_thinking=False,
            input_payload=repair_messages,
        ) as repair_telemetry, observe_transport(repair_telemetry):
            repaired = complete_json_chat(
                client=client,
                model=repair_model,
                messages=repair_messages,
                temperature=0,
                max_tokens=max(1024, min(4096, len(raw) * 2)),
                enable_thinking=False,
                thinking_budget=None,
                reasoning_effort=None,
                telemetry=repair_telemetry,
            )
            repair_telemetry["outcome"] = "ok" if repaired.finish_reason == "stop" else "non_stop_finish"
            return repaired
    except Exception as exc:  # noqa: BLE001 - syntax repair is best-effort
        logging.getLogger(__name__).warning(
            "json syntax repair failed: %s model=%s",
            type(exc).__name__,
            repair_model,
        )
        return None


class _CompletionClassifiedError(Exception):
    def __init__(self, outcome: CompletionOutcome, gateway_code: str, detail: str | None = None):
        super().__init__(outcome)
        self.outcome = outcome
        self.gateway_code = gateway_code
        self.detail = detail


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
    from app.infrastructure.ai.client import observe_transport
    from app.infrastructure.ai.thinking_policy import resolve_provider_thinking

    resolved_thinking = resolve_provider_thinking(
        model,
        effort=spec.thinking_effort,
        enable_thinking=spec.enable_thinking,
        thinking_budget=spec.thinking_budget,
        reasoning_effort=spec.reasoning_effort,
    )

    telemetry_ref: dict[str, Any] = {}
    raw_seen = ""
    started = perf_counter()
    try:
        with model_call_span(
            operation=spec.operation, model=model, agent_type=spec.agent_label,
            component_id=spec.component_id, component_version=spec.version,
            prompt_id=spec.prompt.id, model_source=model_source,
            definition_digest=spec.definition_digest,
            enable_thinking=resolved_thinking.enable_thinking,
            thinking_budget=resolved_thinking.thinking_budget,
            reasoning_effort=resolved_thinking.reasoning_effort,
            thinking_effort=resolved_thinking.effective_effort,
            input_payload=None if spec.component_id.startswith("behavior.") else messages,
        ) as telemetry, observe_transport(telemetry):
            telemetry_ref = telemetry
            completion = complete_json_chat(
                client=client,
                model=model,
                messages=messages,
                temperature=spec.temperature,
                max_tokens=spec.max_tokens,
                enable_thinking=resolved_thinking.enable_thinking,
                thinking_budget=resolved_thinking.thinking_budget,
                reasoning_effort=resolved_thinking.reasoning_effort,
                telemetry=telemetry,
            )
            raw_seen = completion.raw_wire or completion.raw
            has_user_images = isinstance(user, list) and any(
                isinstance(part, dict) and part.get("type") == "image_url" for part in user
            )
            raw = completion.raw
            try:
                def _validate(data):
                    if unit.id == "tutoring.turn" and not has_user_images and isinstance(data, dict):
                        data.pop("image_review", None)
                    return validate_output(unit, data)

                payload, outcome, abrupt_detail = validate_json_completion(
                    completion,
                    unit_id=unit.id,
                    validate_payload=_validate,
                )
            except _CompletionClassifiedError as error:
                repaired_ok = False
                if (
                    error.outcome == "json_parse_error"
                    and unit.id == "tutoring.turn"
                    and resolved_thinking.enable_thinking
                    and completion.finish_reason == "stop"
                    and "{" in completion.raw
                ):
                    repaired = _try_repair_json_syntax(
                        raw=completion.raw,
                        json_error=error.detail,
                        client=client,
                        runtime_settings=runtime_settings,
                    )
                    if repaired is not None:
                        try:
                            payload, outcome, _ = validate_json_completion(
                                repaired,
                                unit_id=unit.id,
                                validate_payload=_validate,
                            )
                            abrupt_detail = "json_syntax_repaired"
                            raw = repaired.raw
                            repaired_ok = True
                        except _CompletionClassifiedError:
                            repaired_ok = False
                if not repaired_ok:
                    telemetry["outcome"] = error.outcome
                    raise
            telemetry["outcome"] = outcome
            telemetry["abrupt_detail"] = abrupt_detail
            record_model_response(
                agent_type=spec.agent_label,
                model=model,
                content="[observation payload withheld]"
                if spec.component_id.startswith("behavior.")
                else raw,
                operation=spec.operation,
                component_id=spec.component_id,
                component_version=spec.version,
                provider_request_id=completion.provider_request_id,
                finish_reason=completion.finish_reason,
                stream_completed=completion.stream_completed,
                tokens_in=completion.tokens_in,
                tokens_out=completion.tokens_out,
                tokens_answer=completion.tokens_answer,
                tokens_reasoning=completion.tokens_reasoning,
                outcome=outcome,
                abrupt_detail=abrupt_detail,
                duration_ms=round((perf_counter() - started) * 1000),
                first_token_ms=telemetry.get("first_token_ms"),
                first_content_ms=telemetry.get("first_content_ms"),
            )
            _record_call_evidence(
                {
                    "component_id": spec.component_id,
                    "operation": spec.operation,
                    "model": model,
                    "provider_request_id": completion.provider_request_id,
                    "finish_reason": completion.finish_reason,
                    "stream_completed": completion.stream_completed,
                    "tokens_in": completion.tokens_in,
                    "tokens_out": completion.tokens_out,
                    "tokens_answer": completion.tokens_answer,
                    "tokens_reasoning": completion.tokens_reasoning,
                    "outcome": outcome,
                    "abrupt_detail": abrupt_detail,
                }
            )
    except _CompletionClassifiedError as error:
        rejection_detail: str | None = None
        if error.outcome == "json_parse_error" and not spec.component_id.startswith("behavior."):
            parts = [p for p in (error.detail, f"preview={_preview_raw(raw_seen)}" if raw_seen else None) if p]
            rejection_detail = " | ".join(parts) if parts else None
        telemetry_ref["outcome"] = error.outcome
        if rejection_detail is not None:
            telemetry_ref["abrupt_detail"] = rejection_detail
        record_model_rejection(
            agent_type=spec.agent_label,
            model=model,
            raw_content="[observation payload withheld]"
            if spec.component_id.startswith("behavior.")
            else raw_seen,
            operation=spec.operation,
            component_id=spec.component_id,
            component_version=spec.version,
            provider_request_id=telemetry_ref.get("provider_request_id"),
            finish_reason=telemetry_ref.get("finish_reason"),
            stream_completed=bool(telemetry_ref.get("stream_completed")),
            tokens_in=telemetry_ref.get("tokens_in"),
            tokens_out=telemetry_ref.get("tokens_out"),
            tokens_answer=telemetry_ref.get("tokens_answer"),
            tokens_reasoning=telemetry_ref.get("tokens_reasoning"),
            outcome=error.outcome,
            duration_ms=round((perf_counter() - started) * 1000),
            first_token_ms=telemetry_ref.get("first_token_ms"),
            first_content_ms=telemetry_ref.get("first_content_ms"),
        )
        _record_call_evidence(
            {
                "component_id": spec.component_id,
                "operation": spec.operation,
                "model": model,
                "provider_request_id": telemetry_ref.get("provider_request_id"),
                "finish_reason": telemetry_ref.get("finish_reason"),
                "stream_completed": bool(telemetry_ref.get("stream_completed")),
                "tokens_in": telemetry_ref.get("tokens_in"),
                "tokens_out": telemetry_ref.get("tokens_out"),
                "tokens_answer": telemetry_ref.get("tokens_answer"),
                "tokens_reasoning": telemetry_ref.get("tokens_reasoning"),
                "outcome": error.outcome,
                "abrupt_detail": rejection_detail,
            }
        )
        logging.getLogger(__name__).warning(
            "model completion rejected: outcome=%s finish_reason=%s stream_completed=%s request_id=%s component=%s detail=%s",
            error.outcome,
            telemetry_ref.get("finish_reason"),
            telemetry_ref.get("stream_completed"),
            telemetry_ref.get("provider_request_id"),
            spec.component_id,
            rejection_detail,
        )
        raise ModelGatewayError(error.gateway_code) from error
    except (ModelGatewayError, ModelTimeBudgetExceeded):
        raise
    except Exception as error:
        telemetry_ref["outcome"] = "api_error"
        if telemetry_ref.get("stream_completed") is None:
            telemetry_ref["stream_completed"] = False
        _record_call_evidence(
            {
                "component_id": spec.component_id,
                "operation": spec.operation,
                "model": model,
                "provider_request_id": telemetry_ref.get("provider_request_id"),
                "finish_reason": telemetry_ref.get("finish_reason"),
                "stream_completed": bool(telemetry_ref.get("stream_completed")),
                "tokens_in": telemetry_ref.get("tokens_in"),
                "tokens_out": telemetry_ref.get("tokens_out"),
                "tokens_answer": telemetry_ref.get("tokens_answer"),
                "tokens_reasoning": telemetry_ref.get("tokens_reasoning"),
                "outcome": "api_error",
                "abrupt_detail": None,
                "error_type": type(error).__name__,
            }
        )
        logging.getLogger(__name__).warning(
            "model transport failed: %s status=%s request_id=%s component=%s",
            type(error).__name__,
            getattr(error, "status_code", None),
            telemetry_ref.get("provider_request_id"),
            spec.component_id,
        )
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
