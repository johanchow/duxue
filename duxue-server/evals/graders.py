"""Deterministic assertions. No LLM judge: its FP/FN rate would have to be calibrated first."""

from __future__ import annotations

from evals.outcome import Observation
from evals.schema import EvalCase


def _contains_any(text: str | None, needles: list[str]) -> bool:
    haystack = " ".join((text or "").lower().split())
    return any(" ".join(needle.lower().split()) in haystack for needle in needles)


def grade(case: EvalCase, obs: Observation) -> list[str]:
    """Failure reasons; an empty list means the sample passed."""
    expect = case.expect
    failures: list[str] = []
    if case.component == "companion.intent":
        if obs.error:
            failures.append(f"provider_error:{obs.error}")
        if expect.intent_in and obs.outcome not in expect.intent_in:
            failures.append(f"intent:{obs.outcome} not in {expect.intent_in}")
        return failures

    if expect.outcome_in and obs.outcome not in expect.outcome_in:
        failures.append(f"outcome:{obs.outcome}{f'({obs.reason})' if obs.reason else ''} not in {expect.outcome_in}")
    elif obs.outcome in expect.outcome_not_in:
        failures.append(f"outcome:{obs.outcome}{f'({obs.reason})' if obs.reason else ''} is forbidden")
    haystack_lessons = " ".join(obs.lesson_sources) if obs.lesson_sources else obs.lesson_source
    if expect.lesson_source_contains_any and not _contains_any(haystack_lessons, expect.lesson_source_contains_any):
        failures.append(f"lesson_source {haystack_lessons!r} lacks any of {expect.lesson_source_contains_any}")
    if expect.lesson_source_contains_all:
        missing = [needle for needle in expect.lesson_source_contains_all if not _contains_any(haystack_lessons, [needle])]
        if missing:
            failures.append(f"lesson_source {haystack_lessons!r} lacks {missing}")
    lesson_count = len(obs.lesson_sources) or (1 if obs.lesson_source else 0)
    if expect.min_lessons is not None and lesson_count < expect.min_lessons:
        failures.append(f"lessons: expected >={expect.min_lessons}, got {lesson_count}")
    if expect.content_contains_any and not _contains_any(obs.content, expect.content_contains_any):
        failures.append(f"content lacks any of {expect.content_contains_any}")
    if expect.content_not_contains and _contains_any(obs.content, expect.content_not_contains):
        failures.append(f"content contains forbidden text from {expect.content_not_contains}")
    if expect.visual == "present" and obs.visual_kind is None:
        failures.append(f"visual: expected a diagram, got none{f' (dropped: {obs.visual_dropped})' if obs.visual_dropped else ''}")
    if expect.visual == "absent" and obs.visual_kind is not None:
        failures.append(f"visual: expected no diagram, got {obs.visual_kind}")
    if expect.visual_kind_in and obs.visual_kind not in expect.visual_kind_in:
        failures.append(f"visual_kind:{obs.visual_kind} not in {expect.visual_kind_in}")
    if expect.visual_not_contains and _contains_any(obs.visual_text, expect.visual_not_contains):
        failures.append(f"visual contains forbidden text from {expect.visual_not_contains}")
    return failures
