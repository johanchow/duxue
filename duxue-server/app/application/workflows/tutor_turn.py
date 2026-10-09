"""tutor-turn.v1：模型候选契约与出口检查。

候选是不可信的提议。每轮必经三道检查：结构、越权与一致性、泄露。
任一不通过，调用方回退固定话术，不写事实，不推进题目记录。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal, Protocol

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from app.application.workflows.pronunciation_guidance import LessonBody, forbidden_text, normalized
from app.contexts.study.domain.execution import ANSWER_LEAK_MARKERS
from app.contexts.study.domain.tutor_permit import HINT_ACTS, TutorPermit

CONTRACT_ID = "tutor-turn.v1"

Act = Literal["answer", "probe", "hint", "confirm", "example", "clarify", "redirect", "pronounce"]
QuestionKind = Literal["knowledge_lookup", "work_product_help", "chat", "safety"]
StudentTurnKind = Literal["attempt", "ask_hint", "ask_answer", "off_topic", "other"]

SAFE_TEXT = "这件事需要先告诉身边信任的大人。我们先停一下，等你准备好了再继续学习。"
FALLBACK_TEXT = "我这次没能整理出回答。把你的想法或要问的那一句再说一次，好吗？"
REMINDER = "先回到正在进行的任务，这个问题可以稍后再问。"


class TutorTurnCandidate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    act: Act
    question_kind: QuestionKind
    content: str = Field(min_length=1, max_length=1200)
    follow_up_question: str | None = Field(default=None, max_length=300)
    candidates: list[str] = Field(default_factory=list, max_length=8)
    student_turn_kind: StudentTurnKind
    progress: Literal["none", "some", "solved"] | None = None
    same_problem: bool
    is_assignment_content: bool
    reveals_solution: bool
    history_ref: str | None = None
    lesson: LessonBody | None = None


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


@dataclass(frozen=True)
class Verdict:
    ok: bool
    reason: str = ""
    effective_work_product: bool = False
    solution: str = "locked"
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
    if candidate.progress is not None and candidate.student_turn_kind != "attempt":
        return Verdict(False, "progress_without_attempt")
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
    # 换了新题，旧题的解锁不继承。
    solution = permit.solution if (has_open_problem and candidate.same_problem) else "locked"
    reveals = candidate.reveals_solution or act == "answer"
    if work_product:
        if solution == "locked" and reveals:
            return Verdict(False, "reveals_while_locked")
        if solution == "unlocked" and reveals and not (candidate.follow_up_question or "").strip():
            return Verdict(False, "unlocked_without_verification")
    if work_product and solution == "locked":
        if any(marker in candidate.content for marker in ANSWER_LEAK_MARKERS):
            return Verdict(False, "answer_marker")
    needs_leak = (work_product and solution == "locked") or (
        act == "answer" and permit.must_remind_task and not work_product
    )
    ref = candidate.history_ref if candidate.history_ref in authorized_history_refs else None
    return Verdict(
        True, effective_work_product=work_product, solution=solution,
        needs_leak_check=needs_leak, history_ref=ref,
    )
