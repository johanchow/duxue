"""Code-owned debug adapters and bounded input contracts, never configurable handlers."""

from datetime import date
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class HistoryRow(BaseModel):
    model_config = ConfigDict(extra="forbid")
    author: Literal["ward", "companion"]
    text: str = Field(max_length=2000)


class DebugContext(BaseModel):
    model_config = ConfigDict(extra="forbid")
    review_date: date | None = None
    review_feeling: str = Field(default="", max_length=40)
    review_reflection: str = Field(default="", max_length=4000)
    history: list[HistoryRow] = Field(default_factory=list, max_length=20)
    task_title: str = Field(default="", max_length=300)
    problem_status: Literal["open", "submitted"] = "open"
    substantive_attempts: int = Field(default=0, ge=0, le=100)
    hints_given: int = Field(default=0, ge=0, le=100)
    active_subgoal: str = Field(default="", max_length=1000)
    evidence_summary: str = Field(default="", max_length=2000)


class DebugInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    content: str = Field(min_length=1, max_length=4000)
    problem: str = Field(default="", max_length=2000)
    target_kind: Literal["agent", "workflow"] | None = None
    target_id: str | None = Field(default=None, max_length=120)
    component_id: str | None = Field(default=None, max_length=120)
    context: DebugContext = Field(default_factory=DebugContext)


WORKFLOWS = {"tutoring", "reflection", "task-intake", "review-aspects", "sprint-intake"}
CODE_AGENTS = {
    "tutoring.session-turn": "tutoring",
    "reflection.session-turn": "reflection",
}


from app.agent_specs.observation_contracts import WORKFLOWS as OBSERVATION_WORKFLOWS, CODE_AGENTS as OBSERVATION_CODE_AGENTS
WORKFLOWS.update(OBSERVATION_WORKFLOWS)
CODE_AGENTS.update({identifier:identifier.replace('.', '-') for identifier in OBSERVATION_CODE_AGENTS})


def debug_capabilities():
    return {
        "workflows": sorted(WORKFLOWS),
        "code_agents": CODE_AGENTS,
        "context_schema": DebugContext.model_json_schema(),
        "limitations": {
            "eval-grading": "通过离线CLI运行完整评测；可单独调试评测裁判组件",
            "companion": "尚未接入协调器隔离调试",
            "planning": "尚未接入计划检查点隔离调试",
            "tutoring-vet": "内部审核子流程，请在Tutoring执行记录中查看",
            "tutoring-retry": "内部重试子流程，请在Tutoring执行记录中查看",
        },
    }


def resolve_target(data: DebugInput, catalog):
    kind, target, component = data.target_kind, data.target_id, data.component_id
    # Existing API callers may select an explicit model; the resolved owner is always recorded.
    if kind is None:
        if component in {None, "tutoring-pipeline"}:
            kind, target, component = "workflow", "tutoring", None
        else:
            kind, target = "agent", catalog.component(component)[0].id
    if kind == "workflow":
        if target not in WORKFLOWS or (target in OBSERVATION_WORKFLOWS and target not in catalog.workflow_catalog.specs) or component not in {None, "tutoring-pipeline"}:
            raise ValueError(
                "workflow has no standalone debug adapter or unexpected model override"
            )
    else:
        definition = catalog.units.get(target)
        if definition:
            component = component or definition.models[0].component_id
            if component not in {m.component_id for m in definition.models}:
                raise ValueError("model does not belong to the selected Agent")
        elif target not in CODE_AGENTS or target not in catalog.code_agents or component is not None:
            raise ValueError("component has no independent debug adapter")
    return {"kind": kind, "id": target, "component_id": component}
