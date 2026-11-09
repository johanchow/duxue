"""Shared rule and message assembly for the recent-utterance window sent with a Ward turn.

Every model call that reads the conversation window receives the images in it
as vision input, not as a flag. Each utterance row may carry ``image_urls``
(already authorized data URLs). The text view only lists ``image_ids``; the
images themselves follow in the same user message as ``image_url`` parts,
numbered in the same order. Storage paths never appear in model-facing text.
"""

from __future__ import annotations

import json

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
