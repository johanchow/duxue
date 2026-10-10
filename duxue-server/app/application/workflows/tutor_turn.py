"""tutor-turn.v1：模型候选契约与出口检查。

候选是不可信的提议。每轮必经三道检查：结构、越权与一致性、泄露。
任一不通过，调用方回退固定话术，不写事实，不推进题目记录。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal, Protocol

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    ValidationError,
    field_validator,
    model_validator,
)

from app.application.workflows.pronunciation_guidance import (
    LessonBody,
    forbidden_text,
    normalized,
)
from app.contexts.study.domain.execution import ANSWER_LEAK_MARKERS
from app.contexts.tutoring.domain.tutor_permit import TutorPermit

CONTRACT_ID = "tutor-turn.v1"

Act = Literal["answer", "probe", "hint", "confirm", "example", "clarify", "redirect", "pronounce"]
QuestionKind = Literal["knowledge_lookup", "work_product_help", "chat", "safety"]
StudentTurnKind = Literal["attempt", "ask_hint", "ask_answer", "off_topic", "other"]

_LESSON_KEYS = ("source_text", "locale", "introduction", "reading_guide", "notes")

SAFE_TEXT = "这件事需要先告诉身边信任的大人。我们先停一下，等你准备好了再继续学习。"
FALLBACK_TEXT = "我这次没能整理出回答。把你的想法或要问的那一句再说一次，好吗？"
REMINDER = "先回到正在进行的任务，这个问题可以稍后再问。"


class TutorTurnCandidate(BaseModel):
    # Provider-only fields must not make a safe child-facing reply fail. Unknown
    # fields are discarded and never reach domain state or persistence.
    model_config = ConfigDict(extra="ignore")
    act: Act
    question_kind: QuestionKind
    content: str = Field(min_length=1, max_length=1200)
    follow_up_question: str | None = Field(default=None, max_length=300)
    candidates: list[str] = Field(default_factory=list, max_length=8)
    student_turn_kind: StudentTurnKind = "other"
    progress: Literal["none", "some", "solved"] | None = None
    # An omitted relationship to an existing open problem must fail closed.
    same_problem: bool = True
    is_assignment_content: bool = False
    reveals_solution: bool = False
    subgoal_evidence: str | None = Field(default=None, max_length=500)
    next_subgoal: str | None = Field(default=None, max_length=300)
    history_ref: str | None = None
    lesson: LessonBody | None = None

    @field_validator("follow_up_question", "subgoal_evidence", "next_subgoal", "history_ref", mode="before")
    @classmethod
    def blank_optional_text_is_absent(cls, value):
        """Models often emit "" for unused optional fields. That is unset, not a value."""
        if isinstance(value, str) and not value.strip():
            return None
        return value

    @model_validator(mode="before")
    @classmethod
    def normalize_pronounce_shape(cls, value):
        """Discard harmless misplaced metadata before validating the child-facing core.

        This normalizes only the unprojected lesson on ``clarify``.  In
        particular, an invalid ``question_kind`` on an answer is deliberately
        *not* repaired: guessing there could weaken work-product protection.
        """
        if not isinstance(value, dict):
            return value
        value = dict(value)
        act = value.get("act")
        if act == "clarify":
            # A clarification says the referenced source has not been
            # confirmed.  lesson is never projected for it, so it is safe to
            # discard before its own fields are validated.
            value.pop("lesson", None)
            for key in _LESSON_KEYS:
                value.pop(key, None)

        # "pronounce" is an act, never a question_kind.  Repair this exact
        # misplaced token only for acts that cannot reveal an answer.
        if value.get("question_kind") == "pronounce" and act in {"pronounce", "clarify"}:
            value["question_kind"] = "chat"

        if act != "pronounce":
            return value

        kind = value.get("question_kind")
        if kind is None or (isinstance(kind, str) and not kind.strip()):
            value["question_kind"] = "chat"
        lesson = value.get("lesson")
        if not isinstance(lesson, dict):
            lifted = {key: value[key] for key in _LESSON_KEYS if key in value}
            if lifted.get("source_text"):
                value["lesson"] = lifted
        for key in _LESSON_KEYS:
            value.pop(key, None)
        return value


class TutorModelPort(Protocol):
    def complete(
        self, *, envelope: dict, instruction: str, recent_utterances: list[dict] | None = None,
        current_images: list[str | None] | None = None, repair_error: str | None = None,
        observations: list[dict] | None = None,
    ) -> dict:
        """返回候选，或 {"tool": 名称, "args": {...}} 请求一次只读工具。"""


class LeakJudgePort(Protocol):
    def leaks(self, *, text: str, task_title: str | None, problem_summary: str | None) -> bool | None:
        """True 泄露；False 未泄露；None 判定失败（按泄露处理）。"""


def format_schema_error(error: Exception) -> str:
    if isinstance(error, ValidationError):
        parts = []
        for item in error.errors()[:8]:
            loc = ".".join(str(piece) for piece in item.get("loc", ()))
            parts.append(f"{loc}: {item.get('msg')}")
        return "；".join(parts)[:800]
    return str(error)[:800]


def schema_error_diagnostic(error: Exception) -> tuple[str, str]:
    """Return bounded attributes suitable for traces, never the candidate text."""
    if isinstance(error, ValidationError) and error.errors():
        first = error.errors()[0]
        location = first.get("loc", ())
        field = str(location[0]) if location else "root"
        return str(first.get("type", "validation_error")), field[:64]
    return "validation_error", "root"


@dataclass(frozen=True)
class Verdict:
    ok: bool
    reason: str = ""
    effective_work_product: bool = False
    answer_protected: bool = False
    needs_leak_check: bool = False
    history_ref: str | None = None


def check_authority(
    candidate: TutorTurnCandidate, permit: TutorPermit, *, has_open_problem: bool,
    authorized_history_refs: frozenset[str], has_work_input: bool,
) -> Verdict:
    """检查 2：越权与一致性。只收紧，不放松。"""
    act = candidate.act
    if candidate.question_kind == "safety":
        return Verdict(True)
    if candidate.lesson is not None and act != "pronounce":
        return Verdict(False, "lesson_without_pronounce")
    if candidate.candidates and act != "clarify":
        return Verdict(False, "candidates_without_clarify")
    # Progress/evidence only affect `advance()`, which already ignores them for
    # non-attempt turns. A stray annotation is not an answer-leak risk and must
    # not replace an otherwise safe reply with the generic fallback.
    if candidate.next_subgoal is not None and candidate.question_kind != "work_product_help":
        return Verdict(False, "subgoal_without_work_product")
    if act == "confirm" and candidate.progress != "solved":
        return Verdict(False, "confirm_without_solved")
    if act == "pronounce":
        if candidate.lesson is None:
            return Verdict(False, "pronounce_without_lesson")
        lesson_text = [candidate.lesson.source_text, candidate.lesson.introduction, candidate.lesson.reading_guide]
        for note in candidate.lesson.notes:
            lesson_text.extend([note.explanation, note.segment or ""])
        if any(forbidden_text(chunk) for chunk in lesson_text):
            return Verdict(False, "lesson_markup")
        source = normalized(candidate.lesson.source_text)
        if any(note.segment and normalized(note.segment) not in source for note in candidate.lesson.notes):
            return Verdict(False, "segment_not_in_source")
        return Verdict(True)
    if act == "clarify":
        return Verdict(True)

    work_product = (
        candidate.question_kind == "work_product_help"
        or candidate.is_assignment_content
        or (has_open_problem and candidate.same_problem and candidate.question_kind != "chat")
    )
    # A newly recognised work-product question starts protected.  A model label
    # can never turn an existing protected problem into an unprotected one.
    answer_protected = work_product and (
        not has_open_problem or not candidate.same_problem or permit.answer_protected
    )
    reveals = candidate.reveals_solution or act == "answer"
    if answer_protected and reveals:
        return Verdict(False, "reveals_protected_work_product")
    if answer_protected and any(marker in candidate.content for marker in ANSWER_LEAK_MARKERS):
        return Verdict(False, "answer_marker")
    needs_leak = answer_protected
    ref = candidate.history_ref if candidate.history_ref in authorized_history_refs else None
    return Verdict(
        True, effective_work_product=work_product, answer_protected=answer_protected,
        needs_leak_check=needs_leak, history_ref=ref,
    )
