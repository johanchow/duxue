"""Internal runner inputs and shared assertions; disk records live in dialogue.py."""

from __future__ import annotations

import re
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from evals.grading import Grading

Component = Literal["tutoring.turn", "companion.intent"]
LabelStatus = Literal["confirmed", "proposed", "needs_decision"]
Source = Literal["real", "synthetic"]
SnapshotOrigin = Literal["synthetic", "recorded", "reconstructed", "missing"]

ASSET_NAME = re.compile(r"^[a-z0-9][a-z0-9._-]{0,63}\.(jpg|jpeg|png|webp)$")
MAX_WINDOW = 8


class Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Utterance(Strict):
    author: Literal["ward", "companion"]
    text: str = ""
    # Asset names only. Files live in var/eval-assets/ and never enter git.
    images: list[str] = Field(default_factory=list)
    image_target_refs: list[str] = Field(default_factory=list)


class ProblemContext(Strict):
    """An open work-product problem. Absent means the Ward has no open problem."""

    summary: str | None = None
    active_subgoal: str | None = None
    substantive_attempts: int = 0
    hints_given: int = 0
    evidence_summary: str | None = None


class Context(Strict):
    recent_problems: list[str] = Field(default_factory=list, max_length=3)
    problem: ProblemContext | None = None
    task_title: str | None = None
    task_active: bool = False
    tutoring_intent: str | None = None
    focus_agent_type: str | None = None


class EvalCase(Strict):
    # Internal runner input, projected from a versioned dialogue record.
    snapshot_origin: SnapshotOrigin = "synthetic"
    record_digest: str | None = None
    id: str = Field(pattern=r"^[a-z0-9][a-z0-9._-]{2,80}$")
    component: Component
    conversation_id: str
    turn_index: int = Field(ge=0)
    history: list[Utterance] = Field(default_factory=list, max_length=MAX_WINDOW)
    student_said: str
    images: list[str] = Field(default_factory=list)
    context: Context = Field(default_factory=Context)
    grading: Grading
    case_id: str | None = None
    check_id: str = "check-1"
    tags: list[str] = Field(default_factory=list)
    source: Source
    flags: list[str] = Field(default_factory=list)
    review_batch: str | None = Field(default=None, pattern=r"^[a-z][a-z0-9-]{1,40}$")
    label_status: LabelStatus = "proposed"
    reviewed_by: str | None = None
    note: str | None = None

    @model_validator(mode="after")
    def component_fields_match(self):
        if not self.student_said.strip() and not self.images:
            raise ValueError("student turn requires text or images")
        self.grading.for_component(self.component)
        return self

    @property
    def asset_names(self) -> list[str]:
        names = [name for row in self.history for name in row.images] + list(
            self.images
        )
        return list(dict.fromkeys(names))
