from __future__ import annotations

from ..memory import MemoryContextRequest, SqlAlchemyMemoryFacade
from .contracts import ContextEnvelope, ContextSpec


class ContextBuilder:
    """Builds a minimal envelope through MemoryFacade, never direct table reads."""

    def __init__(self, memory: SqlAlchemyMemoryFacade):
        self.memory = memory

    def build(
        self,
        *,
        run_id: str,
        ward_id: str,
        actor_id: str,
        actor_role: str,
        agent_type: str,
        context_refs: list[str],
        context_spec: ContextSpec | None = None,
    ) -> ContextEnvelope:
        spec = context_spec or ContextSpec()
        bundle = self.memory.resolve_context(
            MemoryContextRequest(
                ward_id=ward_id,
                actor_id=actor_id,
                actor_role=actor_role,
                use_case=agent_type,
                memory_types=spec.memory_types,
                visibility_scope={"ward", "system"},
                item_budget=spec.item_budget,
                token_budget=spec.token_budget,
            )
        )
        return ContextEnvelope(
            run={
                "run_id": run_id,
                "agent_type": agent_type,
                "context_refs": context_refs,
            },
            actor={"ward_id": ward_id, "role": actor_role},
            objective={"agent_type": agent_type},
            session={},
            evidence_refs=bundle.evidence_refs,
            signals=bundle.active_signals,
            memory=bundle.episodic_memories,
            profile=bundle.profile_projection,
            policy={"version": spec.policy_version, "max_model_calls": spec.max_model_calls, "max_tool_calls": spec.max_tool_calls},
            tools=[{"name": name} for name in sorted(spec.tool_allow_list)],
            truncated=bundle.truncated,
        )
