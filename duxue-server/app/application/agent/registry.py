"""Unified ToolRegistry, SkillRegistry, and ToolExecutor middleware.

Lives in Application shared runtime infrastructure (not a business Domain).
"""

from __future__ import annotations

import json
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from contextvars import copy_context
from dataclasses import dataclass, field
from pathlib import Path
from threading import BoundedSemaphore
from typing import Any, Literal

from jsonschema import Draft202012Validator
from pydantic import BaseModel, ConfigDict, Field

from app.application.agent.role_policy import (
    AgentRole,
    RolePolicyDecision,
    verify_skill_role_ceiling,
    verify_tool_role_ceiling,
)
from app.infrastructure.ai.client import model_time_budget, remaining_model_time
from app.infrastructure.observability.telemetry import (
    edu_agent_span,
    set_observation_payload,
)

# Timed-out reads retain their slot until the handler actually exits. This
# bounds both running work and queued work when an external service stalls.
_tool_workers = ThreadPoolExecutor(max_workers=8, thread_name_prefix="edu-tool")
_tool_slots = BoundedSemaphore(8)


class _ToolCapacityExceeded(RuntimeError):
    pass


_SCHEMAS_DIR = Path(__file__).resolve().parent / "schemas"
_TOOL_SCHEMA = json.loads((_SCHEMAS_DIR / "tool.schema.json").read_text(encoding="utf-8"))
_SKILL_SCHEMA = json.loads((_SCHEMAS_DIR / "skill.schema.json").read_text(encoding="utf-8"))
_TOOL_VALIDATOR = Draft202012Validator(_TOOL_SCHEMA)
_SKILL_VALIDATOR = Draft202012Validator(_SKILL_SCHEMA)


class ToolSpec(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    kind: Literal["tool"] = "tool"
    owner_domain: Literal[
        "agent",
        "problem_solving",
        "tutoring",
        "artifact_workspace",
        "memory",
        "evaluation",
        "study",
        "infrastructure",
    ]
    display_name: str | None = None
    description: str
    access: Literal["read", "command"]
    allowed_roles: list[AgentRole]
    input_schema: dict[str, Any]
    output_schema: dict[str, Any]
    timeout_ms: int = Field(default=10_000, ge=100, le=120_000)
    handler_id: str
    static_result: dict[str, Any] | None = None


class SkillSpec(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    kind: Literal["skill"] = "skill"
    display_name: str
    description: str
    allowed_roles: list[AgentRole]
    tools: list[str]
    required_gates: list[str]
    output_artifact_type: Literal[
        "interactive_courseware", "grading_report", "lesson_pack", "creative_work"
    ] | None = None
    instructions: str


@dataclass(frozen=True)
class ToolContext:
    actor_id: str
    actor_role: AgentRole
    thread_id: str | None = None
    context_ward_id: str | None = None
    db: Any = None
    extras: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class ToolResult:
    tool_id: str
    status: Literal["ok", "denied", "invalid_input", "tool_error"]
    data: dict[str, Any] = field(default_factory=dict)
    error_code: str | None = None


ToolHandler = Callable[[dict[str, Any], ToolContext], dict[str, Any]]


class ToolRegistry:
    def __init__(self) -> None:
        self._specs: dict[str, ToolSpec] = {}
        self._handlers: dict[str, ToolHandler] = {}

    def register_spec(self, raw: dict[str, Any] | ToolSpec) -> ToolSpec:
        data = raw.model_dump(exclude_none=True) if isinstance(raw, ToolSpec) else raw
        errors = sorted(_TOOL_VALIDATOR.iter_errors(data), key=lambda e: list(e.path))
        if errors:
            raise ValueError(f"invalid tool schema for {data.get('id')}: {errors[0].message}")
        spec = ToolSpec.model_validate(data)
        verify_tool_role_ceiling(spec.id, set(spec.allowed_roles))
        self._specs[spec.id] = spec
        return spec

    def register_handler(self, handler_id: str, handler: ToolHandler) -> None:
        if not handler_id:
            raise ValueError("handler_id is required")
        self._handlers[handler_id] = handler

    def get_spec(self, tool_id: str) -> ToolSpec | None:
        return self._specs.get(tool_id)

    def get_handler(self, handler_id: str) -> ToolHandler | None:
        return self._handlers.get(handler_id)

    def list_specs(self) -> list[ToolSpec]:
        return list(self._specs.values())

    def validate_alignment(self) -> None:
        missing = [
            f"{spec.id} -> {spec.handler_id}"
            for spec in self._specs.values()
            if spec.handler_id != "tool.static_result" and spec.handler_id not in self._handlers
        ]
        if missing:
            raise ValueError(f"unregistered tool handlers: {', '.join(missing)}")


class SkillRegistry:
    def __init__(self) -> None:
        self._skills: dict[str, SkillSpec] = {}

    def register_skill(self, raw: dict[str, Any] | SkillSpec) -> SkillSpec:
        data = raw.model_dump(exclude_none=True) if isinstance(raw, SkillSpec) else raw
        errors = sorted(_SKILL_VALIDATOR.iter_errors(data), key=lambda e: list(e.path))
        if errors:
            raise ValueError(f"invalid skill schema for {data.get('id')}: {errors[0].message}")
        spec = SkillSpec.model_validate(data)
        verify_skill_role_ceiling(spec.id, set(spec.allowed_roles))
        self._skills[spec.id] = spec
        return spec

    def get(self, skill_id: str) -> SkillSpec | None:
        return self._skills.get(skill_id)

    def visible_catalog(self, policy: RolePolicyDecision) -> list[dict[str, str]]:
        return [
            {
                "id": skill.id,
                "display_name": skill.display_name,
                "description": skill.description,
            }
            for skill in self._skills.values()
            if skill.id in policy.allowed_skills and policy.role in skill.allowed_roles
        ]

    def validate_against_tools(self, tool_registry: ToolRegistry) -> None:
        missing = []
        for skill in self._skills.values():
            for tool_id in skill.tools:
                if tool_registry.get_spec(tool_id) is None:
                    missing.append(f"{skill.id} -> {tool_id}")
        if missing:
            raise ValueError(f"skills reference unknown tools: {', '.join(missing)}")


class ToolExecutor:
    """Unified execution middleware: RolePolicy -> Schema -> OTel/Langfuse -> Error translation."""

    def __init__(self, registry: ToolRegistry) -> None:
        self.registry = registry

    @staticmethod
    def _invoke(spec: ToolSpec, handler: ToolHandler, args: dict, ctx: ToolContext):
        def checked_call():
            remaining_model_time()
            try:
                return handler(args, ctx)
            finally:
                # Includes swallowed provider timeouts and late successful
                # results. Never let either authorize the next agent step.
                remaining_model_time()

        with model_time_budget(spec.timeout_ms / 1000):
            remaining = remaining_model_time()
            if spec.access == "command" or ctx.db is not None:
                # A Session and a domain command belong to their caller.
                # Detaching one on timeout would race rollback/commit and
                # could leave a write running after the response is returned.
                return checked_call()
            slots = _tool_slots
            if not slots.acquire(blocking=False):
                raise _ToolCapacityExceeded
            try:
                work = _tool_workers.submit(copy_context().run, checked_call)
            except Exception:
                slots.release()
                raise
            work.add_done_callback(lambda _: slots.release())
            try:
                return work.result(timeout=remaining)
            except TimeoutError:
                work.cancel()
                raise

    def execute(
        self,
        *,
        tool_id: str,
        args: dict[str, Any] | None,
        ctx: ToolContext,
        policy: RolePolicyDecision,
        active_tools: frozenset[str],
    ) -> ToolResult:
        safe_args = args if isinstance(args, dict) else {}
        with edu_agent_span(
            "tool",
            tool_id,
            **{"agent.tool_id": tool_id, "agent.role": ctx.actor_role},
        ) as span:
            set_observation_payload(span, input={"keys": sorted(safe_args.keys())})
            spec = self.registry.get_spec(tool_id)
            if spec is None or tool_id not in active_tools or tool_id not in policy.all_permitted_tools:
                span.set_attribute("agent.status", "denied")
                return ToolResult(tool_id=tool_id, status="denied", error_code="tool_not_permitted")
            if ctx.actor_role not in spec.allowed_roles:
                span.set_attribute("agent.status", "denied")
                return ToolResult(tool_id=tool_id, status="denied", error_code="role_not_permitted")

            validator = Draft202012Validator(spec.input_schema)
            input_errors = sorted(validator.iter_errors(safe_args), key=lambda e: list(e.path))
            if input_errors:
                span.set_attribute("agent.status", "invalid_input")
                return ToolResult(
                    tool_id=tool_id,
                    status="invalid_input",
                    error_code="invalid_tool_input",
                )

            if spec.handler_id == "tool.static_result" and spec.access == "read":
                data = dict(spec.static_result or {})
                span.set_attribute("agent.status", "ok")
                set_observation_payload(span, output={"status": "ok"})
                return ToolResult(tool_id=tool_id, status="ok", data=data)

            handler = self.registry.get_handler(spec.handler_id)
            if handler is None:
                span.set_attribute("agent.status", "tool_error")
                return ToolResult(tool_id=tool_id, status="tool_error", error_code="handler_missing")
            try:
                output = self._invoke(spec, handler, safe_args, ctx)
            except TimeoutError:
                span.set_attribute("agent.status", "tool_error")
                span.set_attribute("agent.error_code", "tool_timeout")
                return ToolResult(tool_id=tool_id, status="tool_error", error_code="tool_timeout")
            except _ToolCapacityExceeded:
                span.set_attribute("agent.status", "tool_error")
                span.set_attribute("agent.error_code", "tool_capacity_exhausted")
                return ToolResult(tool_id=tool_id, status="tool_error", error_code="tool_capacity_exhausted")
            except NotImplementedError:
                span.set_attribute("agent.status", "tool_error")
                return ToolResult(tool_id=tool_id, status="tool_error", error_code="tool_unavailable")
            except PermissionError:
                span.set_attribute("agent.status", "denied")
                return ToolResult(tool_id=tool_id, status="denied", error_code="access_denied")
            except Exception:  # noqa: BLE001 - tool failures must use the public error vocabulary
                span.set_attribute("agent.status", "tool_error")
                return ToolResult(tool_id=tool_id, status="tool_error", error_code="execution_failed")

            if not isinstance(output, dict) or not Draft202012Validator(spec.output_schema).is_valid(output):
                span.set_attribute("agent.status", "tool_error")
                return ToolResult(tool_id=tool_id, status="tool_error", error_code="invalid_tool_output")
            span.set_attribute("agent.status", "ok")
            set_observation_payload(span, output={"status": "ok", "keys": sorted(output.keys())})
            return ToolResult(tool_id=tool_id, status="ok", data=output)
