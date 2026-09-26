"""One structured model call that proposes a closed intent label."""

from __future__ import annotations

import json
from collections.abc import Callable

from app.application.ports.companion import IntentProposal
from app.bootstrap.settings import settings
from app.infrastructure.ai.model_gateway import ModelGatewayError
from app.infrastructure.observability.telemetry import model_call_span

_LABELS = {"planning", "tutoring", "reflection", "unclear"}
_SYSTEM = (
    "你只判断孩子这句话要进入哪个学习场景。只返回一个 JSON 对象，字段只有 intent。"
    "intent 只能是 planning、tutoring、reflection、unclear 之一。"
    "planning 表示安排或修改学习任务；tutoring 表示提问、求解或想弄明白一个知识；"
    "reflection 表示复盘今天的学习；unclear 表示同时要做多件事，或听不出要哪一件。"
    "如果这句话是在延续当前 focus 场景，就再次返回该场景名。"
    "不得调用工具，不得回答问题本身，不得输出其它字段。"
)


def parse_intent_payload(raw: str) -> IntentProposal:
    text = (raw or "").strip()
    if text.startswith("```"):
        text = text.strip("`")
        if text.lower().startswith("json"):
            text = text[4:].strip()
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        return IntentProposal(intent="unclear")
    intent = data.get("intent") if isinstance(data, dict) else None
    if intent not in _LABELS:
        return IntentProposal(intent="unclear")
    return IntentProposal(intent=intent)  # type: ignore[arg-type]


def complete_intent(*, content: str, focus_agent_type: str | None) -> str:
    if not settings.agent_model_enabled:
        raise ModelGatewayError("model_provider_disabled")
    if not settings.dashscope_api_key:
        raise ModelGatewayError("model_provider_not_configured")
    from app.infrastructure.ai.client import dashscope_client

    model = settings.planning_model
    user = json.dumps(
        {"content": content, "focus_agent_type": focus_agent_type},
        ensure_ascii=False,
    )
    try:
        with model_call_span(operation="intent_proposal", model=model, agent_type=None) as telemetry:
            response = dashscope_client(timeout=settings.agent_model_timeout_seconds).chat.completions.create(
                model=model,
                messages=[{"role": "system", "content": _SYSTEM}, {"role": "user", "content": user}],
                temperature=0,
                max_tokens=60,
                response_format={"type": "json_object"},
            )
            usage = response.usage
            telemetry["provider_request_id"] = getattr(response, "id", None)
            telemetry["tokens_in"] = getattr(usage, "prompt_tokens", None)
            telemetry["tokens_out"] = getattr(usage, "completion_tokens", None)
            return (response.choices[0].message.content or "").strip()
    except Exception as error:
        raise ModelGatewayError("model_transport_error") from error


class ModelIntentClassifier:
    def __init__(self, complete: Callable[..., str] | None = None):
        self._complete = complete or complete_intent

    def propose(self, *, content: str, focus_agent_type: str | None) -> IntentProposal:
        try:
            return parse_intent_payload(self._complete(content=content, focus_agent_type=focus_agent_type))
        except ModelGatewayError:
            return IntentProposal(intent="unclear")
