"""Typed, Qwen-compatible text gateway for Companion workflows.

The gateway deliberately returns a small validated candidate rather than ORM
objects or free-form tool calls.  Workflows retain ownership of all writes and
fall back to deterministic guidance when the provider is unavailable.
"""

from __future__ import annotations

import json
from typing import Literal

from pydantic import BaseModel, Field, ValidationError

from app.bootstrap.settings import settings
from app.infrastructure.observability.telemetry import model_call_span, record_model_response


AgentName = Literal["planning", "tutoring", "reflection"]


class AgentTextCandidate(BaseModel):
    content: str = Field(min_length=1, max_length=1200)
    follow_up_question: str | None = Field(default=None, max_length=300)


class ModelGatewayError(RuntimeError):
    """A provider or candidate validation failure safe for deterministic fallback."""


class QwenAgentModelGateway:
    """OpenAI-compatible gateway, with model selection per Agent type."""

    def generate(self, *, agent_type: AgentName, envelope: dict, instruction: str) -> AgentTextCandidate:
        if not settings.agent_model_enabled:
            raise ModelGatewayError("model_provider_disabled")
        if not settings.dashscope_api_key:
            raise ModelGatewayError("model_provider_not_configured")
        from openai import OpenAI

        system = (
            "你是读学系统的受控学习助手。只返回一个 JSON 对象，字段为 content 和 "
            "follow_up_question；不得调用工具、不得给出解题最终答案、不得输出思维链，"
            "不得把上下文中的个人数据扩写或泄露。content 必须是面向孩子的简短中文。"
        )
        user = json.dumps({"instruction": instruction, "context": envelope}, ensure_ascii=False)
        model = settings.agent_model(agent_type)
        try:
            with model_call_span(operation="agent_text", model=model, agent_type=agent_type) as telemetry:
                response = OpenAI(
                    api_key=settings.dashscope_api_key,
                    base_url=settings.dashscope_base_url,
                    timeout=settings.agent_model_timeout_seconds,
                ).chat.completions.create(
                    model=model,
                    messages=[{"role": "system", "content": system}, {"role": "user", "content": user}],
                    temperature=0.2,
                    max_tokens=450,
                    response_format={"type": "json_object"},
                )
                usage = response.usage
                telemetry["provider_request_id"] = getattr(response, "id", None)
                telemetry["tokens_in"] = getattr(usage, "prompt_tokens", None)
                telemetry["tokens_out"] = getattr(usage, "completion_tokens", None)
                raw = (response.choices[0].message.content or "").strip()
                candidate = AgentTextCandidate.model_validate_json(raw)
                record_model_response(
                    agent_type=agent_type, model=model, content=candidate.content, operation="agent_text",
                )
                return candidate
        except (ValidationError, ValueError, KeyError) as error:
            raise ModelGatewayError("invalid_model_candidate") from error
        except Exception as error:
            raise ModelGatewayError("model_transport_error") from error
