"""tutor-turn.v4 的只读工具。全部限于当前 Ward，不改变许可，没有副作用。

观察结果是不可信输入，只带类型化的状态：unique、ambiguous、no_match、tool_error。
"""

from __future__ import annotations

from sqlalchemy.orm import Session

from app.agent_specs.definitions import load_definitions
from app.agent_specs.static_tools import static_tool_result
from app.application.workflows.teaching_skills import history_candidates
from app.infrastructure.observability.telemetry import (
    agent_step_span,
    set_observation_payload,
)
from app.infrastructure.persistence.models import TutoringMessage, TutoringProblem

from app.agent_specs.configuration import code_contract

_FIXED = code_contract()["files"]["workflows/tutoring.json"]
MAX_TOOL_CALLS = _FIXED["limits"]["tool_calls"]
MAX_MODEL_CALLS = _FIXED["limits"]["model_calls"]
TOOL_NAMES = tuple(tool_id.split(".", 1)[1] for tool_id in code_contract()["tool_authority"]["tutoring.turn"])
_HISTORY_LIMIT = 3


def __getattr__(name):
    if name == "SVG_WIDGET_GUIDELINES":
        return static_tool_result("tutoring.widget_guidelines")["guidelines"]
    raise AttributeError(name)


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

    def run(self, name: str, args: dict | None) -> dict:
        allowed = {tool_id.split(".", 1)[1] for tool_id in load_definitions().units["tutoring.turn"].tools}
        with agent_step_span("tool", name if name in allowed else "unknown_tool",
                             **{"agent.tool.source": "model_request"}) as span:
            args = args if isinstance(args, dict) else {}
            set_observation_payload(span, input=args)
            handlers = {
                "get_task_context": self._task_context,
                "get_attempt_summary": self._attempt_summary,
                "lookup_history": self._lookup_history,
            }
            for tool_id in load_definitions().units["tutoring.turn"].tools:
                if load_definitions().tools[tool_id].handler_id == "tool.static_result":
                    handlers[tool_id.split(".", 1)[1]] = (
                        lambda args, tool_id=tool_id: static_tool_result(tool_id, args)
                    )
            handlers = {key: value for key, value in handlers.items() if key in allowed}
            if set(handlers) != allowed:
                raise ValueError("tutoring tool handlers differ from Agent definition")
            handler = handlers.get(name)
            if handler is None:
                span.set_attribute("agent.tool.status", "tool_error")
                result = {"tool": name, "status": "tool_error", "detail": "unknown_tool"}
                set_observation_payload(span, output=result)
                return result
            try:
                result = {"tool": name, **handler(args)}
            except Exception:
                result = {"tool": name, "status": "tool_error"}
            span.set_attribute("agent.tool.status", result.get("status", "tool_error"))
            set_observation_payload(span, output=result)
            return result

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
        return {"status": "unique" if len(hits) == 1 else "ambiguous", "matches": hits}
