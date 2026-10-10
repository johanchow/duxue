"""Typed, Qwen-compatible text gateway for Companion workflows.

The gateway deliberately returns a small validated candidate rather than ORM
objects or free-form tool calls.  Workflows retain ownership of all writes and
fall back to deterministic guidance when the provider is unavailable.
"""

from __future__ import annotations

import json
from typing import Literal

from pydantic import BaseModel, Field, ValidationError

from app.infrastructure.ai import components
from app.infrastructure.ai.errors import ModelGatewayError
from app.infrastructure.ai.utterance_window import image_parts

__all__ = ["AgentTextCandidate", "ModelGatewayError", "QwenAgentModelGateway"]

AgentName = Literal["planning", "reflection"]
_COMPONENT_BY_AGENT = {"planning": "planning.reply", "reflection": "reflection.advice"}


class AgentTextCandidate(BaseModel):
    content: str = Field(min_length=1, max_length=1200)
    follow_up_question: str | None = Field(default=None, max_length=300)


class QwenAgentModelGateway:
    """Planning / reflection text candidates through the registered components."""

    def generate(
        self, *, agent_type: AgentName, envelope: dict, instruction: str,
        recent_utterances: list[dict] | None = None, current_images: list[str | None] | None = None,
    ) -> AgentTextCandidate:
        """``instruction`` already carries the window text (``instruction_with_window``);
        the pictures in that window and this turn's pictures follow as vision parts."""
        user = [
            {"type": "text", "text": json.dumps({"instruction": instruction, "context": envelope}, ensure_ascii=False)},
            *image_parts(list(recent_utterances or []), list(current_images or [])),
        ]
        payload = components.invoke_json_component(
            spec=components.COMPONENTS.get(_COMPONENT_BY_AGENT[agent_type]), user=user,
        )
        try:
            return AgentTextCandidate.model_validate(payload)
        except ValidationError as error:
            raise ModelGatewayError("invalid_model_candidate") from error
