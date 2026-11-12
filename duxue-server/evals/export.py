"""Turn a real conversation into reviewable dataset candidates.

Follows the dataset recipe in the Khanmigo paper: take real conversations, flag the ones
that went wrong automatically, and let a person decide what is right before anything is
kept. Nothing exported here is trusted: ``grading`` is a proposed baseline and ``label_status`` is
``proposed`` until a human edits and confirms it.
"""

from __future__ import annotations

import hashlib
import re
from collections.abc import Callable
from pathlib import Path

from app.application.process_managers.companion_coordinator import _CLARIFY_REPLY
from app.application.queries.run_transcript import select_recent_utterances
from app.application.workflows.tutor_turn import FALLBACK_TEXT
from evals.dataset import ASSETS_DIR, scrub
from evals.dialogue import (
    VERSION,
    ContextSnapshot,
    Message,
    Source,
    TurnCheck,
    TurnRecord,
)
from evals.grading import Grading

_NUMBERED_LIST = re.compile(r"\n1\. ")
_IMAGE_SUFFIXES = {".jpg", ".jpeg", ".png", ".webp"}


def _norm(text: str) -> str:
    return "".join(text.split())


def _flags(rows: list[dict], index: int) -> list[str]:
    """Automatic markers of "this decision point went badly". A person confirms them."""
    flags: list[str] = []
    reply = None
    for later in rows[index + 1 :]:
        if later["author"] == "ward":
            break
        reply = later
        break
    if reply is None:
        flags.append("no_reply")
    else:
        text = reply.get("text") or ""
        if text.startswith(FALLBACK_TEXT):
            flags.append("fallback_reply")
        if text.startswith(_CLARIFY_REPLY):
            flags.append("intent_unclear")
        if _NUMBERED_LIST.search(text):
            flags.append("clarify_reply")
            previous = [r for r in rows[:index] if r["author"] == "companion"]
            if previous and _NUMBERED_LIST.search(previous[-1].get("text") or ""):
                flags.append("clarify_repeat")
    said = _norm(rows[index].get("text") or "")
    if said and any(
        _norm(r.get("text") or "") == said
        for r in rows[:index]
        if r["author"] == "ward"
    ):
        flags.append("ward_repeat")
    return flags


def build_cases(
    rows: list[dict],
    *,
    conversation_id: str,
    component: str,
    asset_for: Callable[[str], str],
    names: tuple[str, ...] = (),
    snapshots: dict[str, ContextSnapshot] | None = None,
) -> list[TurnRecord]:
    """``rows`` are the thread's messages, oldest first (``author``, ``text``, ``attachment_refs``)."""
    short = "intent" if component == "companion.intent" else "turn"
    # select_recent_utterances drops rows whose turn_id equals the excluded one (None here).
    rows = [
        {
            **row,
            "turn_id": row.get("turn_id") or f"row-{i}",
            "eval_message_id": f"m{i + 1}",
        }
        for i, row in enumerate(rows)
    ]
    # Message storage does not contain a historical domain-state snapshot.
    # In particular, later tutor text must not be used to reconstruct earlier state.
    cases: list[TurnRecord] = []

    def message(item):
        return Message(
            id=item["eval_message_id"],
            role="user" if item["author"] == "ward" else "assistant",
            content=scrub(item.get("text") or "", names),
            images=[asset_for(key) for key in item.get("attachment_refs") or []],
            image_target_refs=list(item.get("image_target_refs") or []),
        )

    ordinal = 0
    for index, row in enumerate(rows):
        if row["author"] != "ward":
            continue
        position, ordinal = ordinal, ordinal + 1
        text = scrub((row.get("text") or "").strip(), names)
        if not text and not row.get("attachment_refs"):
            continue
        prior, _omitted = select_recent_utterances(rows[:index], exclude_turn_id=None)
        current = message(row)
        snapshot = (snapshots or {}).get(row["turn_id"]) or ContextSnapshot(
            origin="missing",
            context=None,
            note="消息存储未提供当时的题目/任务/路由状态；须从对应运行证据补齐，禁止依据后续回复推断。",
        )
        cases.append(
            TurnRecord(
                schema_version=VERSION,
                type="single_turn",
                replay_mode="fixed_history",
                id=f"{short}-{conversation_id}-{position:02d}",
                conversation_id=conversation_id,
                turn_index=position,
                messages=[*[message(item) for item in prior], current],
                source=Source(
                    kind="real",
                    provider="companion_messages",
                    coverage="observed_window",
                ),
                checks=[
                    TurnCheck(
                        id="check-1",
                        after_message=current.id,
                        component=component,
                        input_snapshot=snapshot,
                        grading=Grading.model_validate(
                            {
                                "deterministic": [
                                    {
                                        "id": "baseline",
                                        "field": "intent"
                                        if component == "companion.intent"
                                        else "outcome",
                                        "op": "in"
                                        if component == "companion.intent"
                                        else "not_in",
                                        "expected": [
                                            "planning",
                                            "tutoring",
                                            "reflection",
                                            "unclear",
                                        ]
                                        if component == "companion.intent"
                                        else ["fallback"],
                                    }
                                ],
                                "model_graded": []
                                if component == "companion.intent"
                                else [
                                    {
                                        "id": "quality",
                                        "type": "score",
                                        "rubric_ref": "teaching-quality.v1",
                                        "min_score": 4,
                                    }
                                ],
                            }
                        ),
                    )
                ],
                flags=_flags(rows, index),
                label_status="proposed",
                note="自动导出候选：保留原话与附件；补全期望、状态证据和复核记录后才可用于质量结论。",
            )
        )
    return cases


def asset_writer(
    read_bytes: Callable[[str], bytes], assets_dir: Path | None = None
) -> Callable[[str], str]:
    """Copy a stored image into the local asset directory and return its stable name."""
    target = assets_dir or ASSETS_DIR

    def asset_for(key: str) -> str:
        data = read_bytes(key)
        suffix = Path(key).suffix.lower()
        suffix = suffix if suffix in _IMAGE_SUFFIXES else ".jpg"
        name = f"img-{hashlib.sha256(data).hexdigest()[:12]}{suffix}"
        target.mkdir(parents=True, exist_ok=True)
        path = target / name
        if not path.exists():
            path.write_bytes(data)
        return name

    return asset_for


def load_thread_rows(db, thread_prefix: str) -> tuple[str, list[dict]]:
    """Messages of the one thread whose id starts with ``thread_prefix`` (read-only)."""
    from sqlalchemy import String, cast

    from app.infrastructure.persistence.models import CompanionMessage

    ids = {
        str(value)
        for (value,) in db.query(CompanionMessage.thread_id)
        .filter(cast(CompanionMessage.thread_id, String).like(f"{thread_prefix}%"))
        .distinct()
        .all()
    }
    if len(ids) != 1:
        raise ValueError(
            f"thread prefix {thread_prefix!r} matches {len(ids)} threads; need exactly one"
        )
    thread_id = ids.pop()
    messages = (
        db.query(CompanionMessage)
        .filter(CompanionMessage.thread_id == thread_id)
        .order_by(CompanionMessage.thread_version)
        .all()
    )
    rows = [
        {
            "turn_id": m.turn_id,
            "author": m.author_type,
            "text": m.content,
            "attachment_refs": list(m.attachment_refs or []),
            "image_target_refs": list(
                (m.interaction_ref or {}).get("image_target_refs", [])
            ),
        }
        for m in messages
    ]
    return thread_id[:8], rows
