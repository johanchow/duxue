"""One structured model call that proposes a closed intent label."""

from __future__ import annotations

import json
from collections.abc import Callable
from dataclasses import replace

from app.agent_specs.catalog import load_catalog
from app.agent_specs.contexts import build_context
from app.application.ports.companion import IntentProposal
from app.infrastructure.ai import components
from app.infrastructure.ai.errors import ModelGatewayError
from app.infrastructure.ai.thinking_policy import normalize_thinking_effort

_LABELS = {"planning", "tutoring", "reflection", "unclear"}
_VISION_INTENT_PREFIXES = ("qwen3.", "qwen-vl", "qwen2.5-vl", "deepseek-v4")


def _supports_vision_model(model_name: str | None) -> bool:
    name = (model_name or "").strip().lower()
    return bool(name) and (
        "vl" in name or any(name.startswith(prefix) for prefix in _VISION_INTENT_PREFIXES)
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
    if not isinstance(intent, str) or intent not in _LABELS:
        return IntentProposal(intent="unclear")
    policy = data.get("teaching_policy")
    if policy is not None and policy not in ("homework", "pronunciation", "standard"):
        return IntentProposal(intent="unclear")
    history_image_ref = "none" if data.get("history_image_ref") == "none" else "needed"
    thinking_effort = normalize_thinking_effort(
        data.get("thinking_effort"),
        legacy_thinking=data.get("thinking"),
        default="medium",
    )
    return IntentProposal(
        intent=intent,  # type: ignore[arg-type]
        history_image_ref=history_image_ref,
        teaching_policy=policy,
        creative_work=data.get("creative_work") is True and policy == "standard" and intent == "tutoring",
        thinking_effort=thinking_effort,
    )


def complete_intent(
    *, content: str, focus_agent_type: str | None, recent_utterances: list[dict] | None = None,
    current_images: list[str | None] | None = None, spec=None, settings_obj=None,
) -> str:
    user = build_context(
        "companion.intent", content=content, focus_agent_type=focus_agent_type,
        recent_utterances=recent_utterances, current_images=current_images,
    )
    resolved_spec = spec or load_catalog().component("companion", "intent_route")
    if (
        current_images
        and not getattr(resolved_spec, "accepts_images", False)
        and _supports_vision_model(getattr(resolved_spec, "model", None))
    ):
        resolved_spec = replace(resolved_spec, accepts_images=True)
    payload = components.invoke_agent_component(
        spec=resolved_spec, user=user, settings_obj=settings_obj,
    ).unwrap()
    return json.dumps(payload, ensure_ascii=False)


class ModelIntentClassifier:
    def __init__(self, complete: Callable[..., str] | None = None):
        self._complete = complete or complete_intent

    def propose(
        self, *, content: str, focus_agent_type: str | None, recent_utterances: list[dict] | None = None,
        current_images: list[str | None] | None = None,
    ) -> IntentProposal:
        try:
            return parse_intent_payload(self._complete(
                content=content, focus_agent_type=focus_agent_type, recent_utterances=recent_utterances,
                current_images=current_images,
            ))
        except ModelGatewayError:
            return IntentProposal(intent="unclear")
