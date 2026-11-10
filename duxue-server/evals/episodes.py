"""Authored multi-turn scenarios. No application imports, so CI can validate offline."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Literal

from pydantic import Field, ValidationError, model_validator

from evals import dataset
from evals.grading import Grading, OUTCOMES
from evals.schema import Context, EvalCase, SnapshotOrigin, Strict, Utterance

EPISODES_DIR = dataset.DATA_DIR / "multi_turn"
Origin = Literal["MathDial", "SocraTeach", "CoMTA", "self"]


class EpisodeTurn(Strict):
    snapshot_origin: SnapshotOrigin = "synthetic"
    student_said: str
    images: list[str] = Field(default_factory=list)
    # A different student reply after clarification or another allowed tutor move.
    student_on: dict[str, str] = Field(default_factory=dict)
    context: Context
    grading: Grading
    check_id: str = "check-1"
    tags: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def branch_keys(self):
        if not self.student_said.strip() and not self.images:
            raise ValueError("student turn requires text or images")
        if set(self.student_on) - set(OUTCOMES):
            raise ValueError("student_on keys must be tutoring outcomes")
        if any(not text.strip() for text in self.student_on.values()):
            raise ValueError("student_on replies must not be empty")
        return self


class Episode(Strict):
    record_digest: str | None = None
    id: str = Field(pattern=r"^[a-z0-9][a-z0-9-]{2,80}$")
    title: str
    inspired_by: Origin
    source: Literal["synthetic"] = "synthetic"
    review_batch: str | None = Field(default=None, pattern=r"^[a-z][a-z0-9-]{1,40}$")
    label_status: Literal["confirmed", "proposed", "needs_decision"] = "proposed"
    reviewed_by: str | None = None
    initial_history: list[Utterance] = Field(default_factory=list, max_length=8)
    turns: list[EpisodeTurn] = Field(min_length=1, max_length=10)
    note: str


def load_episodes(path: Path = EPISODES_DIR) -> list[Episode]:
    if not path.exists():
        return []
    files = [path] if path.is_file() else sorted(path.glob("*.json"))
    rows: list[Episode] = []
    for file in files:
        try:
            from evals.dialogue import EpisodeRecord

            record = EpisodeRecord.model_validate(dataset.read_object(file))
            if file.stem != record.id:
                raise ValueError("filename must match id")
            rows.append(record.to_episode())
        except (ValidationError, ValueError) as error:
            raise ValueError(f"{file.name}: {error}") from error
    return rows


def episodes_hash(rows: list[Episode]) -> str:
    payload = [
        row.model_dump(mode="json") for row in sorted(rows, key=lambda row: row.id)
    ]
    return hashlib.sha256(
        json.dumps(payload, ensure_ascii=False, sort_keys=True).encode()
    ).hexdigest()[:16]


def turn_case(
    episode: Episode, index: int, history: list[Utterance], said: str
) -> EvalCase:
    turn = episode.turns[index]
    return EvalCase(
        snapshot_origin=turn.snapshot_origin,
        record_digest=episode.record_digest,
        id=f"{episode.id}-{index:02d}",
        component="tutoring.turn",
        conversation_id=episode.id,
        turn_index=index,
        history=history[-8:],
        student_said=said,
        images=turn.images,
        context=turn.context,
        grading=turn.grading,
        case_id=episode.id,
        check_id=turn.check_id,
        tags=["multi-turn", *turn.tags],
        source="synthetic",
        review_batch=episode.review_batch,
        label_status=episode.label_status,
        reviewed_by=episode.reviewed_by,
        note=episode.note,
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
            if not turn.grading.is_specific():
                problems.append(
                    f"{episode.id}:{index}: turn needs specific expectation"
                )
            case = turn_case(episode, index, episode.initial_history, turn.student_said)
            problems.extend(dataset.validate([case]))
            for reply in turn.student_on.values():
                branch_case = turn_case(episode, index, episode.initial_history, reply)
                problems.extend(dataset.validate([branch_case]))
    return problems
