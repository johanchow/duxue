from __future__ import annotations

from ..memory import MemoryContextRequest, SqlAlchemyMemoryFacade
from .contracts import ContextEnvelope


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
    ) -> ContextEnvelope:
        bundle = self.memory.resolve_context(
            MemoryContextRequest(
                ward_id=ward_id,
                actor_id=actor_id,
                actor_role=actor_role,
                use_case=agent_type,
                memory_types={"episodic", "signal", "profile"},
                visibility_scope={"ward", "system"},
                item_budget=12,
                token_budget=900,
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
            truncated=bundle.truncated,
        )
