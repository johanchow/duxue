"""Shared on-disk dialogue contract; runners consume explicit projections of it.

No app imports. A message is evidence, an expectation is not model input, and a
missing snapshot never becomes a purportedly observed default state.
"""
from __future__ import annotations

import hashlib
import json
from typing import Annotated, Literal

from pydantic import Field, model_validator

from evals.schema import (
    ASSET_NAME,
    OUTCOMES,
    Component,
    Context,
    EvalCase,
    Expect,
    LabelStatus,
    SnapshotOrigin,
    Strict,
    Utterance,
)

VERSION = 'dialogue-eval.v1'
Text = Annotated[str, Field(min_length=1)]


def digest(record: dict) -> str:
    return hashlib.sha256(json.dumps(record, ensure_ascii=False, sort_keys=True).encode()).hexdigest()[:16]


class Message(Strict):
    id: str = Field(min_length=1)
    role: Literal['user', 'assistant']
    content: str
    images: list[str] = Field(default_factory=list)
    image_target_refs: list[str] = Field(default_factory=list)

    @model_validator(mode='after')
    def valid_content(self):
        if not self.content.strip() and not self.images:
            raise ValueError('message requires text or images')
        if any(not ASSET_NAME.fullmatch(name) for name in self.images):
            raise ValueError('invalid message image asset')
        return self

    def utterance(self) -> Utterance:
        return Utterance(author='ward' if self.role == 'user' else 'companion', text=self.content,
                         images=self.images, image_target_refs=self.image_target_refs)


class Source(Strict):
    kind: Literal['real', 'synthetic']
    coverage: Literal['observed_window', 'full_thread', 'authored', 'candidate_only']
    provider: str | None = None
    trace_ids: list[Text] = Field(default_factory=list)
    history_observation_id: str | None = None
    note: str | None = None


class Evidence(Strict):
    origin: SnapshotOrigin
    references: list[Text] = Field(default_factory=list)
    note: str | None = None

    @model_validator(mode='after')
    def recorded_needs_reference(self):
        if self.origin == 'recorded' and not self.references:
            raise ValueError('recorded snapshot needs evidence references')
        return self


class ContextSnapshot(Evidence):
    context: Context | None

    @model_validator(mode='after')
    def missing_is_explicit(self):
        if (self.origin == 'missing') != (self.context is None):
            raise ValueError('missing snapshot requires null context; other snapshots require context')
        return self


class Dialogue(Strict):
    schema_version: Literal['dialogue-eval.v1']
    id: str = Field(min_length=3, max_length=80, pattern=r'^[a-z0-9][a-z0-9._-]+$')
    source: Source
    messages: list[Message]
    review_batch: str | None = Field(default=None, pattern=r"^[a-z][a-z0-9-]{1,40}$")
    label_status: LabelStatus = 'proposed'
    reviewed_by: str | None = None
    note: str | None = None

    @model_validator(mode='after')
    def message_ids_and_review(self):
        if len({m.id for m in self.messages}) != len(self.messages):
            raise ValueError('duplicate message id')
        if (self.label_status == 'confirmed') != bool(self.reviewed_by):
            raise ValueError('confirmed requires reviewer; other labels cannot claim one')
        return self

    def user_index(self, ref: str) -> int:
        for i, message in enumerate(self.messages):
            if message.id == ref and message.role == 'user':
                return i
        raise ValueError('after_message must reference a user message')


class TurnCheck(Strict):
    id: str = Field(min_length=1)
    after_message: str
    component: Component
    input_snapshot: ContextSnapshot
    expect: Expect
    # Authored alternatives, selected by the preceding actual tutor outcome.
    student_on: dict[str, str] = Field(default_factory=dict)
    tags: list[str] = Field(default_factory=list)

    @model_validator(mode='after')
    def valid_branches(self):
        if set(self.student_on) - set(OUTCOMES) or any(not s.strip() for s in self.student_on.values()):
            raise ValueError('student_on requires tutoring outcomes and nonempty replies')
        return self


class TurnRecord(Dialogue):
    type: Literal['single_turn']
    replay_mode: Literal['fixed_history']
    conversation_id: str
    turn_index: int = Field(ge=0)
    checks: list[TurnCheck] = Field(min_length=1, max_length=1)
    tags: list[str] = Field(default_factory=list)
    flags: list[str] = Field(default_factory=list)

    @model_validator(mode='after')
    def checkpoint(self):
        check = self.checks[0]
        self.user_index(check.after_message)
        if self.label_status == 'confirmed' and check.input_snapshot.origin == 'missing':
            raise ValueError('confirmed case needs an input snapshot')
        if check.student_on:
            raise ValueError('branches require generated_history')
        return self

    def to_case(self) -> EvalCase:
        check = self.checks[0]
        index = self.user_index(check.after_message)
        current = self.messages[index]
        return EvalCase(
            id=self.id, component=check.component, conversation_id=self.conversation_id, turn_index=self.turn_index,
            history=[m.utterance() for m in self.messages[max(0, index - 8):index]],
            student_said=current.content, images=current.images,
            context=check.input_snapshot.context or Context(), snapshot_origin=check.input_snapshot.origin,
            record_digest=digest(self.model_dump(mode='json')), expect=check.expect,
            tags=[*self.tags, *check.tags], flags=self.flags, source=self.source.kind,
            review_batch=self.review_batch, label_status=self.label_status, reviewed_by=self.reviewed_by, note=self.note,
        )


class EpisodeRecord(Dialogue):
    type: Literal['episode']
    replay_mode: Literal['generated_history']
    title: str
    inspired_by: Literal['MathDial', 'SocraTeach', 'CoMTA', 'self']
    checks: list[TurnCheck] = Field(min_length=1, max_length=10)

    @model_validator(mode='after')
    def script_order(self):
        if self.source.kind != 'synthetic':
            raise ValueError('generated student scripts must be marked synthetic')
        positions = [self.user_index(c.after_message) for c in self.checks]
        if positions[0] > 8:
            raise ValueError('episode seed history exceeds the production window')
        if positions != list(range(positions[0], len(self.messages))):
            raise ValueError('generated_history checks must cover the ordered user script after the seed history')
        if len({c.id for c in self.checks}) != len(self.checks):
            raise ValueError('duplicate check id')
        if any(c.component != 'tutoring.turn' for c in self.checks):
            raise ValueError('episode checks require tutoring.turn')
        if any(c.input_snapshot.origin == 'missing' for c in self.checks):
            raise ValueError('authored episode requires explicit injected contexts')
        return self

    def to_episode(self):
        from evals.episodes import Episode, EpisodeTurn
        start = self.user_index(self.checks[0].after_message)
        return Episode(
            id=self.id, title=self.title, inspired_by=self.inspired_by, source='synthetic',
            initial_history=[m.utterance() for m in self.messages[:start]],
            turns=[EpisodeTurn(student_said=self.messages[self.user_index(c.after_message)].content,
                               images=self.messages[self.user_index(c.after_message)].images,
                               student_on=c.student_on, context=c.input_snapshot.context, expect=c.expect, tags=c.tags,
                               snapshot_origin=c.input_snapshot.origin)
                   for c in self.checks],
            review_batch=self.review_batch, label_status=self.label_status, reviewed_by=self.reviewed_by,
            note=self.note or '', record_digest=digest(self.model_dump(mode='json')),
        )


class JudgeInput(Evidence):
    task_title: str | None
    # null means construct the production summary from the explicit current request.
    problem: str | None
    current_request: str | None
    images: list[str] = Field(default_factory=list, max_length=1)

    @model_validator(mode='after')
    def complete_input(self):
        if self.origin == 'missing' or not (self.problem or self.current_request):
            raise ValueError('judge input needs problem or current_request')
        if self.problem is not None and not self.problem.strip():
            raise ValueError('empty judge problem')
        if self.problem is not None and self.current_request is not None:
            raise ValueError('judge problem snapshot and current_request are mutually exclusive')
        if any(not ASSET_NAME.fullmatch(name) for name in self.images):
            raise ValueError('invalid judge image asset')
        return self


class JudgeExpect(Strict):
    leaks: bool = Field(strict=True)
    reason: str | None = None
    answer_protected: bool | None = Field(default=None, strict=True)
    criteria: list[Text] = Field(min_length=1)

    @model_validator(mode='after')
    def reason_matches(self):
        if self.reason is not None and (not self.reason.strip() or (self.reason == 'none') == self.leaks):
            raise ValueError('invalid expected reason')
        return self


class JudgeCheck(Strict):
    id: str
    component: Literal['tutoring.leak-judge']
    candidate_id: str
    input_snapshot: JudgeInput
    expect: JudgeExpect


class JudgeRecord(Dialogue):
    type: Literal['judge']
    replay_mode: Literal['fixed_candidate']
    candidates: list[Message] = Field(min_length=1, max_length=1)
    checks: list[JudgeCheck] = Field(min_length=1, max_length=1)
    reference_problem: str = Field(min_length=1)  # Label-only; not a user message.
    pair: str | None = None

    @model_validator(mode='after')
    def candidate_reference(self):
        if self.messages:
            raise ValueError('standalone judge cases contain a snapshot, not a fabricated visible dialogue')
        candidate = self.candidates[0]
        if candidate.role != 'assistant' or not candidate.content.strip() or candidate.images or candidate.image_target_refs:
            raise ValueError('judge candidate must be assistant text')
        if self.checks[0].candidate_id != candidate.id:
            raise ValueError('candidate_id must reference the candidate')
        return self

    def to_case(self) -> dict:
        check = self.checks[0]
        snapshot, expect = check.input_snapshot, check.expect
        case = {'id': self.id, 'component': check.component, 'source': self.source.kind,
                'review_batch': self.review_batch, 'label_status': self.label_status, 'reviewed_by': self.reviewed_by,
                'reply': self.candidates[0].content, 'reference_problem': self.reference_problem,
                'expected_leaks': expect.leaks, 'rationale': '\n'.join(expect.criteria),
                'task_title': snapshot.task_title, 'record_digest': digest(self.model_dump(mode='json'))}
        if snapshot.problem is not None:
            case['problem'] = snapshot.problem
        else:
            case['current_request'] = snapshot.current_request
        if snapshot.images:
            case['image'] = snapshot.images[0]
        if self.pair is not None:
            case['pair'] = self.pair
        if expect.reason is not None:
            case['expected_reason'] = expect.reason
        if expect.answer_protected is not None:
            case['expected_answer_protected'] = expect.answer_protected
        return case
