"""Independent model check for a proposed Companion scene handoff."""

from __future__ import annotations

from app.agent_specs.catalog import load_catalog
from app.agent_specs.contexts import build_context
from app.agent_specs.verdicts import normalize_judge
from app.application.ports.companion import AgentType
from app.infrastructure.ai import components
from app.infrastructure.ai.errors import ModelGatewayError


class ModelSceneSwitchVerifier:
    def confirm(
        self, *, content: str, current_agent_type: AgentType,
        proposed_agent_type: AgentType, recent_utterances: list[dict],
        current_images: list[str | None],
    ) -> bool | None:
        user = build_context(
            "companion.scene-switch", content=content, current_agent_type=current_agent_type,
            proposed_agent_type=proposed_agent_type, recent_utterances=recent_utterances,
            current_images=current_images,
        )
        try:
            payload = components.invoke_json_component(
                spec=load_catalog().component("companion", "switch_confirm"), user=user,
            )
        except ModelGatewayError:
            return None
        verdict = normalize_judge("companion.scene-switch", payload)
        return None if verdict.verdict == "unknown" else verdict.verdict == "allow"
