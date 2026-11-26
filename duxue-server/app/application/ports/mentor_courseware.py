"""Application Ports for Tutoring.MentorCourseware (P0-1)."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal, Protocol
from uuid import UUID

from app.contexts.tutoring.domain.mentor_courseware import (
    CoursewareStep,
    CoursewareVersion,
    MentorCourseware,
    VerificationBaseline,
    VisualSpec,
)

ProductionStage = Literal["queued", "solving", "directing", "rendering", "judging", "ready", "failed"]


@dataclass(frozen=True)
class ProductionStatusSnapshot:
    courseware_id: str
    stage: ProductionStage
    message: str
    revision_id: str | None = None
    updated_at: str = ""
    error_code: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "courseware_id": self.courseware_id,
            "stage": self.stage,
            "message": self.message,
            "revision_id": self.revision_id,
            "updated_at": self.updated_at,
            "error_code": self.error_code,
        }


@dataclass(frozen=True)
class DirectorDraftResult:
    change_summary: str
    methodology_key: str | None
    steps: tuple[CoursewareStep, ...]
    requires_reverify: bool = False
    target_step_ids: tuple[str, ...] = ()


@dataclass(frozen=True)
class PedagogicalJudgeResult:
    passed: bool
    critique: str = ""
    issues: tuple[str, ...] = ()


class MentorCoursewareRepository(Protocol):
    """Aggregate repository port with optimistic CAS on state_revision."""

    def get(self, courseware_id: UUID) -> MentorCourseware | None: ...

    def get_by_create_command(self, guardian_id: UUID, command_id: str) -> MentorCourseware | None: ...

    def create(self, courseware: MentorCourseware, *, command_id: str) -> None: ...

    def save_cas(self, courseware: MentorCourseware, *, expected_state_revision: int) -> None: ...


class ProductionStatusStore(Protocol):
    """Non-domain technical progress store (never enters aggregate state machine)."""

    def set_status(self, snapshot: ProductionStatusSnapshot) -> None: ...

    def get_status(self, courseware_id: UUID) -> ProductionStatusSnapshot | None: ...


class ProblemVerificationPort(Protocol):
    """ACL port to ProblemSolving stateless solver + optional read-only bank lookup."""

    def solve_and_verify(
        self,
        *,
        prompt_text: str,
        attachment_keys: tuple[str, ...],
        guardian_id: UUID,
    ) -> VerificationBaseline: ...

    def reverify_revision(
        self,
        *,
        baseline: VerificationBaseline,
        instruction: str,
        draft_steps: tuple[CoursewareStep, ...],
    ) -> tuple[bool, VerificationBaseline | None, str]: ...


class PedagogicalDirectorPort(Protocol):
    """Port for generating initial courseware steps or localized revision patches."""

    def draft_initial(
        self,
        *,
        prompt_text: str,
        baseline: VerificationBaseline,
        target_grade_hint: str | None = None,
    ) -> DirectorDraftResult: ...

    def draft_revision(
        self,
        *,
        current_version: CoursewareVersion,
        baseline: VerificationBaseline,
        instruction: str,
        target_step_id: str | None = None,
        critique: str | None = None,
    ) -> DirectorDraftResult: ...


class PedagogicalJudgePort(Protocol):
    """Independent heterogeneous judge checking reasoning clarity & visual alignment."""

    def review(
        self,
        *,
        prompt_text: str,
        baseline: VerificationBaseline,
        draft: DirectorDraftResult,
    ) -> PedagogicalJudgeResult: ...


class CoursewareMediaRenderPort(Protocol):
    """Validates and normalizes visual specs (P0-1: component_scene + layered_svg)."""

    def validate_and_prepare(self, visual: VisualSpec) -> VisualSpec: ...
