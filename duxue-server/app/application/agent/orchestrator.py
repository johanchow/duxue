"""EduAgentOrchestrator: Application-layer Process Manager for dual-role Education General Agent.

Supports Default General Mode (safe read-only base tools only) and progressive
Skill disclosure via `agent.load_skill`, emitting nested OTel/Langfuse spans.
"""

from __future__ import annotations

from contextlib import ExitStack
import threading
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Callable, Literal
from uuid import uuid4

from app.application.agent.gates import GateRunner
from app.application.agent.registry import (
    SkillRegistry,
    SkillSpec,
    ToolContext,
    ToolExecutor,
    ToolRegistry,
    ToolResult,
)
from app.application.agent.role_policy import RolePolicyDecision, evaluate_role_policy
from app.infrastructure.observability.telemetry import (
    edu_agent_span,
    set_observation_payload,
)


@dataclass
class AgentRunRecord:
    run_id: str
    owner_id: str
    owner_role: str
    thread_id: str | None
    status: Literal["running", "completed", "cancelled", "failed"] = "running"
    active_skill_id: str | None = None
    loaded_skills: list[str] = field(default_factory=list)
    planned_steps: list[str] = field(default_factory=list)
    events: list[dict[str, Any]] = field(default_factory=list)
    result: dict[str, Any] | None = None
    updated_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))


class AgentRunStore:
    """Thread-safe ephemeral run store for progress projection and cancellation."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._runs: dict[str, AgentRunRecord] = {}

    def create(self, *, owner_id: str, owner_role: str, thread_id: str | None) -> AgentRunRecord:
        record = AgentRunRecord(
            run_id=str(uuid4()),
            owner_id=owner_id,
            owner_role=owner_role,
            thread_id=thread_id,
        )
        with self._lock:
            self._runs[record.run_id] = record
        return record

    def get(self, run_id: str) -> AgentRunRecord | None:
        with self._lock:
            return self._runs.get(run_id)

    def push_event(self, run_id: str, event: dict[str, Any]) -> None:
        with self._lock:
            rec = self._runs.get(run_id)
            if rec is not None:
                rec.events.append(event)
                rec.updated_at = datetime.now(timezone.utc)

    def cancel(self, run_id: str, *, owner_id: str) -> AgentRunRecord | None:
        with self._lock:
            rec = self._runs.get(run_id)
            if rec is None or rec.owner_id != owner_id:
                return None
            if rec.status == "running":
                rec.status = "cancelled"
                rec.events.append({"event": "cancelled", "run_id": run_id})
                rec.updated_at = datetime.now(timezone.utc)
            return rec


@dataclass(frozen=True)
class OrchestratorStep:
    """Single step proposed by the planner/model callback."""

    action: Literal["load_skill", "call_tool", "respond"]
    skill_id: str | None = None
    tool_id: str | None = None
    tool_args: dict[str, Any] = field(default_factory=dict)
    content: str = ""
    interaction_kind: str = "text"
    artifact_id: str | None = None
    artifacts: tuple[dict[str, Any], ...] = ()


PlannerFn = Callable[
    [dict[str, Any]],
    OrchestratorStep,
]


@dataclass(frozen=True)
class AgentRunOutcome:
    run_id: str
    status: Literal["completed", "cancelled", "failed"]
    content: str
    interaction_kind: str
    active_skill_id: str | None
    registered_gates: frozenset[str]
    tool_results: tuple[ToolResult, ...]
    artifact_id: str | None = None
    loaded_skills: tuple[str, ...] = ()
    artifacts: tuple[dict[str, Any], ...] = ()


class EduAgentOrchestrator:
    def __init__(
        self,
        *,
        tool_registry: ToolRegistry,
        skill_registry: SkillRegistry,
        run_store: AgentRunStore | None = None,
        max_steps: int = 6,
        gates: GateRunner | None = None,
    ) -> None:
        self.tool_registry = tool_registry
        self.skill_registry = skill_registry
        self.executor = ToolExecutor(tool_registry)
        self.run_store = run_store or AgentRunStore()
        self.gates = gates or GateRunner()
        self.max_steps = max_steps

    def run(
        self,
        *,
        ctx: ToolContext,
        message: str,
        planner: PlannerFn,
        attachments: list[str] | None = None,
    ) -> AgentRunOutcome:
        policy: RolePolicyDecision = evaluate_role_policy(
            role=ctx.actor_role,
            context_ward_bound=bool(ctx.context_ward_id),
        )
        record = self.run_store.create(
            owner_id=ctx.actor_id,
            owner_role=policy.role,
            thread_id=ctx.thread_id,
        )
        active_tools: set[str] = set(policy.base_tools)
        registered_gates: set[str] = set(policy.mandatory_gates)
        active_skill: SkillSpec | None = None
        loaded_skills: list[str] = []
        tool_results: list[ToolResult] = []
        visible_skills = self.skill_registry.visible_catalog(policy)

        with edu_agent_span(
            "turn",
            "edu_agent_orchestrator",
            **{"agent.run_id": record.run_id, "agent.role": policy.role},
        ) as turn_span, ExitStack() as skill_scope:
            set_observation_payload(
                turn_span,
                input={"message_len": len(message), "attachment_count": len(attachments or [])},
            )
            self.run_store.push_event(
                record.run_id,
                {"event": "started", "run_id": record.run_id, "role": policy.role},
            )

            for step_index in range(self.max_steps):
                current = self.run_store.get(record.run_id)
                if current and current.status == "cancelled":
                    return AgentRunOutcome(
                        run_id=record.run_id,
                        status="cancelled",
                        content="",
                        interaction_kind="text",
                        active_skill_id=active_skill.id if active_skill else None,
                        registered_gates=frozenset(registered_gates),
                        tool_results=tuple(tool_results),
                        loaded_skills=tuple(loaded_skills),
                    )

                step = planner(
                    {
                        "step_index": step_index,
                        "message": message,
                        "attachments": attachments or [],
                        "role": policy.role,
                        "visible_skills": visible_skills,
                        "active_skill": active_skill.model_dump() if active_skill else None,
                        "loaded_skills": list(loaded_skills),
                        "active_tools": sorted(active_tools),
                        "tool_results": [
                            {"tool_id": r.tool_id, "status": r.status, "data": r.data, "error_code": r.error_code}
                            for r in tool_results
                        ],
                    }
                )

                if step.action == "load_skill" and step.skill_id:
                    skill = self.skill_registry.get(step.skill_id)
                    if (
                        skill is None
                        or skill.id not in policy.allowed_skills
                        or policy.role not in skill.allowed_roles
                    ):
                        tool_results.append(
                            ToolResult(
                                tool_id="agent.load_skill",
                                status="denied",
                                error_code="skill_not_permitted",
                            )
                        )
                        continue
                    skill_scope.close()
                    skill_span = skill_scope.enter_context(edu_agent_span(
                        "skill",
                        skill.id,
                        **{"agent.skill_id": skill.id, "agent.role": policy.role},
                    ))
                    active_skill = skill
                    record.active_skill_id = skill.id
                    if skill.id not in loaded_skills:
                        loaded_skills.append(skill.id)
                    record.loaded_skills = list(loaded_skills)
                    unlocked = set(skill.tools) & policy.all_permitted_tools
                    active_tools = set(policy.base_tools) | unlocked
                    registered_gates |= set(skill.required_gates)
                    set_observation_payload(
                        skill_span,
                        output={
                            "skill_id": skill.id,
                            "unlocked_tools": sorted(unlocked),
                            "required_gates": sorted(skill.required_gates),
                        },
                    )
                    tool_results.append(
                        ToolResult(
                            tool_id="agent.load_skill",
                            status="ok",
                            data={
                                "skill_id": skill.id,
                                "instructions": skill.instructions,
                                "unlocked_tools": sorted(unlocked),
                            },
                        )
                    )
                    self.run_store.push_event(
                        record.run_id,
                        {"event": "skill_loaded", "skill_id": skill.id},
                    )
                    continue

                spec = self.tool_registry.get_spec(step.tool_id) if step.action == "call_tool" else None
                phase = "respond" if step.action == "respond" else "write" if spec and spec.access == "command" and step.tool_id in active_tools else None
                if phase and not self.gates.allows(registered_gates, phase=phase, candidate=step):
                    record.status = "failed"
                    self.run_store.push_event(record.run_id, {"event": "failed", "reason": "gate_denied"})
                    return AgentRunOutcome(
                        record.run_id,
                        "failed",
                        "本轮核验未通过。",
                        "text",
                        active_skill.id if active_skill else None,
                        frozenset(registered_gates),
                        tuple(tool_results),
                        loaded_skills=tuple(loaded_skills),
                    )

                if step.action == "call_tool" and step.tool_id:
                    res = self.executor.execute(
                        tool_id=step.tool_id,
                        args=step.tool_args,
                        ctx=ctx,
                        policy=policy,
                        active_tools=frozenset(active_tools),
                    )
                    tool_results.append(res)
                    self.run_store.push_event(
                        record.run_id,
                        {"event": "tool_called", "tool_id": step.tool_id, "status": res.status},
                    )
                    if res.status == "tool_error":
                        record.status = "failed"
                        self.run_store.push_event(record.run_id, {"event": "failed", "reason": res.error_code})
                        return AgentRunOutcome(
                            run_id=record.run_id, status="failed", content="工具暂不可用，请稍后重试。",
                            interaction_kind="text", active_skill_id=active_skill.id if active_skill else None,
                            registered_gates=frozenset(registered_gates), tool_results=tuple(tool_results),
                            loaded_skills=tuple(loaded_skills),
                        )
                    continue

                if step.action == "respond":
                    record.status = "completed"
                    outcome = AgentRunOutcome(
                        run_id=record.run_id,
                        status="completed",
                        content=step.content,
                        interaction_kind=step.interaction_kind,
                        active_skill_id=active_skill.id if active_skill else None,
                        registered_gates=frozenset(registered_gates),
                        tool_results=tuple(tool_results),
                        artifact_id=step.artifact_id,
                        loaded_skills=tuple(loaded_skills),
                        artifacts=step.artifacts,
                    )
                    record.result = {
                        "content": outcome.content,
                        "interaction_kind": outcome.interaction_kind,
                        "active_skill_id": outcome.active_skill_id,
                        "loaded_skills": list(outcome.loaded_skills),
                        "artifact_id": outcome.artifact_id,
                        "artifacts": list(outcome.artifacts),
                    }
                    self.run_store.push_event(
                        record.run_id,
                        {"event": "completed", "run_id": record.run_id, "result": record.result},
                    )
                    set_observation_payload(
                        turn_span,
                        output={
                            "status": "completed",
                            "active_skill_id": outcome.active_skill_id,
                            "loaded_skills": list(outcome.loaded_skills),
                            "tool_count": len(tool_results),
                        },
                    )
                    return outcome

            record.status = "failed"
            self.run_store.push_event(
                record.run_id,
                {"event": "failed", "reason": "step_budget_exhausted"},
            )
            return AgentRunOutcome(
                run_id=record.run_id,
                status="failed",
                content="本次任务步骤超出上限，请缩小范围后重试。",
                interaction_kind="text",
                active_skill_id=active_skill.id if active_skill else None,
                registered_gates=frozenset(registered_gates),
                tool_results=tuple(tool_results),
                loaded_skills=tuple(loaded_skills),
            )
