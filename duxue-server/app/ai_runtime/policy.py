"""Versioned deterministic guardrails for target workflows.

The first production policy intentionally has no model or external tools.  A
future gateway may propose candidates, but every candidate still passes these
same bounded checks before a Context use case can persist anything.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any


_DIRECT_ANSWER = re.compile(r"(直接.*答案|告诉我答案|选\s*[ABCD]|代写|写一篇作文)", re.I)


@dataclass(frozen=True)
class PolicyDecision:
    accepted: bool
    code: str | None = None
    safe_response: str | None = None


class PolicyRegistry:
    """Small explicit policy registry; callers persist its version in traces."""

    version = "v1"

    def context_spec(self, agent_type: str):
        from .contracts import ContextSpec

        # One typed text candidate is permitted per turn.  Tools remain denied;
        # the workflow validates the candidate and owns all domain writes.
        return ContextSpec(policy_version=self.version, max_model_calls=1)

    def validate_tutoring_input(self, content: str) -> PolicyDecision:
        if _DIRECT_ANSWER.search(content):
            return PolicyDecision(
                accepted=False,
                code="direct_answer_request",
                safe_response="我会陪你一步步想，不直接给答案。先说说题目已知什么、要求什么？",
            )
        return PolicyDecision(accepted=True)

    def validate_candidate(self, candidate: dict[str, Any], *, allowed_tools: set[str]) -> PolicyDecision:
        tool = candidate.get("tool")
        if tool is not None and tool not in allowed_tools:
            return PolicyDecision(False, "unregistered_tool")
        if candidate.get("raw_chain_of_thought"):
            return PolicyDecision(False, "chain_of_thought_not_storable")
        return PolicyDecision(True)
