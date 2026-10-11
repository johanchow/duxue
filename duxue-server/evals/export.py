"""Turn a real conversation into reviewable dataset candidates.

Follows the dataset recipe in the Khanmigo paper: take real conversations, flag the ones
that went wrong automatically, and let a person decide what is right before anything is
kept. Nothing exported here is trusted: ``expect`` is left open and ``label_status`` is
``proposed`` until a human edits and confirms it.
"""

from __future__ import annotations

import hashlib
import re
from collections.abc import Callable
from pathlib import Path

from app.application.process_managers.companion_coordinator import _CLARIFY_REPLY
from app.application.queries.run_transcript import select_recent_utterances
from app.application.workflows.tutor_turn import FALLBACK_TEXT, REMINDER
from evals.dataset import ASSETS_DIR, scrub
from evals.schema import Context, EvalCase, Utterance

_NUMBERED_LIST = re.compile(r"\n1\. ")
_IMAGE_SUFFIXES = {".jpg", ".jpeg", ".png", ".webp"}


def _norm(text: str) -> str:
    return "".join(text.split())


def _flags(rows: list[dict], index: int) -> list[str]:
    """Automatic markers of "this decision point went badly". A person confirms them."""
    flags: list[str] = []
    reply = None
    for later in rows[index + 1:]:
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
    if said and any(_norm(r.get("text") or "") == said for r in rows[:index] if r["author"] == "ward"):
        flags.append("ward_repeat")
    return flags


def build_cases(
    rows: list[dict], *, conversation_id: str, component: str, asset_for: Callable[[str], str],
    names: tuple[str, ...] = (),
) -> list[EvalCase]:
    """``rows`` are the thread's messages, oldest first (``author``, ``text``, ``attachment_refs``)."""
    short = "intent" if component == "companion.intent" else "turn"
    # select_recent_utterances drops rows whose turn_id equals the excluded one (None here).
    rows = [{**row, "turn_id": row.get("turn_id") or f"row-{i}"} for i, row in enumerate(rows)]
    # The reminder is appended only while a task is running, so any occurrence in the thread
    # tells us the Ward had an active task around these turns.
    task_active = any(REMINDER in (r.get("text") or "") for r in rows if r["author"] == "companion")
    cases: list[EvalCase] = []
    ordinal = 0
    for index, row in enumerate(rows):
        if row["author"] != "ward":
            continue
        position, ordinal = ordinal, ordinal + 1
        text = scrub((row.get("text") or "").strip(), names)
        if not text:
            continue  # a picture with no words has no sentence to replay
        prior, _omitted = select_recent_utterances(rows[:index], exclude_turn_id=None)
        history = [
            Utterance(
                author=item["author"], text=scrub(item.get("text") or "", names),
                images=[asset_for(key) for key in item.get("attachment_refs") or []],
            )
            for item in prior
        ]
        cases.append(EvalCase(
            id=f"{short}-{conversation_id}-{position:02d}", component=component,  # type: ignore[arg-type]
            conversation_id=conversation_id, turn_index=position, history=history, student_said=text,
            images=[asset_for(key) for key in row.get("attachment_refs") or []],
            context=Context(task_active=task_active) if component == "tutoring.turn" else Context(),
            source="real", flags=_flags(rows, index), label_status="proposed",
            note="自动导出：补全 expect 与 tags，人工复核后再设 confirmed。context 无法从对话还原的部分（题目状态等）需手工补。",
        ))
    return cases


def asset_writer(read_bytes: Callable[[str], bytes], assets_dir: Path | None = None) -> Callable[[str], str]:
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
        str(value) for (value,) in db.query(CompanionMessage.thread_id)
        .filter(cast(CompanionMessage.thread_id, String).like(f"{thread_prefix}%")).distinct().all()
    }
    if len(ids) != 1:
        raise ValueError(f"thread prefix {thread_prefix!r} matches {len(ids)} threads; need exactly one")
    thread_id = ids.pop()
    messages = (
        db.query(CompanionMessage).filter(CompanionMessage.thread_id == thread_id)
        .order_by(CompanionMessage.thread_version).all()
    )
    rows = [
        {"turn_id": m.turn_id, "author": m.author_type, "text": m.content,
         "attachment_refs": list(m.attachment_refs or [])}
        for m in messages
    ]
    return thread_id[:8], rows
