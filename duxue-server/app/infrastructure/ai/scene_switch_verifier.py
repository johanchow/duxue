"""Independent model check for a proposed Companion scene handoff."""

from __future__ import annotations

from app.application.ports.companion import AgentType
from app.infrastructure.ai import components
from app.infrastructure.ai.errors import ModelGatewayError
from app.infrastructure.ai.utterance_window import user_content


class ModelSceneSwitchVerifier:
    def confirm(
        self, *, content: str, current_agent_type: AgentType,
        proposed_agent_type: AgentType, recent_utterances: list[dict],
        current_images: list[str | None],
    ) -> bool | None:
        user = user_content(
            {
                "content": content,
                "current_agent_type": current_agent_type,
                "proposed_agent_type": proposed_agent_type,
            },
            recent_utterances, current_images,
        )
        try:
            payload = components.invoke_json_component(
                spec=components.COMPONENTS.get("companion.scene-switch"), user=user,
            )
        except ModelGatewayError:
            return None
        if set(payload) != {"allow_switch"} or type(payload["allow_switch"]) is not bool:
            return None
        return payload["allow_switch"]
