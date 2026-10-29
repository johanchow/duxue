"""Choose pictures for one tutoring turn using request-local image numbers."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass


@dataclass(frozen=True)
class ImageTarget:
    ids: tuple[int, ...]
    ambiguous: bool = False


def choose_image_target(
    window: list[dict], current_images: list[str | None],
    *, select: Callable[[list[dict]], dict] | None = None,
    compare_previous: bool = False,
) -> ImageTarget:
    """New readable pictures win; only several old pictures need semantic choice."""
    old = [url for row in window for url in (row.get("image_urls") or [])]
    current = list(current_images)
    readable_current = [len(old) + i + 1 for i, url in enumerate(current) if url]
    if readable_current:
        chosen = list(readable_current)
        if compare_previous:
            previous = next((i + 1 for i in range(len(old) - 1, -1, -1) if old[i]), None)
            if previous is not None:
                chosen.insert(0, previous)
        return ImageTarget(tuple(chosen))
    if current:
        return ImageTarget((), ambiguous=True)
    readable_old = [i + 1 for i, url in enumerate(old) if url]
    if not old:
        return ImageTarget(())
    if len(old) == 1:
        return ImageTarget(tuple(readable_old), ambiguous=not readable_old)
    if select is None:
        return ImageTarget((), ambiguous=True)
    try:
        result = select(window)
    except Exception:  # noqa: BLE001 - provider failure must not select a picture
        return ImageTarget((), ambiguous=True)
    if not isinstance(result, dict) or result.get("ambiguous"):
        return ImageTarget((), ambiguous=True)
    selected = result.get("target_image_ids")
    if not isinstance(selected, list) or any(
        type(number) is not int or number not in readable_old for number in selected
    ):
        return ImageTarget((), ambiguous=True)
    return ImageTarget(tuple(dict.fromkeys(selected)))


def keep_target_images(
    window: list[dict], current_images: list[str | None], target: ImageTarget,
) -> tuple[list[dict], list[str | None]]:
    """Keep all text but send only selected pixels to tutor and leak judge."""
    selected = set(target.ids)
    number = 0
    rows = []
    for row in window:
        view = dict(row)
        kept = []
        for url in row.get("image_urls") or []:
            number += 1
            if number in selected:
                kept.append(url)
        view.pop("image_urls", None)
        if kept:
            view["image_urls"] = kept
        rows.append(view)
    current = []
    for url in current_images:
        number += 1
        if number in selected:
            current.append(url)
    return rows, current
