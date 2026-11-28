"""Initial 5 Skills & 11 Tools composition root and core read-only ToolHandlers."""

from __future__ import annotations

from typing import Any

from app.application.agent.registry import SkillRegistry, ToolContext, ToolRegistry
from app.application.agent.role_policy import ADULT_ROLES
from app.application.agent.tool_catalog import bootstrap_tools
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


def build_default_registries() -> tuple[ToolRegistry, SkillRegistry]:
    from app.agent_specs.definitions import active_definitions
    from app.application.agent.skill_catalog import bootstrap_skills

    active = active_definitions()
    tool_declarations = getattr(active, "education_tools", None) or bootstrap_tools()
    tool_reg = ToolRegistry()
    for spec in tool_declarations.values():
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
    declarations = getattr(active, "education_skills", None) or bootstrap_skills()
    for spec in declarations.values():
        skill_reg.register_skill(spec)
    skill_reg.validate_against_tools(tool_reg)
    return tool_reg, skill_reg
