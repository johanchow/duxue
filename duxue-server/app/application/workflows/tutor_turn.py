"""tutor-turn.v2：模型候选契约与出口检查。

候选是不可信的提议。每轮必经三道检查：结构、越权与一致性、泄露。
任一不通过，调用方回退固定话术，不写事实，不推进题目记录。
"""

from __future__ import annotations

import json
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
from app.application.workflows.tutor_visual import (
    VISUAL_ACTS,
    VISUAL_ADAPTER,
    Visual,
    drop_reason,
)
from app.contexts.study.domain.execution import ANSWER_LEAK_MARKERS
from app.contexts.tutoring.domain.tutor_permit import TutorPermit

CONTRACT_ID = "tutor-turn.v2"

Act = Literal["answer", "guide", "chat", "clarify", "redirect", "pronounce", "safety"]
Relation = Literal["none", "same", "new"]
StudentMove = Literal["attempt", "request_hint", "request_answer", "other"]
Progress = Literal["none", "some", "submitted"]

# `answer` and `guide` are the acts that can reach the Ward's work product, so the
# model must say whether the turn touches it.  Every other act defaults to "none".
_WORK_ACTS = frozenset({"answer", "guide"})
_LESSON_KEYS = ("source_text", "locale", "introduction", "reading_guide", "notes")

SAFE_TEXT = "这件事需要先告诉身边信任的大人。我们先停一下，等你准备好了再继续学习。"
FALLBACK_TEXT = "我这次没能整理出回答。把你的想法或要问的那一句再说一次，好吗？"
REMINDER = "先回到正在进行的任务，这个问题可以稍后再问。"


def _blank_is_absent(value):
    """Models often emit "" for unused optional fields. That is unset, not a value."""
    if isinstance(value, str) and not value.strip():
        return None
    return value


class WorkAssessment(BaseModel):
    """The model's self-report about the Ward's work product.

    Only ``relation`` can widen or narrow answer protection, so it is the one field
    that is required (and only for acts that can reveal an answer).  The
    rest only feed ``TutorPermitPolicy.advance()``: an unknown value is "not
    reported", never a reason to replace a safe reply.
    """

    model_config = ConfigDict(extra="ignore")
    relation: Relation | None = None
    student_move: StudentMove = "other"
    progress: Progress | None = None
    evidence: str | None = None
    next_subgoal: str | None = None

    @field_validator("relation", mode="before")
    @classmethod
    def _relation(cls, value):
        # An unknown value is "not reported".  For act=answer|guide that is a
        # structure error (repaired once); it is never guessed.
        return value if value in Relation.__args__ else None

    @field_validator("student_move", mode="before")
    @classmethod
    def _student_move(cls, value):
        return value if value in StudentMove.__args__ else "other"

    @field_validator("progress", mode="before")
    @classmethod
    def _progress(cls, value):
        return value if value in Progress.__args__ else None

    @field_validator("evidence", "next_subgoal", mode="before")
    @classmethod
    def _text(cls, value):
        value = _blank_is_absent(value)
        return value[:500] if isinstance(value, str) else None


class ClarifyPayload(BaseModel):
    model_config = ConfigDict(extra="ignore")
    candidates: list[str] = Field(default_factory=list)

    @field_validator("candidates", mode="before")
    @classmethod
    def _candidates(cls, value):
        if not isinstance(value, list):
            return []
        # Models copy the {"ref", "text"} shape of history_candidates.  Show the
        # text, never the repr of a dict; anything else unusable is dropped.
        items = [item.get("text") if isinstance(item, dict) else item for item in value]
        return [item.strip()[:300] for item in items if isinstance(item, str) and item.strip()][:8]


class PronouncePayload(BaseModel):
    model_config = ConfigDict(extra="ignore")
    lesson: LessonBody


class TutorTurnCandidate(BaseModel):
    """tutor-turn.v2.  Required: ``act`` and ``content``.  Everything else is optional
    and lives in the sub-object that belongs to one act, so no field can contradict
    another.  A sub-object that does not belong to the act is dropped before
    validation (see ``shape_by_act``)."""

    # Provider-only fields must not make a safe child-facing reply fail. Unknown
    # fields are discarded and never reach domain state or persistence.
    model_config = ConfigDict(extra="ignore")
    act: Act
    content: str = Field(min_length=1, max_length=1200)
    follow_up_question: str | None = Field(default=None, max_length=300)
    history_ref: str | None = None
    work: WorkAssessment | None = None
    clarify: ClarifyPayload | None = None
    pronounce: PronouncePayload | None = None
    # 配图是可选的展示增强：非法或不适用时整张丢弃并记下原因，绝不让候选整体失败。
    visual: Visual | None = None
    visual_dropped: str | None = Field(default=None, exclude=True)

    @field_validator("follow_up_question", "history_ref", mode="before")
    @classmethod
    def blank_optional_text_is_absent(cls, value):
        return _blank_is_absent(value)

    @model_validator(mode="before")
    @classmethod
    def shape_by_act(cls, value):
        """Keep only what the act can use.

        Dropping is safe because a dropped field is never projected: ``lesson`` is
        shown only for ``pronounce`` and ``candidates`` only for ``clarify``.  The
        one repair is the exact misplacement models make for a lesson: its fields
        at the top level, or ``lesson`` outside ``pronounce``; likewise ``candidates``
        for ``clarify``.  A missing ``work.relation`` on an act that can reveal an
        answer is deliberately *not* repaired.
        """
        if not isinstance(value, dict):
            return value
        value = dict(value)
        act = value.get("act")
        if act == "pronounce":
            payload = value.get("pronounce")
            if not isinstance(payload, dict) or not isinstance(payload.get("lesson"), dict):
                lesson = value.get("lesson")
                if not isinstance(lesson, dict):
                    lesson = {key: value[key] for key in _LESSON_KEYS if key in value}
                if lesson.get("source_text"):
                    value["pronounce"] = {"lesson": lesson}
        else:
            value.pop("pronounce", None)
        if act == "clarify":
            if not isinstance(value.get("clarify"), dict) and isinstance(value.get("candidates"), list):
                value["clarify"] = {"candidates": value["candidates"]}
        else:
            value.pop("clarify", None)
        if not isinstance(value.get("work"), dict):
            value.pop("work", None)
        value.pop("visual_dropped", None)  # 只由这里写，模型自报的无效
        raw_visual = value.pop("visual", None)
        if raw_visual not in (None, "", {}, []):
            if act not in VISUAL_ACTS:
                value["visual_dropped"] = "visual_not_applicable"
            else:
                try:
                    value["visual"] = VISUAL_ADAPTER.validate_python(raw_visual)
                except ValidationError as error:
                    value["visual_dropped"] = drop_reason(error)
        for key in ("lesson", *_LESSON_KEYS, "candidates"):
            value.pop(key, None)
        return value

    @model_validator(mode="after")
    def work_relation_for_answer_acts(self):
        if self.act in _WORK_ACTS and (self.work is None or self.work.relation is None):
            raise ValueError("work.relation is required for act=answer|guide")
        return self

    # ---- derived views: one place that knows the nested layout -------------
    @property
    def relation(self) -> Relation:
        return (self.work.relation if self.work else None) or "none"

    @property
    def student_move(self) -> StudentMove:
        return self.work.student_move if self.work else "other"

    @property
    def progress(self) -> Progress | None:
        return self.work.progress if self.work else None

    @property
    def subgoal_evidence(self) -> str | None:
        return self.work.evidence if self.work else None

    @property
    def next_subgoal(self) -> str | None:
        return self.work.next_subgoal[:300] if self.work and self.work.next_subgoal else None

    @property
    def lesson(self) -> LessonBody | None:
        return self.pronounce.lesson if self.pronounce else None

    @property
    def candidates(self) -> list[str]:
        return self.clarify.candidates if self.clarify else []


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


def build_tutor_instruction(
    *, content: str, permit: TutorPermit, history_candidates: list[dict], tutoring_intent: str | None,
) -> str:
    """The per-turn instruction JSON. Shared by the workflow and the offline evaluation."""
    return json.dumps({
        "student_said": content,
        "permit": permit.as_context(),
        "history_candidates": history_candidates,
        "expected_act": "pronounce" if tutoring_intent == "pronunciation" else None,
    }, ensure_ascii=False)


def check_authority(
    candidate: TutorTurnCandidate, permit: TutorPermit, *, has_open_problem: bool,
    authorized_history_refs: frozenset[str], has_work_input: bool,
) -> Verdict:
    """检查 2：越权与一致性。只收紧，不放松。

    只有会让孩子看到不该看的内容的情形才拒绝（答案保护、发音卡不可用）。
    与展示无关的字段不一致已经在候选解析时丢弃或降级，不会走到这里。
    """
    act = candidate.act
    if act == "safety":
        return Verdict(True)
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

    # `relation` is the model's own report of whether this turn touches the Ward's work
    # product.  It only decides *how closely we look*, never whether a reply may be shown:
    # the one red line is that the Ward is not handed the finished homework.  So a protected
    # turn is judged on its content (answer marker, leak judge, fail-closed), not rejected
    # because its labels look contradictory (e.g. act=answer with relation=new on what is
    # really a knowledge question).  A label can still never loosen an existing protected
    # problem: only an explicit "none" leaves the work product.
    relation = candidate.relation
    claims_work = relation in {"same", "new"}
    answer_protected = claims_work and (
        not has_open_problem or relation == "new" or permit.answer_protected
    )
    if answer_protected and any(marker in candidate.content for marker in ANSWER_LEAK_MARKERS):
        return Verdict(False, "answer_marker")
    # An `answer` is a direct reply to a question, not the child's attempt at a problem, so it
    # never opens, abandons or advances a problem record (a mislabelled knowledge question must
    # not lock the next turn).  It is still leak-checked when it claims to touch the work.
    work_product = claims_work and act != "answer"
    ref = candidate.history_ref if candidate.history_ref in authorized_history_refs else None
    return Verdict(
        True, effective_work_product=work_product, answer_protected=answer_protected,
        needs_leak_check=answer_protected, history_ref=ref,
    )
