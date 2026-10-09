from __future__ import annotations

import re

from app.application.ports.companion import IntentProposal, RouteDecision

_SAFETY = re.compile(
    r"自杀|自殘|自残|伤害自己|傷害自己|伤害他人|傷害他人", re.IGNORECASE
)
_BUSINESS_TARGETS = {"planning", "tutoring", "reflection"}
_PROPOSAL_LABELS = _BUSINESS_TARGETS | {"unclear"}


class IntentRouter:
    """Apply a validated intent proposal. Free text is not interpreted here."""

    @staticmethod
    def blocks_for_safety(content: str) -> bool:
        return _SAFETY.search(content or "") is not None

    def decide(
        self,
        *,
        content: str,
        route_hint: str | None,
        focus_run: object | None,
        proposal: IntentProposal | None = None,
        has_image: bool = False,
    ) -> RouteDecision:
        if self.blocks_for_safety(content):
            return RouteDecision(
                target="safety",
                mode="clarify",
                confidence=1,
                route_reason="safety_keyword",
            )
        if route_hint in _BUSINESS_TARGETS:
            return RouteDecision(
                target=route_hint,
                mode="start",
                confidence=1,
                route_reason="validated_route_hint",
            )

        intent = proposal.intent if proposal is not None else "unclear"
        if intent not in _PROPOSAL_LABELS:
            intent = "unclear"
        active_type = getattr(focus_run, "agent_type", None)
        active_id = getattr(focus_run, "id", None)
        if intent == "unclear":
            # The classifier sees the images too, yet may still return unclear.
            # An image with no explicit scene keeps its established default of
            # reaching Planning. An active tutoring or reflection focus is
            # left unchanged.
            if has_image and active_type in {None, "planning"}:
                return RouteDecision(
                    target="planning",
                    mode="continue" if active_type == "planning" else "start",
                    confidence=0.7,
                    active_session_id=active_id if active_type == "planning" else None,
                    route_reason="image_without_explicit_intent",
                )
            return RouteDecision(
                target="clarify",
                mode="clarify",
                confidence=0.4,
                route_reason="insufficient_route_confidence",
            )

        mode = (
            "continue"
            if active_type == intent
            else ("handoff" if focus_run else "start")
        )
        return RouteDecision(
            target=intent,
            mode=mode,
            confidence=0.95,
            active_session_id=active_id,
            route_reason="model_intent_proposal",
        )
