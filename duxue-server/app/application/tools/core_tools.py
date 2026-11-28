"""Initial 5 Skills & 11 Tools composition root and core read-only ToolHandlers."""

from __future__ import annotations

from typing import Any

from app.agent_specs.web_search import CONTRACT as SEARCH_CONTRACT
from app.application.agent.role_policy import ADULT_ROLES
from app.application.agent.registry import SkillRegistry, ToolContext, ToolRegistry
from app.infrastructure.persistence.models import (
    ConversationThread,
    GuardianWard,
    LearningEvent,
    Sprint,
)


def handle_study_get_focus_state(args: dict[str, Any], ctx: ToolContext) -> dict[str, Any]:
    if ctx.db is None:
        return {"in_sprint": False, "sprint_id": None, "topic": None}
    sprint = (
        ctx.db.query(Sprint)
        .filter_by(ward_id=ctx.actor_id, status="active")
        .first()
    )
    if sprint is None:
        return {"in_sprint": False, "sprint_id": None, "topic": None}
    return {"in_sprint": True, "sprint_id": sprint.id, "topic": sprint.topic}


def handle_ward_context_read_summary(args: dict[str, Any], ctx: ToolContext) -> dict[str, Any]:
    """Strictly read-only summary for an explicitly bound Ward. Never writes to Memory."""
    ward_id = ctx.context_ward_id
    if args.get("ward_id", ward_id) != ward_id:
        raise PermissionError("ward differs from conversation context")
    if ctx.actor_role not in ADULT_ROLES or not (ward_id and ctx.db is not None and ctx.thread_id):
        raise PermissionError("bound ward_id is required")
    bound = ctx.db.query(ConversationThread.id).filter_by(
        id=ctx.thread_id, guardian_id=ctx.actor_id, context_ward_id=ward_id, deleted=False,
    ).first()
    if bound is None:
        raise PermissionError("conversation context no longer available")
    binding = (
        ctx.db.query(GuardianWard)
        .filter_by(guardian_id=ctx.actor_id, ward_id=str(ward_id))
        .first()
    )
    if binding is None:
        raise PermissionError("guardian is not bound to this ward")

    limit = max(1, min(int(args.get("limit", 5)), 20))
    events = (
        ctx.db.query(LearningEvent)
        .filter_by(ward_id=str(ward_id), visibility="guardian")
        .order_by(LearningEvent.occurred_at.desc())
        .limit(limit)
        .all()
    )
    return {
        "ward_id": str(ward_id),
        "read_only": True,
        "recent_learning_events": [
            {
                "event_type": e.event_type,
                "source_type": e.source_type,
                "occurred_at": e.occurred_at.isoformat() if e.occurred_at else None,
                "summary": (e.payload or {}).get("title") or (e.payload or {}).get("summary") or "",
            }
            for e in events
        ],
    }


def handle_math_compute(args: dict[str, Any], ctx: ToolContext) -> dict[str, Any]:
    engine = ctx.extras.get("math_engine")
    if engine is None:
        raise NotImplementedError("math engine unavailable")
    return engine.execute(args)


def handle_web_search(args: dict[str, Any], ctx: ToolContext) -> dict[str, Any]:
    searcher = ctx.extras.get("web_search")
    if searcher is None:
        from app.infrastructure.ai.learning_search import LearningSearch

        searcher = LearningSearch()
        ctx.extras["web_search"] = searcher
    return searcher.search(args)


def _unimplemented_placeholder(name: str):
    def _handler(args: dict[str, Any], ctx: ToolContext) -> dict[str, Any]:
        delegate = ctx.extras.get(name)
        if callable(delegate):
            return delegate(args, ctx)
        raise NotImplementedError(name)

    return _handler


_INITIAL_TOOLS: list[dict[str, Any]] = [
    {
        "id": "agent.load_skill",
        "kind": "tool",
        "owner_domain": "agent",
        "description": "按需加载指定教育 Skill 的详细 SOP 指令并解锁其专属工具。",
        "access": "read",
        "allowed_roles": ["teacher", "coach", "guardian", "ward"],
        "input_schema": {
            "type": "object",
            "required": ["skill_id"],
            "properties": {"skill_id": {"type": "string"}},
            "additionalProperties": False,
        },
        "output_schema": {"type": "object"},
        "timeout_ms": 1000,
        "handler_id": "agent.load_skill",
    },
    {
        "id": "problem_solving.solve_and_verify",
        "kind": "tool",
        "owner_domain": "problem_solving",
        "description": "调用多路求解与确定性核验内核，用于单题求解、批改核验与出题自验。",
        "access": "read",
        "allowed_roles": ["teacher", "coach", "guardian"],
        "input_schema": {"type": "object", "properties": {"prompt": {"type": "string"}}},
        "output_schema": {"type": "object"},
        "timeout_ms": 60000,
        "handler_id": "problem_solving.solve_and_verify",
    },
    {
        "id": "math.compute",
        "kind": "tool",
        "owner_domain": "problem_solving",
        "description": "执行确定性数学/理化符号计算与等价性核验。",
        "access": "read",
        "allowed_roles": ["teacher", "coach", "guardian", "ward"],
        "input_schema": {"type": "object", "required": ["op"], "properties": {"op": {"type": "string"}}},
        "output_schema": {"type": "object"},
        "timeout_ms": 10000,
        "handler_id": "math.compute",
    },
    {
        "id": "tutoring.run_homework_turn",
        "kind": "tool",
        "owner_domain": "tutoring",
        "description": "受控调用 Ward 作业启发答疑状态机与答案保护出口检查。",
        "access": "command",
        "allowed_roles": ["teacher", "coach", "guardian", "ward"],
        "input_schema": {"type": "object", "properties": {"content": {"type": "string"}}},
        "output_schema": {"type": "object"},
        "timeout_ms": 45000,
        "handler_id": "tutoring.run_homework_turn",
    },
    {
        "id": "artifact.create_or_revise",
        "kind": "tool",
        "owner_domain": "artifact_workspace",
        "description": "创建或局部修订多形态可版本化教育产物（EduArtifact）。",
        "access": "command",
        "allowed_roles": ["teacher", "coach", "guardian", "ward"],
        "input_schema": {"type": "object", "properties": {"artifact_type": {"type": "string"}}},
        "output_schema": {"type": "object"},
        "timeout_ms": 30000,
        "handler_id": "artifact.create_or_revise",
    },
    {
        "id": "artifact.get_view",
        "kind": "tool",
        "owner_domain": "artifact_workspace",
        "description": "只读查询当前产物的版本块视图。",
        "access": "read",
        "allowed_roles": ["teacher", "coach", "guardian", "ward"],
        "input_schema": {"type": "object", "required": ["artifact_id"], "properties": {"artifact_id": {"type": "string"}}},
        "output_schema": {"type": "object"},
        "timeout_ms": 5000,
        "handler_id": "artifact.get_view",
    },
    {
        "id": "ward_context.read_summary",
        "kind": "tool",
        "owner_domain": "memory",
        "description": "显式受权只读已绑定学生近期卡点与报告摘要（零写入）。",
        "access": "read",
        "allowed_roles": ["teacher", "coach", "guardian"],
        "input_schema": {
            "type": "object",
            "properties": {"ward_id": {"type": "string"}, "limit": {"type": "integer"}},
            "additionalProperties": False,
        },
        "output_schema": {"type": "object"},
        "timeout_ms": 3000,
        "handler_id": "ward_context.read_summary",
    },
    {
        "id": "study.get_focus_state",
        "kind": "tool",
        "owner_domain": "study",
        "description": "只读查询 Ward 当前是否存在活跃 Sprint 专注挑战。",
        "access": "read",
        "allowed_roles": ["ward"],
        "input_schema": {"type": "object", "additionalProperties": False},
        "output_schema": {"type": "object"},
        "timeout_ms": 2000,
        "handler_id": "study.get_focus_state",
    },
    {
        "id": "image.inspect_crop",
        "kind": "tool",
        "owner_domain": "infrastructure",
        "description": "对授权题目图片进行局部裁剪放大核查。",
        "access": "read",
        "allowed_roles": ["teacher", "coach", "guardian", "ward"],
        "input_schema": {"type": "object"},
        "output_schema": {"type": "object"},
        "timeout_ms": 10000,
        "handler_id": "image.inspect_crop",
    },
    {
        "id": "web.search",
        "kind": "tool",
        "owner_domain": "infrastructure",
        "description": "只读联网检索学习资料与真实照片。",
        "access": "read",
        "allowed_roles": ["teacher", "coach", "guardian", "ward"],
        "input_schema": SEARCH_CONTRACT["input_schema"],
        "output_schema": {"type": "object"},
        "timeout_ms": 8000,
        "handler_id": "web.search",
    },
    {
        "id": "media.generate_image",
        "kind": "tool",
        "owner_domain": "infrastructure",
        "description": "生成适龄教育插画或绘本配图。",
        "access": "read",
        "allowed_roles": ["teacher", "coach", "guardian", "ward"],
        "input_schema": {"type": "object", "required": ["prompt"], "properties": {"prompt": {"type": "string"}}},
        "output_schema": {"type": "object"},
        "timeout_ms": 30000,
        "handler_id": "media.generate_image",
    },
]

def build_default_registries() -> tuple[ToolRegistry, SkillRegistry]:
    tool_reg = ToolRegistry()
    for spec in _INITIAL_TOOLS:
        tool_reg.register_spec(spec)
    tool_reg.register_handler("agent.load_skill", lambda args, ctx: {"skill_id": args["skill_id"]})
    tool_reg.register_handler("study.get_focus_state", handle_study_get_focus_state)
    tool_reg.register_handler("ward_context.read_summary", handle_ward_context_read_summary)
    tool_reg.register_handler("math.compute", handle_math_compute)
    tool_reg.register_handler("web.search", handle_web_search)
    for name in (
        "problem_solving.solve_and_verify",
        "tutoring.run_homework_turn",
        "artifact.create_or_revise",
        "artifact.get_view",
        "image.inspect_crop",
        "media.generate_image",
    ):
        tool_reg.register_handler(name, _unimplemented_placeholder(name))
    tool_reg.validate_alignment()

    skill_reg = SkillRegistry()
    from app.agent_specs.definitions import active_definitions
    from app.application.agent.skill_catalog import bootstrap_skills

    active = active_definitions()
    declarations = getattr(active, "education_skills", None) or bootstrap_skills()
    for spec in declarations.values():
        skill_reg.register_skill(spec)
    skill_reg.validate_against_tools(tool_reg)
    return tool_reg, skill_reg
