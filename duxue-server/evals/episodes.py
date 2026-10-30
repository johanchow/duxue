"""Authored multi-turn scenarios. No application imports, so CI can validate offline."""

from __future__ import annotations

import json
import hashlib
from pathlib import Path
from typing import Literal

from pydantic import Field, ValidationError, model_validator

from evals import dataset
from evals.schema import Context, EvalCase, Expect, OUTCOMES, Strict, Utterance

EPISODES_DIR = dataset.DATA_DIR / "multi_turn"
Origin = Literal["MathDial", "SocraTeach", "CoMTA", "self"]


class EpisodeTurn(Strict):
    student_said: str = Field(min_length=1)
    # A different student reply after clarification or another allowed tutor move.
    student_on: dict[str, str] = Field(default_factory=dict)
    context: Context
    expect: Expect
    tags: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def branch_keys(self):
        if set(self.student_on) - set(OUTCOMES):
            raise ValueError("student_on keys must be tutoring outcomes")
        if any(not text.strip() for text in self.student_on.values()):
            raise ValueError("student_on replies must not be empty")
        return self


class Episode(Strict):
    id: str = Field(pattern=r"^episode-[a-z0-9-]+$")
    title: str
    inspired_by: Origin
    source: Literal["synthetic"] = "synthetic"
    review_batch: str | None = Field(default=None, pattern=r"^[a-z][a-z0-9-]{1,40}$")
    label_status: Literal["confirmed", "proposed", "needs_decision"] = "proposed"
    reviewed_by: str | None = None
    initial_history: list[Utterance] = Field(default_factory=list, max_length=8)
    turns: list[EpisodeTurn] = Field(min_length=6, max_length=10)
    note: str


def load_episodes(path: Path = EPISODES_DIR) -> list[Episode]:
    if not path.exists():
        return []
    files = [path] if path.is_file() else sorted(path.glob("*.json"))
    rows: list[Episode] = []
    for file in files:
        try:
            rows.append(Episode.model_validate(dataset.read_object(file)))
        except (ValidationError, ValueError) as error:
            raise ValueError(f"{file.name}: {error}") from error
    return rows


def episodes_hash(rows: list[Episode]) -> str:
    payload = [row.model_dump(mode="json") for row in sorted(rows, key=lambda row: row.id)]
    return hashlib.sha256(json.dumps(payload, ensure_ascii=False, sort_keys=True).encode()).hexdigest()[:16]


def turn_case(episode: Episode, index: int, history: list[Utterance], said: str) -> EvalCase:
    turn = episode.turns[index]
    return EvalCase(
        id=f"{episode.id}-{index:02d}", component="tutoring.turn", conversation_id=episode.id,
        turn_index=index, history=history[-8:], student_said=said, context=turn.context,
        expect=turn.expect, tags=["multi-turn", *turn.tags], source="synthetic",
        review_batch=episode.review_batch, label_status=episode.label_status,
        reviewed_by=episode.reviewed_by, note=episode.note,
    )


def validate_episodes(rows: list[Episode]) -> list[str]:
    problems: list[str] = []
    seen: set[str] = set()
    for episode in rows:
        if episode.id in seen:
            problems.append(f"{episode.id}: duplicate episode id")
        seen.add(episode.id)
        if episode.label_status == "confirmed" and not episode.reviewed_by:
            problems.append(f"{episode.id}: confirmed needs reviewed_by")
        if episode.label_status != "confirmed" and episode.reviewed_by:
            problems.append(f"{episode.id}: reviewer on unconfirmed episode")
        for index, turn in enumerate(episode.turns):
            if not turn.expect.is_specific():
                problems.append(f"{episode.id}:{index}: turn needs specific expectation")
            case = turn_case(episode, index, episode.initial_history, turn.student_said)
            problems.extend(dataset.validate([case]))
            for reply in turn.student_on.values():
                branch_case = turn_case(episode, index, episode.initial_history, reply)
                problems.extend(dataset.validate([branch_case]))
    return problems
