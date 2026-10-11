"""Dataset record: one decision point (history + injected context + the Ward's sentence)."""

from __future__ import annotations

import re
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

Component = Literal["tutoring.turn", "companion.intent"]
LabelStatus = Literal["confirmed", "proposed", "needs_decision"]
Source = Literal["real", "synthetic"]

# tutoring.turn result categories (derived from the production exit checks)
OUTCOMES = ("answer", "hint_like", "chat", "clarify", "redirect", "pronounce", "blocked", "fallback")
INTENTS = ("planning", "tutoring", "reflection", "unclear")

ASSET_NAME = re.compile(r"^[a-z0-9][a-z0-9._-]{0,63}\.(jpg|jpeg|png|webp)$")
MAX_WINDOW = 8


class Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Utterance(Strict):
    author: Literal["ward", "companion"]
    text: str = ""
    # Asset names only. Files live in var/eval-assets/ and never enter git.
    images: list[str] = Field(default_factory=list)


class ProblemContext(Strict):
    """An open work-product problem. Absent means the Ward has no open problem."""

    summary: str | None = None
    active_subgoal: str | None = None
    substantive_attempts: int = 0
    hints_given: int = 0
    evidence_summary: str | None = None


class Context(Strict):
    problem: ProblemContext | None = None
    task_title: str | None = None
    task_active: bool = False
    tutoring_intent: str | None = None
    focus_agent_type: str | None = None


class Expect(Strict):
    """Assertions. ``fallback`` is always a failure unless a case lists it explicitly."""

    outcome_in: list[Literal[OUTCOMES]] = Field(default_factory=list)  # type: ignore[valid-type]
    outcome_not_in: list[Literal[OUTCOMES]] = Field(default_factory=lambda: ["fallback"])  # type: ignore[valid-type]
    lesson_source_contains_any: list[str] = Field(default_factory=list)
    content_contains_any: list[str] = Field(default_factory=list)
    content_not_contains: list[str] = Field(default_factory=list)
    intent_in: list[Literal[INTENTS]] = Field(default_factory=list)  # type: ignore[valid-type]

    def is_specific(self) -> bool:
        """True when the case asserts more than "did not fall back"."""
        return bool(
            self.outcome_in or self.lesson_source_contains_any or self.content_contains_any
            or self.content_not_contains or self.intent_in or set(self.outcome_not_in) != {"fallback"}
        )


class EvalCase(Strict):
    id: str = Field(pattern=r"^[a-z0-9][a-z0-9._-]{2,80}$")
    component: Component
    conversation_id: str
    turn_index: int = Field(ge=0)
    history: list[Utterance] = Field(default_factory=list, max_length=MAX_WINDOW)
    student_said: str = Field(min_length=1)
    images: list[str] = Field(default_factory=list)
    context: Context = Field(default_factory=Context)
    expect: Expect = Field(default_factory=Expect)
    tags: list[str] = Field(default_factory=list)
    source: Source
    flags: list[str] = Field(default_factory=list)
    label_status: LabelStatus = "proposed"
    reviewed_by: str | None = None
    note: str | None = None

    @model_validator(mode="after")
    def component_fields_match(self):
        if self.component == "companion.intent":
            if self.expect.outcome_in or self.expect.lesson_source_contains_any or self.expect.content_contains_any:
                raise ValueError("intent cases may only assert intent_in")
        elif self.expect.intent_in:
            raise ValueError("intent_in belongs to companion.intent cases")
        return self

    @property
    def asset_names(self) -> list[str]:
        names = [name for row in self.history for name in row.images] + list(self.images)
        return list(dict.fromkeys(names))
