"""进入 tutoring 场景后的一次无状态意图提议。失败不猜测。"""

from __future__ import annotations

import json

from app.bootstrap.settings import settings
from app.infrastructure.ai.model_gateway import ModelGatewayError
from app.infrastructure.ai.utterance_window import WINDOW_RULE
from app.infrastructure.observability.telemetry import model_call_span, record_model_response

TUTORING_INTENTS = frozenset({
    "problem_solving", "curiosity", "conversation", "safety", "pronunciation",
})
_SYSTEM = (
    "你只判断这句已经进入答疑的话要哪一种辅导。只返回一个 JSON 对象，字段只有 intent。"
    "intent 只能是 problem_solving、curiosity、conversation、safety、pronunciation 之一。"
    "problem_solving：孩子卡在一道作业题上，包括没看懂题目在问什么，或想知道这一步怎么做。出现题目、这道题、问的是什么，都是 problem_solving。"
    "curiosity：孩子想弄懂眼前材料里、并不属于这道作业题的内容，例如一个外语词或一句话的意思、为什么这样。材料里的词句释义是 curiosity。"
    "conversation：和学习、题目、眼前材料都无关的闲聊。"
    "safety：涉及伤害、危险或求助，不能当成普通题目继续教。"
    "pronunciation：孩子明确要听某个词或句子怎么读、怎么发音。只有要求朗读或发音时才选它。"
    + WINDOW_RULE +
    "不得调用工具，不得回答问题本身，不得输出其它字段。"
)


def parse_tutoring_intent(raw: str) -> str | None:
    text = (raw or "").strip()
    if text.startswith("```"):
        text = text.strip("`")
        if text.lower().startswith("json"):
            text = text[4:].strip()
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        return None
    intent = data.get("intent") if isinstance(data, dict) else None
    if intent not in TUTORING_INTENTS:
        return None
    return intent


def complete_tutoring_intent(*, content: str, recent_utterances: list[dict] | None = None) -> str:
    if not settings.agent_model_enabled:
        raise ModelGatewayError("model_provider_disabled")
    if not settings.dashscope_api_key:
        raise ModelGatewayError("model_provider_not_configured")
    from app.infrastructure.ai.client import dashscope_client

    model = settings.tutoring_model
    user = json.dumps(
        {"content": content, "recent_utterances": list(recent_utterances or [])},
        ensure_ascii=False,
    )
    try:
        with model_call_span(operation="tutoring_intent_proposal", model=model, agent_type="tutoring") as telemetry:
            response = dashscope_client(timeout=settings.agent_model_timeout_seconds).chat.completions.create(
                model=model,
                messages=[{"role": "system", "content": _SYSTEM}, {"role": "user", "content": user}],
                temperature=0,
                max_tokens=40,
                response_format={"type": "json_object"},
            )
            usage = response.usage
            telemetry["provider_request_id"] = getattr(response, "id", None)
            telemetry["tokens_in"] = getattr(usage, "prompt_tokens", None)
            telemetry["tokens_out"] = getattr(usage, "completion_tokens", None)
            raw = (response.choices[0].message.content or "").strip()
            record_model_response(
                agent_type="tutoring", model=model, content=raw, operation="tutoring_intent_proposal",
            )
            return raw
    except Exception as error:
        raise ModelGatewayError("model_transport_error") from error


class QwenTutoringIntentProposer:
    def propose(self, *, content: str, recent_utterances: list[dict] | None = None) -> str | None:
        try:
            return parse_tutoring_intent(complete_tutoring_intent(
                content=content, recent_utterances=recent_utterances,
            ))
        except ModelGatewayError:
            return None
