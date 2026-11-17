"""Tutoring domain value objects & stateless policies for SolutionBlueprint and ProblemGroupContext.

Pure domain module: zero dependencies on ORM, HTTP, LLM SDKs, or SymPy.
Invariants:
- A blueprint distinguishes solution approaches (routes) from cross-route invariants.
- Blueprint existence or milestone completion NEVER unlocks `Disclosure="protected"`.
- ProblemGroupContext preserves shared stem references and verified prior subproblem
  conclusions while keeping at most one `open` subproblem per TutoringSession.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from typing import Literal

CheckKind = Literal[
    "symbolic_equivalence",
    "solution_set_or_counterexample",
    "physics_dimension_and_eq",
    "chemistry_conservation",
    "genetics_ratio",
    "conceptual_rubric",
]
VerificationStatus = Literal["verified", "unverified", "not_applicable"]
MilestoneStudentStatus = Literal["pending", "in_progress", "completed"]


@dataclass(frozen=True)
class ProblemInvariant:
    id: str
    expression: str
    description: str = ""

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "expression": self.expression,
            "description": self.description,
        }

    @classmethod
    def from_dict(cls, raw: dict) -> ProblemInvariant:
        return cls(
            id=str(raw["id"])[:32],
            expression=str(raw["expression"])[:500],
            description=str(raw.get("description") or "")[:300],
        )


@dataclass(frozen=True)
class Milestone:
    id: str
    goal: str
    check_kind: CheckKind = "conceptual_rubric"
    canonical_target: str | None = None
    verification_status: VerificationStatus = "unverified"
    common_pitfalls: tuple[str, ...] = ()
    student_status: MilestoneStudentStatus = "pending"

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "goal": self.goal,
            "check_kind": self.check_kind,
            "canonical_target": self.canonical_target,
            "verification_status": self.verification_status,
            "common_pitfalls": list(self.common_pitfalls),
            "student_status": self.student_status,
        }

    @classmethod
    def from_dict(cls, raw: dict) -> Milestone:
        ck = raw.get("check_kind", "conceptual_rubric")
        if ck not in CheckKind.__args__:
            ck = "conceptual_rubric"
        vs = raw.get("verification_status", "unverified")
        if vs not in VerificationStatus.__args__:
            vs = "unverified"
        ss = raw.get("student_status", "pending")
        if ss not in MilestoneStudentStatus.__args__:
            ss = "pending"
        target = raw.get("canonical_target")
        pitfalls = raw.get("common_pitfalls") or ()
        return cls(
            id=str(raw["id"])[:32],
            goal=str(raw["goal"])[:400],
            check_kind=ck,
            canonical_target=str(target)[:500] if isinstance(target, str) and target.strip() else None,
            verification_status=vs,
            common_pitfalls=tuple(str(p)[:200] for p in pitfalls if isinstance(p, str) and p.strip())[:6],
            student_status=ss,
        )


@dataclass(frozen=True)
class Approach:
    id: str
    name: str
    milestones: tuple[Milestone, ...]

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "name": self.name,
            "milestones": [m.to_dict() for m in self.milestones],
        }

    @classmethod
    def from_dict(cls, raw: dict) -> Approach:
        milestones = tuple(Milestone.from_dict(m) for m in (raw.get("milestones") or [])[:8])
        return cls(
            id=str(raw["id"])[:32],
            name=str(raw["name"])[:120],
            milestones=milestones,
        )


@dataclass(frozen=True)
class SolutionBlueprint:
    subject: str
    problem_digest: str
    approaches: tuple[Approach, ...]
    implicit_constraints: tuple[ProblemInvariant, ...] = ()
    active_approach_id: str | None = None
    active_milestone_id: str | None = None
    schema_version: str = "blueprint.v1"

    def find_approach(self, approach_id: str | None) -> Approach | None:
        if not approach_id:
            return self.approaches[0] if self.approaches else None
        for app in self.approaches:
            if app.id == approach_id:
                return app
        return None

    def find_milestone(self, milestone_id: str | None) -> Milestone | None:
        if not milestone_id:
            return None
        for app in self.approaches:
            for ms in app.milestones:
                if ms.id == milestone_id:
                    return ms
        return None

    def to_dict(self) -> dict:
        return {
            "schema_version": self.schema_version,
            "subject": self.subject,
            "problem_digest": self.problem_digest,
            "implicit_constraints": [c.to_dict() for c in self.implicit_constraints],
            "approaches": [a.to_dict() for a in self.approaches],
            "active_approach_id": self.active_approach_id,
            "active_milestone_id": self.active_milestone_id,
        }

    @classmethod
    def from_dict(cls, raw: dict | None) -> SolutionBlueprint | None:
        if not isinstance(raw, dict) or not raw.get("approaches"):
            return None
        approaches = tuple(Approach.from_dict(a) for a in raw["approaches"][:3])
        if not approaches or not any(a.milestones for a in approaches):
            return None
        constraints = tuple(
            ProblemInvariant.from_dict(c) for c in (raw.get("implicit_constraints") or [])[:8]
        )
        active_app = raw.get("active_approach_id") or approaches[0].id
        active_ms = raw.get("active_milestone_id") or (
            approaches[0].milestones[0].id if approaches[0].milestones else None
        )
        return cls(
            subject=str(raw.get("subject") or "general")[:32],
            problem_digest=str(raw.get("problem_digest") or "")[:64],
            approaches=approaches,
            implicit_constraints=constraints,
            active_approach_id=str(active_app)[:32] if active_app else None,
            active_milestone_id=str(active_ms)[:32] if active_ms else None,
            schema_version=str(raw.get("schema_version") or "blueprint.v1"),
        )


@dataclass(frozen=True)
class VerifiedPriorConclusion:
    subproblem_label: str
    conclusion: str

    def to_dict(self) -> dict:
        return {
            "subproblem_label": self.subproblem_label,
            "conclusion": self.conclusion,
        }

    @classmethod
    def from_dict(cls, raw: dict) -> VerifiedPriorConclusion:
        return cls(
            subproblem_label=str(raw["subproblem_label"])[:32],
            conclusion=str(raw["conclusion"])[:500],
        )


@dataclass(frozen=True)
class ProblemGroupContext:
    shared_stem_ref: str
    shared_stem_summary: str
    subproblem_label: str | None = None
    prior_conclusions: tuple[VerifiedPriorConclusion, ...] = ()

    def advance_to_subproblem(
        self,
        *,
        next_label: str | None,
        verified_conclusion: VerifiedPriorConclusion | None = None,
    ) -> ProblemGroupContext:
        priors = list(self.prior_conclusions)
        if verified_conclusion is not None and verified_conclusion not in priors:
            priors.append(verified_conclusion)
        return ProblemGroupContext(
            shared_stem_ref=self.shared_stem_ref,
            shared_stem_summary=self.shared_stem_summary,
            subproblem_label=next_label,
            prior_conclusions=tuple(priors[-6:]),
        )

    def to_dict(self) -> dict:
        return {
            "shared_stem_ref": self.shared_stem_ref,
            "shared_stem_summary": self.shared_stem_summary,
            "subproblem_label": self.subproblem_label,
            "prior_conclusions": [c.to_dict() for c in self.prior_conclusions],
        }

    @classmethod
    def from_dict(cls, raw: dict | None) -> ProblemGroupContext | None:
        if not isinstance(raw, dict) or not raw.get("shared_stem_ref"):
            return None
        priors = tuple(
            VerifiedPriorConclusion.from_dict(item)
            for item in (raw.get("prior_conclusions") or [])[:6]
            if isinstance(item, dict) and item.get("subproblem_label") and item.get("conclusion")
        )
        label = raw.get("subproblem_label")
        return cls(
            shared_stem_ref=str(raw["shared_stem_ref"])[:64],
            shared_stem_summary=str(raw.get("shared_stem_summary") or "")[:1000],
            subproblem_label=str(label)[:32] if isinstance(label, str) and label.strip() else None,
            prior_conclusions=priors,
        )


class BlueprintProgressPolicy:
    """Stateless domain service advancing milestone progress or switching solution routes."""

    @staticmethod
    def advance(
        blueprint: SolutionBlueprint | None,
        *,
        completed_milestone_id: str | None = None,
        adopted_approach_id: str | None = None,
    ) -> SolutionBlueprint | None:
        if blueprint is None:
            return None

        target_app_id = adopted_approach_id or blueprint.active_approach_id
        # If completed_milestone_id belongs to another approach, switch automatically
        if completed_milestone_id:
            for app in blueprint.approaches:
                if any(ms.id == completed_milestone_id for ms in app.milestones):
                    target_app_id = app.id
                    break

        updated_approaches: list[Approach] = []
        next_active_ms: str | None = blueprint.active_milestone_id

        for app in blueprint.approaches:
            if app.id != target_app_id:
                updated_approaches.append(app)
                continue
            new_milestones: list[Milestone] = []
            for ms in app.milestones:
                if completed_milestone_id and ms.id == completed_milestone_id:
                    new_milestones.append(replace(ms, student_status="completed"))
                else:
                    new_milestones.append(ms)
            # Pick first non-completed milestone on the active approach
            pending = next(
                (ms.id for ms in new_milestones if ms.student_status != "completed"),
                None,
            )
            if pending is not None:
                new_milestones = [
                    replace(ms, student_status="in_progress")
                    if ms.id == pending and ms.student_status == "pending"
                    else ms
                    for ms in new_milestones
                ]
            next_active_ms = pending
            updated_approaches.append(replace(app, milestones=tuple(new_milestones)))

        return replace(
            blueprint,
            approaches=tuple(updated_approaches),
            active_approach_id=target_app_id,
            active_milestone_id=next_active_ms,
        )
