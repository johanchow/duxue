"""Shared rule and message assembly for the recent-utterance window sent with a Ward turn.

Every model call that reads the conversation window receives the images in it
as vision input, not as a flag. Each utterance row may carry ``image_urls``
(already authorized data URLs). The text view only lists ``image_ids``; the
images themselves follow in the same user message as ``image_url`` parts,
numbered in the same order. Storage paths never appear in model-facing text.
"""

from __future__ import annotations

import json

WINDOW_RULE = (
    "recent_utterances 是同一条对话到上一轮为止的最近原句，从旧到新。"
    "「他们」「刚才那句」「上面那个」只能根据这些原句确定对象。"
    "对不上，或有多句都可能时，追问是哪一句，不要自己补一个对象，也不要把孩子这句中文当成待解释的外语。"
    "某句带有 image_ids 时，同编号的图片会随后附在同一条消息里，那就是这句话发出的图片，请直接看图；"
    "current_image_ids 是本轮学生发来的图片。标明无法读取的图片不要猜内容。"
)

_ROW_FIELDS = ("author", "text", "leading_omitted")


def _numbering(utterances: list[dict], current_count: int) -> tuple[list[list[int]], list[int]]:
    next_id = 1
    per_row: list[list[int]] = []
    for row in utterances:
        count = len(row.get("image_urls") or [])
        per_row.append(list(range(next_id, next_id + count)))
        next_id += count
    return per_row, list(range(next_id, next_id + current_count))


def window_text(utterances: list[dict], current_count: int = 0) -> tuple[list[dict], list[int]]:
    """Model-facing rows without image bytes or storage paths, plus this turn's image ids."""
    per_row, current_ids = _numbering(utterances, current_count)
    rows: list[dict] = []
    for row, ids in zip(utterances, per_row):
        view = {key: row[key] for key in _ROW_FIELDS if key in row}
        if ids:
            view["image_ids"] = ids
        rows.append(view)
    return rows, current_ids


def image_parts(utterances: list[dict], current_images: list[str] | None = None) -> list[dict]:
    """Numbered image parts: window images first, then this turn's images."""
    parts: list[dict] = []
    number = 0
    for url in [u for row in utterances for u in (row.get("image_urls") or [])] + list(current_images or []):
        number += 1
        if url:
            parts.append({"type": "text", "text": f"图片{number}："})
            parts.append({"type": "image_url", "image_url": {"url": url}})
        else:
            parts.append({"type": "text", "text": f"图片{number}：无法读取。"})
    return parts


def user_content(
    payload: dict, utterances: list[dict] | None = None, current_images: list[str] | None = None,
) -> list[dict]:
    """JSON text part for ``payload`` (with the text view of the window) plus image parts."""
    window = list(utterances or [])
    images = list(current_images or [])
    rows, current_ids = window_text(window, len(images))
    body = dict(payload)
    body["recent_utterances"] = rows
    if current_ids:
        body["current_image_ids"] = current_ids
    return [{"type": "text", "text": json.dumps(body, ensure_ascii=False)}, *image_parts(window, images)]


def instruction_with_window(
    instruction: str, utterances: list[dict], current_image_count: int = 0,
) -> str:
    rows, current_ids = window_text(list(utterances), current_image_count)
    text = (
        f"{instruction}\n{WINDOW_RULE}\n"
        f"recent_utterances={json.dumps(rows, ensure_ascii=False)}"
    )
    if current_ids:
        text += f"\ncurrent_image_ids={json.dumps(current_ids)}"
    return text
