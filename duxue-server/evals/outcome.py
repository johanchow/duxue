"""Turn what the production exit checks decided into a result category the grader can assert on."""

from __future__ import annotations

from dataclasses import dataclass, field

from app.application.workflows.tutor_loop import ModelCall, Vetting

_ACT_OUTCOME = {
    "answer": "answer", "probe": "hint_like", "hint": "hint_like", "example": "hint_like",
    "confirm": "confirm", "clarify": "clarify", "redirect": "redirect", "pronounce": "pronounce",
}


@dataclass(frozen=True)
class Observation:
    """One sampled result, free of any model-internal detail the Ward would not see."""

    outcome: str
    act: str | None = None
    reason: str | None = None
    content: str | None = None
    lesson_source: str | None = None
    candidates: list[str] = field(default_factory=list)
    error: str | None = None


def classify(call: ModelCall, vetting: Vetting | None) -> Observation:
    """``fallback`` means the Ward would be shown FALLBACK_TEXT; ``reason`` says which check fired."""
    candidate = call.candidate
    if candidate is None:
        return Observation("fallback", reason=call.failure or "no_candidate")
    base = {
        "act": candidate.act, "content": candidate.content,
        "lesson_source": candidate.lesson.source_text if candidate.lesson else None,
        "candidates": list(candidate.candidates),
    }
    if vetting is not None and vetting.failure is not None:
        return Observation("fallback", reason=vetting.failure, **base)
    if candidate.question_kind == "safety":
        return Observation("blocked", **base)
    return Observation(_ACT_OUTCOME[candidate.act], **base)
