"""Code-locked RolePolicy for dual-role Education General Agent.

Admin configuration may only narrow these ceilings; it can never widen them.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

AgentRole = Literal["teacher", "coach", "guardian", "ward"]
ADULT_ROLES: frozenset[str] = frozenset({"teacher", "coach", "guardian"})
ALL_ROLES: frozenset[str] = ADULT_ROLES | {"ward"}

# Code-owned role ceilings for Skills (Admin can only specify a subset).
SKILL_ROLE_CEILINGS: dict[str, frozenset[str]] = {
    "edu.homework_tutoring": ALL_ROLES,
    "edu.worksheet_grading": ADULT_ROLES,
    "edu.interactive_courseware": ALL_ROLES,
    "edu.lesson_pack": ADULT_ROLES,
    "edu.creative_studio": ALL_ROLES,
}

# Code-owned role ceilings for Tools (Admin can only specify a subset).
TOOL_ROLE_CEILINGS: dict[str, frozenset[str]] = {
    "agent.load_skill": ALL_ROLES,
    "problem_solving.solve_and_verify": ADULT_ROLES,
    "math.compute": ALL_ROLES,
    "tutoring.run_homework_turn": ALL_ROLES,
    "artifact.create_or_revise": ALL_ROLES,
    "artifact.get_view": ALL_ROLES,
    "ward_context.read_summary": ADULT_ROLES,
    "study.get_focus_state": frozenset({"ward"}),
    "image.inspect_crop": ALL_ROLES,
    "web.search": ALL_ROLES,
    "media.generate_image": ALL_ROLES,
}

# Default General Mode exposes ONLY safe read-only base tools + load_skill.
SAFE_BASE_TOOLS: frozenset[str] = frozenset(
    {
        "agent.load_skill",
        "web.search",
        "math.compute",
    }
)

# 4 education-specific mandatory gates (generic content safety relies on upstream provider APIs).
EDU_MANDATORY_GATES: frozenset[str] = frozenset(
    {
        "tutoring.answer_protection",
        "ward.anti_ghostwriting",
        "artifact.verification_honesty",
        "media.script_sandbox_prerun",
    }
)


@dataclass(frozen=True)
class RolePolicyDecision:
    role: AgentRole
    allowed_skills: frozenset[str]
    base_tools: frozenset[str]
    all_permitted_tools: frozenset[str]
    mandatory_gates: frozenset[str]
    can_read_bound_ward: bool


def normalize_role(role: str) -> AgentRole:
    if role == "admin":
        return "guardian"
    if role not in ALL_ROLES:
        raise ValueError(f"unsupported agent role: {role}")
    return role  # type: ignore[return-value]


def verify_skill_role_ceiling(skill_id: str, configured_roles: set[str]) -> None:
    ceiling = SKILL_ROLE_CEILINGS.get(skill_id)
    if ceiling is not None and not configured_roles.issubset(ceiling):
        extra = sorted(configured_roles - ceiling)
        raise ValueError(
            f"skill {skill_id} configured roles {extra} exceed code ceiling {sorted(ceiling)}"
        )


def verify_tool_role_ceiling(tool_id: str, configured_roles: set[str]) -> None:
    ceiling = TOOL_ROLE_CEILINGS.get(tool_id)
    if ceiling is not None and not configured_roles.issubset(ceiling):
        extra = sorted(configured_roles - ceiling)
        raise ValueError(
            f"tool {tool_id} configured roles {extra} exceed code ceiling {sorted(ceiling)}"
        )


def evaluate_role_policy(
    *,
    role: str,
    context_ward_bound: bool = False,
) -> RolePolicyDecision:
    normalized = normalize_role(role)
    is_adult = normalized in ADULT_ROLES
    allowed_skills = frozenset(
        sid for sid, roles in SKILL_ROLE_CEILINGS.items() if normalized in roles
    )
    all_permitted_tools = frozenset(
        tid for tid, roles in TOOL_ROLE_CEILINGS.items() if normalized in roles
    )
    base_tools = set(SAFE_BASE_TOOLS & all_permitted_tools)
    if is_adult and context_ward_bound:
        base_tools.add("ward_context.read_summary")
    else:
        all_permitted_tools = all_permitted_tools - {"ward_context.read_summary"}
    mandatory_gates: set[str] = set()
    if normalized == "ward":
        mandatory_gates.add("tutoring.answer_protection")
    return RolePolicyDecision(
        role=normalized,
        allowed_skills=allowed_skills,
        base_tools=frozenset(base_tools),
        all_permitted_tools=all_permitted_tools,
        mandatory_gates=frozenset(mandatory_gates),
        can_read_bound_ward=is_adult and context_ward_bound,
    )
