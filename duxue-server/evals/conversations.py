"""Versioned fixed-history conversation contract; validation needs no app settings."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Annotated, Literal

from pydantic import Field, model_validator

from evals.dataset import DATA_DIR, read_object
from evals.dialogue import Dialogue, Evidence, Message
from evals.schema import (
    ASSET_NAME,
    OUTCOMES,
    Context,
    EvalCase,
    Expect,
    ProblemContext,
    ReferenceResponse,
    Strict,
    Utterance,
)

DIRECTORY = DATA_DIR / "conversation_replay"
Text = Annotated[str, Field(min_length=1)]


class Verdict(Strict):
    leaks: bool = Field(strict=True)
    reason: Text
    answer_protected: bool | None = Field(default=None, strict=True)

    @model_validator(mode="after")
    def consistent(self):
        if (self.reason == "none") == self.leaks:
            raise ValueError("reason must be none iff leaks is false")
        return self


class GateInput(Strict):
    task_title: str | None
    problem: Text
    reply: Text
    images: list[str] = Field(default_factory=list)


class Gate(Strict):
    observation_id: Text
    input: GateInput
    observed_verdict: Verdict
    observed_facts: dict | None = None


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
    repair_feedback_status: Literal["observed", "unavailable"] = "observed"


class AttemptSummary(Strict):
    substantive_attempts: int = Field(ge=0, strict=True)
    hints_given: int = Field(ge=0, strict=True)
    evidence_summary: str | None


class Permit(Strict):
    answer_protected: bool = Field(strict=True)
    active_subgoal: str | None
    attempt_summary: AttemptSummary


class Snapshot(Strict):
    provenance: Evidence
    recent_problems: list[Text] = Field(default_factory=list, max_length=3)
    permit: Permit
    task_title: str | None


class TurnExpect(Strict):
    outcome_in: list[Literal[OUTCOMES]] = Field(min_length=1)
    response: ReferenceResponse
    exit_gate: Verdict
    criteria: list[Text] = Field(min_length=1)
    visual: Literal["present", "absent"] | None = None
    visual_kind_in: list[Literal["steps", "compare", "segment", "number_line", "svg"]] = Field(default_factory=list)
    selected_images: list[str] | None = None
    review_conclusion: Literal["all_correct", "some_incorrect", "uncertain", "not_checking"] | None = None


class GateExpect(Verdict):
    reason_in: list[Text] = Field(default_factory=list)
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


class ConversationEval(Dialogue):
    title: Text
    type: Literal["conversation_replay"]
    replay_mode: Literal["fixed_history"]
    review_batch: Text
    messages: list[Message] = Field(min_length=1)
    attempts: list[Attempt]
    checks: list[Annotated[TurnCheck | GateCheck, Field(discriminator="component")]] = Field(min_length=1)
    note: Text

    @model_validator(mode="after")
    def references(self):
        if (self.source.kind != "real" or not self.source.trace_ids
                or not self.source.provider or not self.source.history_observation_id):
            raise ValueError("conversation replay needs real trace sources")
        if any(isinstance(c, TurnCheck) and c.input_snapshot.provenance.origin == "missing" for c in self.checks):
            raise ValueError("conversation replay requires explicit snapshots")
        assets = [name for message in self.messages for name in message.images]
        assets += [name for attempt in self.attempts for name in attempt.gate.input.images]
        assets += [name for check in self.checks if isinstance(check, TurnCheck) for name in check.expect.selected_images or []]
        if any(not ASSET_NAME.fullmatch(name) for name in assets):
            raise ValueError("invalid conversation image asset")
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
            if attempt.repair_feedback_status == 'unavailable' and (
                attempt.retry_of is None or attempt.repair_feedback is not None
            ):
                raise ValueError('unavailable feedback requires a prior retry without fabricated feedback')
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
                missing_allowed = attempt.repair_feedback_status == "unavailable" and attempt.repair_feedback is None
                if attempt.retry_of not in prior or attempts[attempt.retry_of].after_message != attempt.after_message or (not attempt.repair_feedback and not missing_allowed):
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
        snapshot_origin=snapshot.provenance.origin, record_digest=conversations_hash([row]),
        id=check.id, component="tutoring.turn", conversation_id=row.id, turn_index=index // 2,
        history=[Utterance(author="ward" if m.role == "user" else "companion", text=m.content, images=m.images, image_target_refs=m.image_target_refs)
                 for m in row.messages[max(0, index - 8):index]],
        student_said=row.messages[index].content, images=row.messages[index].images,
        context=Context(task_title=snapshot.task_title, recent_problems=snapshot.recent_problems, problem=ProblemContext(
            active_subgoal=permit.active_subgoal, **permit.attempt_summary.model_dump(),
        ) if permit.answer_protected else None),
        expect=Expect(outcome_in=check.expect.outcome_in,
                      answer_protected=check.expect.exit_gate.answer_protected,
                      visual=check.expect.visual, visual_kind_in=check.expect.visual_kind_in,
                      selected_images=check.expect.selected_images, review_conclusion=check.expect.review_conclusion), source="real",
        label_status=row.label_status, reviewed_by=row.reviewed_by, review_batch=row.review_batch,
    )
