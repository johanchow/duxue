"""答案状态与本轮许可。不访问数据库，也不解释开放文本。

唯一红线：作业成果不被代替完成。`TutorPermitPolicy.permit()` 在调用模型前算出许可，
`advance()` 在本轮通过出口检查后推进题目记录；本轮表现只影响下一轮。
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from typing import Literal

SolutionState = Literal["locked", "unlocked", "solved"]

ATTEMPT_LIMIT = 3          # N：实质性尝试总数兜底，待产品确认
NO_PROGRESS_LIMIT = 2      # 连续无进展次数，待产品确认
HINT_ACTS = frozenset({"probe", "hint", "example"})


@dataclass(frozen=True)
class ProblemState:
    """`ProblemRecord` 中由 Policy 管理的字段。"""

    solution_state: SolutionState = "locked"
    substantive_attempts: int = 0
    no_progress_streak: int = 0
    hints_given: int = 0
    answer_requested: bool = False
    status: Literal["open", "solved", "abandoned"] = "open"


@dataclass(frozen=True)
class AttemptSummary:
    substantive_attempts: int = 0
    no_progress_streak: int = 0
    hints_given: int = 0


@dataclass(frozen=True)
class TutorPermit:
    solution: Literal["locked", "unlocked"]
    must_remind_task: bool
    task_title: str | None
    attempt_summary: AttemptSummary

    def as_context(self) -> dict:
        return {
            "solution": self.solution,
            "must_remind_task": self.must_remind_task,
            "task_title": self.task_title,
            "attempt_summary": {
                "substantive_attempts": self.attempt_summary.substantive_attempts,
                "no_progress_streak": self.attempt_summary.no_progress_streak,
                "hints_given": self.attempt_summary.hints_given,
            },
        }


@dataclass(frozen=True)
class ProblemAssessment:
    """已通过出口检查的本轮标注。"""

    effective_work_product: bool
    student_turn_kind: str
    progress: str | None
    same_problem: bool
    act: str
    counts_as_attempt: bool


class TutorPermitPolicy:
    @staticmethod
    def permit(
        problem: ProblemState | None, *, task_id: str | None, session_status: str, task_title: str | None,
    ) -> TutorPermit:
        solution = "unlocked" if problem is not None and problem.solution_state == "unlocked" else "locked"
        remind = bool(task_id and session_status in {"active", "paused"})
        summary = AttemptSummary(
            problem.substantive_attempts, problem.no_progress_streak, problem.hints_given,
        ) if problem is not None else AttemptSummary()
        return TutorPermit(solution, remind, task_title if remind else None, summary)

    @staticmethod
    def advance(problem: ProblemState | None, assessment: ProblemAssessment) -> ProblemState | None:
        """返回新的题目状态；非作业成果的轮次不改变任何东西。

        旧题在调用方被关闭为 abandoned；这里只在需要时给出新题的初始状态。
        """
        if not assessment.effective_work_product:
            return problem
        if problem is None or problem.status != "open" or not assessment.same_problem:
            problem = ProblemState()
        state = problem
        if assessment.act in HINT_ACTS:
            state = replace(state, hints_given=state.hints_given + 1)
        if assessment.student_turn_kind == "ask_answer":
            state = replace(state, answer_requested=True)
        if assessment.counts_as_attempt and assessment.student_turn_kind == "attempt":
            attempts = state.substantive_attempts + 1
            streak = state.no_progress_streak + 1 if assessment.progress == "none" else 0
            state = replace(state, substantive_attempts=attempts, no_progress_streak=streak)
            if assessment.progress == "solved":
                return replace(state, solution_state="solved", status="solved")
        if state.solution_state == "locked" and _should_unlock(state):
            state = replace(state, solution_state="unlocked")
        return state


def _should_unlock(state: ProblemState) -> bool:
    if state.no_progress_streak >= NO_PROGRESS_LIMIT:
        return True
    if state.substantive_attempts >= ATTEMPT_LIMIT:
        return True
    return state.answer_requested and state.substantive_attempts >= 1
