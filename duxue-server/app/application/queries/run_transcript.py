"""Thread transcript window for the next model call.

The window keeps recent utterances on the same conversation verbatim. Older ones
are omitted by count, not rewritten into a summary. The current turn is excluded
because the caller already supplies it as this turn's student message. Run
boundaries do not hide the previous sentence: the student refers to the dialogue
they can see.

Images sent with those utterances travel with them. Each model-facing row may
carry ``image_urls`` (authorized ``data:`` URLs). Rows never expose storage
paths, and there is no "had an image" flag standing in for the picture.
"""
from __future__ import annotations

from collections.abc import Callable

from sqlalchemy.orm import Session

from app.infrastructure.persistence.models import CompanionMessage

MAX_UTTERANCES = 8
MAX_UTTERANCE_CHARS = 2400
MAX_WINDOW_IMAGES = 8


def ward_media_prefix(ward_id: str) -> str:
    return f"ward/{ward_id}/companion/"


def select_recent_utterances(
    rows: list[dict],
    *,
    exclude_turn_id: str | None,
    max_messages: int = MAX_UTTERANCES,
    max_chars: int = MAX_UTTERANCE_CHARS,
) -> tuple[list[dict], int]:
    """Keep the newest thread originals that fit the budget.

    ``rows`` are oldest first. Each row has ``turn_id``, ``author``, ``text``
    and optional ``attachment_refs``. An utterance that is only a picture still
    counts. Returns ``(kept, omitted_count)``.
    """
    eligible = [
        row for row in rows
        if row.get("turn_id") != exclude_turn_id
        and ((row.get("text") or "").strip() or row.get("attachment_refs"))
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
            "attachment_refs": list(row.attachment_refs or []),
        }
        for row in rows
    ]
    return select_recent_utterances(projected, exclude_turn_id=exclude_turn_id)


def _default_reader(key: str) -> str:
    from app.application.commands.task_intake import _data_url

    return _data_url(key)


def visible_utterances(
    rows: list[dict],
    *,
    ward_id: str,
    read_image: Callable[[str], str] | None = None,
    strict: bool = False,
    image_budget: int = MAX_WINDOW_IMAGES,
) -> list[dict]:
    """Model-facing window: text plus the Ward's own authorized images as data URLs.

    Only keys under this Ward's media prefix are read; others are skipped. The
    newest ``image_budget`` images are kept. A picture that cannot be read
    becomes ``None`` (the model is told it is unreadable) unless ``strict``.
    """
    reader = read_image or _default_reader
    prefix = ward_media_prefix(ward_id)
    budget = image_budget
    views: list[dict | None] = [None] * len(rows)
    for index in range(len(rows) - 1, -1, -1):
        row = rows[index]
        keys = [str(key) for key in row.get("attachment_refs") or [] if str(key).startswith(prefix)]
        keep = keys[-budget:] if budget > 0 else []
        budget -= len(keep)
        urls: list[str | None] = []
        for key in keep:
            try:
                urls.append(reader(key))
            except Exception:
                if strict:
                    raise
                urls.append(None)
        view: dict = {"author": row.get("author"), "text": row.get("text") or ""}
        if row.get("leading_omitted"):
            view["leading_omitted"] = True
        if urls:
            view["image_urls"] = urls
        views[index] = view
    return [view for view in views if view is not None]


def load_visible_utterances(
    db: Session, *, ward_id: str, thread_id: str, exclude_turn_id: str | None,
    read_image: Callable[[str], str] | None = None, strict: bool = False,
) -> list[dict]:
    rows, _omitted = recent_thread_utterances(
        db, ward_id=ward_id, thread_id=thread_id, exclude_turn_id=exclude_turn_id,
    )
    return visible_utterances(rows, ward_id=ward_id, read_image=read_image, strict=strict)


def current_turn_images(
    ward_id: str, keys: list[str] | None, *, read_image: Callable[[str], str] | None = None,
) -> list[str | None]:
    """This turn's authorized images as data URLs; other Wards' keys are skipped."""
    reader = read_image or _default_reader
    prefix = ward_media_prefix(ward_id)
    urls: list[str | None] = []
    for key in keys or []:
        if not str(key).startswith(prefix):
            continue
        try:
            urls.append(reader(str(key)))
        except Exception:
            urls.append(None)
    return urls


def _chars(rows: list[dict]) -> int:
    return sum(len(row.get("text") or "") for row in rows)
