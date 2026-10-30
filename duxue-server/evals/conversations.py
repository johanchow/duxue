"""Versioned fixed-history conversation contract; validation needs no app settings."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Annotated, Literal

from pydantic import Field, model_validator

from evals.dataset import DATA_DIR, read_object
from evals.schema import Strict, LabelStatus, EvalCase, Context, ProblemContext, Expect, Utterance, OUTCOMES

DIRECTORY = DATA_DIR / "conversation_replay"
Text = Annotated[str, Field(min_length=1)]


class Source(Strict):
    kind: Literal["real"]
    provider: Text
    trace_ids: list[Text] = Field(min_length=1)
    history_observation_id: Text
    coverage: Literal["observed_window"]
    note: Text


class Message(Strict):
    id: Text
    role: Literal["user", "assistant"]
    content: Text


class Verdict(Strict):
    leaks: bool = Field(strict=True)
    reason: Text

    @model_validator(mode="after")
    def consistent(self):
        if (self.reason == "none") == self.leaks:
            raise ValueError("reason must be none iff leaks is false")
        return self


class GateInput(Strict):
    task_title: str | None
    problem: Text
    reply: Text


class Gate(Strict):
    observation_id: Text
    input: GateInput
    observed_verdict: Verdict


class Attempt(Strict):
    id: Text
    after_message: Text
    trace_id: Text
    generation_observation_id: Text
    model: Text
    prompt_id: Text
    candidate: dict
    gate: Gate
    shown_to_user: bool = Field(strict=True)
    delivered_as: str | None
    retry_of: Text | None = None
    repair_feedback: Text | None = None


class AttemptSummary(Strict):
    substantive_attempts: int = Field(ge=0, strict=True)
    hints_given: int = Field(ge=0, strict=True)
    evidence_summary: str | None


class Permit(Strict):
    answer_protected: bool = Field(strict=True)
    active_subgoal: str | None
    attempt_summary: AttemptSummary


class Snapshot(Strict):
    permit: Permit
    task_title: str | None


class Response(Strict):
    message: Text


class TurnExpect(Strict):
    outcome_in: list[Literal[OUTCOMES]] = Field(min_length=1)
    response: Response
    exit_gate: Verdict
    criteria: list[Text] = Field(min_length=1)


class GateExpect(Verdict):
    criteria: list[Text] = Field(min_length=1)


class TurnCheck(Strict):
    id: Text
    after_message: Text
    component: Literal["tutoring.turn"]
    source_observation_id: Text
    input_snapshot: Snapshot
    expect: TurnExpect


class GateCheck(Strict):
    id: Text
    after_message: Text
    attempt_id: Text
    component: Literal["tutoring.leak-judge"]
    expect: GateExpect


class ConversationEval(Strict):
    schema_version: Literal["conversation-eval.v1"]
    id: Text
    title: Text
    type: Literal["conversation_replay"]
    replay_mode: Literal["fixed_history"]
    source: Source
    review_batch: Text
    label_status: LabelStatus
    reviewed_by: str | None
    messages: list[Message] = Field(min_length=1)
    attempts: list[Attempt]
    checks: list[Annotated[TurnCheck | GateCheck, Field(discriminator="component")]] = Field(min_length=1)
    note: Text

    @model_validator(mode="after")
    def references(self):
        if (self.label_status == "confirmed") != bool(self.reviewed_by):
            raise ValueError("confirmed requires reviewer; other labels cannot claim one")
        for rows in (self.messages, self.attempts, self.checks):
            if len({r.id for r in rows}) != len(rows):
                raise ValueError("duplicate id")
        positions = {m.id: i for i, m in enumerate(self.messages)}
        attempts = {a.id: a for a in self.attempts}
        def user_index(ref):
            if ref not in positions or self.messages[positions[ref]].role != "user":
                raise ValueError("after_message must reference a user message")
            return positions[ref]
        prior = set()
        for attempt in self.attempts:
            index = user_index(attempt.after_message)
            if attempt.trace_id not in self.source.trace_ids:
                raise ValueError("attempt trace missing from source")
            if attempt.gate.input.reply != attempt.candidate.get("content"):
                raise ValueError("gate input must match original candidate")
            if attempt.shown_to_user:
                if index + 1 >= len(self.messages):
                    raise ValueError("missing delivered message")
                delivered = self.messages[index + 1]
                if delivered.role != "assistant" or delivered.id != attempt.delivered_as or delivered.content != attempt.candidate.get("content"):
                    raise ValueError("delivery must match next visible candidate")
            elif attempt.delivered_as is not None:
                raise ValueError("unshown attempt cannot claim delivery")
            if attempt.retry_of is not None:
                if attempt.retry_of not in prior or attempts[attempt.retry_of].after_message != attempt.after_message or not attempt.repair_feedback:
                    raise ValueError("retry must reference prior attempt in same turn with feedback")
            elif attempt.repair_feedback is not None:
                raise ValueError("repair feedback needs retry_of")
            prior.add(attempt.id)
        for check in self.checks:
            user_index(check.after_message)
            if isinstance(check, GateCheck):
                if check.attempt_id not in attempts or attempts[check.attempt_id].after_message != check.after_message:
                    raise ValueError("gate check must reference an attempt in the same turn")
            elif not any(a.generation_observation_id == check.source_observation_id and a.after_message == check.after_message for a in self.attempts):
                raise ValueError("turn check source must match a generation in the same turn")
        return self


def load_conversations(path: Path = DIRECTORY) -> list[ConversationEval]:
    files = [path] if path.is_file() else sorted(path.glob("*.json"))
    rows = []
    for file in files:
        row = ConversationEval.model_validate(read_object(file))
        if file.stem != row.id or file.suffix != ".json":
            raise ValueError(f"{file.name}: expected <id>.json")
        rows.append(row)
    if len({r.id for r in rows}) != len(rows):
        raise ValueError("duplicate conversation id")
    return rows


def conversations_hash(rows: list[ConversationEval]) -> str:
    payload = [r.model_dump(mode="json") for r in sorted(rows, key=lambda r: r.id)]
    return hashlib.sha256(json.dumps(payload, ensure_ascii=False, sort_keys=True).encode()).hexdigest()[:16]


def turn_case(row: ConversationEval, check: TurnCheck) -> EvalCase:
    index = next(i for i, m in enumerate(row.messages) if m.id == check.after_message)
    snapshot = check.input_snapshot
    permit = snapshot.permit
    return EvalCase(
        id=check.id, component="tutoring.turn", conversation_id=row.id, turn_index=index // 2,
        history=[Utterance(author="ward" if m.role == "user" else "companion", text=m.content)
                 for m in row.messages[max(0, index - 8):index]],
        student_said=row.messages[index].content,
        context=Context(task_title=snapshot.task_title, problem=ProblemContext(
            active_subgoal=permit.active_subgoal, **permit.attempt_summary.model_dump(),
        ) if permit.answer_protected else None),
        expect=Expect(outcome_in=check.expect.outcome_in), source="real",
        label_status=row.label_status, reviewed_by=row.reviewed_by, review_batch=row.review_batch,
    )
