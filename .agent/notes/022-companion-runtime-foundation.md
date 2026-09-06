# Companion Runtime Foundation

- `CompanionCoordinator` is a deterministic control layer, not a fourth Agent. It owns Ward authentication, thread version checks, route decisions, Run lifecycle and trace creation; it never invokes a model or reads memory tables directly.
- The foundation persists `ConversationThread`, `AgentRun`, `AgentCheckpoint` and `AgentTrace`. `AgentRun` is the authority for lifecycle/authorization; a future LangGraph PostgreSQL checkpointer owns graph state. `AgentCheckpoint` must only map a Run to a graph checkpoint/config and digest, never duplicate Prompt or working memory.
- `SqlAlchemyMemoryFacade.resolve_context` is the Agent-facing aggregated read boundary. It authorizes actor/visibility, filters episodic records to the five-day window, returns Active Signals only, removes raw cues, and applies deterministic item/token budgets.
- The empty-schema rebuild migration (`20260830_10`) calls `Base.metadata.create_all` with current metadata. The companion migration therefore treats tables already created during a fresh full upgrade as valid, while still creating them for databases that were already at revision `20260830_10`.
- The first `/companion/turn` response intentionally exposes only route/Run/redacted-context metadata. Domain workflows will later be introduced through `WorkflowAdapter`; they alone may stream Ward-facing content.
