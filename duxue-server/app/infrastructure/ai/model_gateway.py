"""Typed, Qwen-compatible text gateway for Companion workflows.

The gateway deliberately returns a small validated candidate rather than ORM
objects or free-form tool calls.  Workflows retain ownership of all writes and
fall back to deterministic guidance when the provider is unavailable.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field, ValidationError

from app.agent_specs.catalog import load_catalog
from app.agent_specs.contexts import build_context
from app.infrastructure.ai import components
from app.infrastructure.ai.errors import ModelGatewayError

__all__ = ["AgentTextCandidate", "ModelGatewayError", "QwenAgentModelGateway"]

AgentName = Literal["planning"]


class AgentTextCandidate(BaseModel):
    content: str = Field(min_length=1, max_length=1200)
    follow_up_question: str | None = Field(default=None, max_length=300)


class QwenAgentModelGateway:
    """Planning text candidates through the registered component."""

    def generate(
        self, *, agent_type: AgentName, envelope: dict, instruction: str,
        recent_utterances: list[dict] | None = None, current_images: list[str | None] | None = None,
    ) -> AgentTextCandidate:
        """``instruction`` already carries the window text (``instruction_with_window``);
        the pictures in that window and this turn's pictures follow as vision parts."""
        user = build_context("planning.reply", envelope=envelope, instruction=instruction,
                             recent_utterances=recent_utterances, current_images=current_images)
        payload = components.invoke_agent_component(
            spec=load_catalog().component(agent_type, "agent_text"), user=user,
        ).unwrap()
        try:
            return AgentTextCandidate.model_validate(payload)
        except ValidationError as error:
            raise ModelGatewayError("invalid_model_candidate") from error
