"""One structured model call that proposes a closed intent label."""

from __future__ import annotations

import json
from collections.abc import Callable

from app.application.ports.companion import IntentProposal
from app.infrastructure.ai import components
from app.infrastructure.ai.errors import ModelGatewayError
from app.infrastructure.ai.utterance_window import user_content

_LABELS = {"planning", "tutoring", "reflection", "unclear"}
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


def complete_intent(
    *, content: str, focus_agent_type: str | None, recent_utterances: list[dict] | None = None,
    current_images: list[str | None] | None = None,
) -> str:
    user = user_content(
        {"content": content, "focus_agent_type": focus_agent_type},
        recent_utterances, current_images,
    )
    payload = components.invoke_json_component(
        spec=components.COMPONENTS.get("companion.intent"), user=user,
    )
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
