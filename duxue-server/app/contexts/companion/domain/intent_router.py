from __future__ import annotations

import re

from app.application.ports.companion import RouteDecision

_SAFETY = re.compile(
    r"自杀|自殘|自残|伤害自己|傷害自己|伤害他人|傷害他人", re.IGNORECASE
)
_INTENTS: dict[str, re.Pattern[str]] = {
    "planning": re.compile(
        r"计划|計畫|安排|排(?:一下|一[下下])?|明天.*(?:学|複習|复习)|待办|待辦",
        re.IGNORECASE,
    ),
    "tutoring": re.compile(
        r"不会|不會|这题|這題|题目|題目|讲讲|講講|怎么做|怎麼做|看不懂", re.IGNORECASE
    ),
    "reflection": re.compile(
        r"复盘|複盤|回顾|回顧|总结今天|總結今天|反思", re.IGNORECASE
    ),
}


class IntentRouter:
    """Rules-only router. It deliberately contains no model or tool calls."""

    def decide(
        self,
        *,
        content: str,
        route_hint: str | None,
        focus_run: object | None,
    ) -> RouteDecision:
        if _SAFETY.search(content):
            return RouteDecision(
                target="safety",
                mode="clarify",
                confidence=1,
                route_reason="safety_keyword",
            )
        if route_hint:
            return RouteDecision(
                target=route_hint,
                mode="start",
                confidence=1,
                route_reason="validated_route_hint",
            )

        matches = [
            name for name, pattern in _INTENTS.items() if pattern.search(content)
        ]
        if len(matches) > 1:
            return RouteDecision(
                target="clarify",
                mode="clarify",
                confidence=1,
                route_reason="multiple_explicit_intents",
            )
        if len(matches) == 1:
            target = matches[0]
            active_type = getattr(focus_run, "agent_type", None)
            active_id = getattr(focus_run, "id", None)
            mode = (
                "continue"
                if active_type == target
                else ("handoff" if focus_run else "start")
            )
            return RouteDecision(
                target=target,
                mode=mode,
                confidence=0.95,
                active_session_id=active_id,
                route_reason="explicit_intent",
            )

        if focus_run is not None:
            return RouteDecision(
                target=focus_run.agent_type,
                mode="continue",
                confidence=0.7,
                active_session_id=focus_run.id,
                route_reason="focus_run_normal_continuation",
            )
        return RouteDecision(
            target="clarify",
            mode="clarify",
            confidence=0.4,
            route_reason="insufficient_route_confidence",
        )
