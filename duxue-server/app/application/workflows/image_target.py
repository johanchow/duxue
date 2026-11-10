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
    """New readable pictures win; a selector can distinguish text from picture followups."""
    old = [url for row in window for url in (row.get("image_urls") or [])]
    current = list(current_images)
    readable_current = [len(old) + i + 1 for i, url in enumerate(current) if url]
    if current and any(not value for value in current):
        return ImageTarget((), ambiguous=True)
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
    if len(old) == 1 and select is None:
        return ImageTarget(tuple(readable_old), ambiguous=not readable_old)
    if select is None:
        return ImageTarget((), ambiguous=True)
    try:
        result = select(window)
    except Exception:  # noqa: BLE001 - provider failure must not select a picture
        return ImageTarget((), ambiguous=True)
    if (not isinstance(result, dict) or type(result.get("ambiguous")) is not bool
            or result["ambiguous"]):
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
    """Keep student evidence and selected pixels, excluding prior picture verdicts.

    Even a reply associated with the selected picture may be the incorrect reply
    the student is correcting. Association is provenance, never verification.
    """
    selected = set(target.ids)
    number = 0
    rows = []
    source_selected = True
    picture_context = False
    for row in window:
        view = dict(row)
        kept = []
        for url in row.get("image_urls") or []:
            number += 1
            if number in selected:
                kept.append(url)
        if row.get("image_urls") or row.get("had_images"):
            picture_context = True
            source_selected = bool(kept)
        if row.get("author") == "companion" and (
            not source_selected or (selected and (picture_context or row.get("image_target_refs")))
        ):
            continue
        view.pop("image_urls", None)
        view.pop("had_images", None)
        if kept:
            view["image_urls"] = kept
        rows.append(view)
    current = []
    for url in current_images:
        number += 1
        if number in selected:
            current.append(url)
    return rows, current


@dataclass(frozen=True)
class PreparedImages:
    target: ImageTarget
    window: list[dict]
    images: list[str | None]

    @property
    def refs(self) -> list[str]:
        from app.agent_specs.image_refs import image_ref
        return list(dict.fromkeys(image_ref(value) for value in [
            *(url for row in self.window for url in row.get('image_urls', [])), *self.images,
        ] if value))


def select_history_images(window: list[dict], content: str) -> dict:
    from app.agent_specs.catalog import load_catalog
    from app.agent_specs.contexts import build_context
    from app.infrastructure.ai.components import invoke_agent_component
    return invoke_agent_component(spec=load_catalog().component('tutoring', 'image_target'),
                                  user=build_context('tutoring.image-target', window=window, content=content)).unwrap()


def prepare_images(window: list[dict], images: list[str | None], *, content: str,
                   select=None, compare_previous: bool = False) -> PreparedImages:
    target = choose_image_target(window, images, compare_previous=compare_previous,
                                 select=lambda rows: (select or select_history_images)(rows, content))
    rows, current = keep_target_images(window, images, target)
    return PreparedImages(target, rows, current)
