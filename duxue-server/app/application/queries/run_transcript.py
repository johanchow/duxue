"""Thread transcript window for the next model call.

The window keeps recent utterances on the same conversation verbatim. Older ones
are omitted by count, not rewritten into a summary. The current turn is excluded
because the caller already supplies it as this turn's student message. Run
boundaries do not hide the previous sentence: the student refers to the dialogue
they can see.
"""
from __future__ import annotations

from sqlalchemy.orm import Session

from app.infrastructure.persistence.models import CompanionMessage

MAX_UTTERANCES = 8
MAX_UTTERANCE_CHARS = 2400


def select_recent_utterances(
    rows: list[dict],
    *,
    exclude_turn_id: str | None,
    max_messages: int = MAX_UTTERANCES,
    max_chars: int = MAX_UTTERANCE_CHARS,
) -> tuple[list[dict], int]:
    """Keep the newest thread originals that fit the budget.

    ``rows`` are oldest first. Each row has ``turn_id``, ``author``, ``text``
    and ``had_image``. Returns ``(kept, omitted_count)``.
    """
    eligible = [
        row for row in rows
        if row.get("turn_id") != exclude_turn_id and (row.get("text") or "").strip()
    ]
    kept = list(eligible)
    omitted = 0
    while len(kept) > 1 and (len(kept) > max_messages or _chars(kept) > max_chars):
        kept.pop(0)
        omitted += 1
    if kept and _chars(kept) > max_chars:
        latest = dict(kept[-1])
        latest["text"] = latest["text"][-max_chars:]
        latest["leading_omitted"] = True
        kept = [latest]
    return kept, omitted


def recent_thread_utterances(
    db: Session, *, ward_id: str, thread_id: str, exclude_turn_id: str | None,
) -> tuple[list[dict], int]:
    rows = (
        db.query(CompanionMessage)
        .filter_by(ward_id=ward_id, thread_id=thread_id)
        .order_by(CompanionMessage.thread_version)
        .all()
    )
    projected = [
        {
            "turn_id": row.turn_id,
            "author": row.author_type,
            "text": row.content,
            "had_image": bool(row.attachment_refs),
        }
        for row in rows
    ]
    return select_recent_utterances(projected, exclude_turn_id=exclude_turn_id)


def _chars(rows: list[dict]) -> int:
    return sum(len(row.get("text") or "") for row in rows)
