"""tutor-turn.v1 的只读工具。全部限于当前 Ward，不改变许可，没有副作用。

观察结果是不可信输入，只带类型化的状态：unique、ambiguous、no_match、tool_error。
"""

from __future__ import annotations

from sqlalchemy.orm import Session

from app.application.workflows.teaching_skills import history_candidates
from app.infrastructure.persistence.models import TutoringMessage, TutoringProblem

MAX_TOOL_CALLS = 3
MAX_MODEL_CALLS = 4
TOOL_NAMES = ("get_task_context", "get_attempt_summary", "lookup_history")
_HISTORY_LIMIT = 3


class TutorToolbox:
    def __init__(
        self, db: Session, *, tutoring_session_id: str | None, problem: TutoringProblem | None,
        task_title: str | None, task_active: bool, window: list[dict],
    ):
        self.db = db
        self.tutoring_session_id = tutoring_session_id
        self.problem = problem
        self.task_title = task_title
        self.task_active = task_active
        self.window = window
        self.authorized_refs: set[str] = {item["ref"] for item in history_candidates(window)}

    def run(self, name: str, args: dict | None) -> dict:
        args = args if isinstance(args, dict) else {}
        handler = {
            "get_task_context": self._task_context,
            "get_attempt_summary": self._attempt_summary,
            "lookup_history": self._lookup_history,
        }.get(name)
        if handler is None:
            return {"tool": name, "status": "tool_error", "detail": "unknown_tool"}
        try:
            return {"tool": name, **handler(args)}
        except Exception:  # noqa: BLE001 - tool failures are intentionally isolated per observation.
            return {"tool": name, "status": "tool_error"}

    def _task_context(self, _args: dict) -> dict:
        if not self.task_active or not self.task_title:
            return {"status": "no_match"}
        return {"status": "unique", "task_title": self.task_title}

    def _attempt_summary(self, _args: dict) -> dict:
        row = self.problem
        if row is None:
            return {"status": "no_match"}
        return {
            "status": "unique", "substantive_attempts": row.substantive_attempts,
            "hints_given": row.hints_given, "evidence_summary": row.evidence_summary,
            "active_subgoal": row.active_subgoal, "problem_summary": row.summary,
        }

    def _lookup_history(self, args: dict) -> dict:
        query = str(args.get("query") or "").strip()
        if not query:
            return {"status": "no_match"}
        hits = [
            {"ref": item["ref"], "author": item["author"], "text": item["text"]}
            for item in history_candidates(self.window) if query in item["text"]
        ]
        if self.tutoring_session_id:
            rows = (
                self.db.query(TutoringMessage)
                .filter(TutoringMessage.tutoring_session_id == self.tutoring_session_id,
                        TutoringMessage.role == "ward", TutoringMessage.content.contains(query))
                .order_by(TutoringMessage.created_at.desc()).limit(_HISTORY_LIMIT).all()
            )
            hits += [{"ref": f"m:{row.id}", "author": "ward", "text": row.content} for row in rows]
        hits = hits[:_HISTORY_LIMIT]
        if not hits:
            return {"status": "no_match"}
        self.authorized_refs.update(hit["ref"] for hit in hits)
        return {"status": "unique" if len(hits) == 1 else "ambiguous", "matches": hits}
