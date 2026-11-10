"""Turn what the production exit checks decided into a result category the grader can assert on."""

from __future__ import annotations

from dataclasses import dataclass, field

from app.application.workflows.tutor_loop import ModelCall, Vetting
from app.application.workflows.tutor_turn import fallback_text
from app.application.workflows.tutor_visual import describe

_ACT_OUTCOME = {
    "answer": "answer",
    "guide": "hint_like",
    "chat": "chat",
    "clarify": "clarify",
    "redirect": "redirect",
    "pronounce": "pronounce",
}


@dataclass(frozen=True)
class Observation:
    """One sampled result, free of any model-internal detail the Ward would not see."""

    outcome: str | None
    tool_calls: list[dict] | None = None
    exit_gate: dict | None = None
    visual_payload: dict | None = None
    delivered_lessons: list[dict] = field(default_factory=list)
    selected_images: list[str] = field(default_factory=list)
    selected_image_refs: list[str] = field(default_factory=list)
    review_conclusion: str | None = None
    image_review: dict | None = None
    act: str | None = None
    reason: str | None = None
    content: str | None = None
    delivered_content: str | None = None
    lesson_source: str | None = None
    lesson_sources: list[str] = field(default_factory=list)
    candidates: list[str] = field(default_factory=list)
    error: str | None = None
    # 孩子最终看到的图（通过全部检查）；被丢弃时只有原因。形状 lint 只是观测。
    visual_kind: str | None = None
    visual_text: str | None = None
    visual_dropped: str | None = None
    shape_flags: list[str] = field(default_factory=list)
    # 第一版说出了答案、已重试一次改成提示（最终结果仍以 outcome 为准）。
    leak_retried: bool = False
    # Scope approved by the production independent review; not the injected permit.
    answer_protected: bool | None = None


def classify(
    call: ModelCall, vetting: Vetting | None, *, leak_retried: bool = False
) -> Observation:
    """``fallback`` means the Ward would be shown FALLBACK_TEXT; ``reason`` says which check fired."""
    candidate = call.candidate
    if candidate is None:
        return Observation(
            "fallback",
            reason=call.failure or "no_candidate",
            delivered_content=fallback_text(call.failure),
            leak_retried=leak_retried,
        )
    base = {
        "leak_retried": leak_retried,
        "answer_protected": vetting.verdict.answer_protected
        if vetting and vetting.verdict
        else None,
        "act": candidate.act,
        "content": candidate.content,
        "review_conclusion": candidate.image_review.conclusion
        if candidate.image_review
        else None,
        "image_review": candidate.image_review.model_dump(mode="json")
        if candidate.image_review
        else None,
        "lesson_source": " ".join(item.source_text for item in candidate.lessons)
        if candidate.lessons
        else None,
        "lesson_sources": [item.source_text for item in candidate.lessons],
        "candidates": list(candidate.candidates),
    }
    flags = list(vetting.shape_flags) if vetting is not None else []
    if vetting is not None and vetting.failure is not None:
        return Observation(
            "fallback",
            reason=vetting.failure,
            delivered_content=fallback_text(vetting.failure, vetting.leak_reason),
            shape_flags=flags,
            **base,
        )
    if candidate.act == "safety":
        from app.application.workflows.tutor_turn import SAFE_TEXT

        return Observation("blocked", delivered_content=SAFE_TEXT, **base)
    visual = vetting.visual if vetting is not None else candidate.visual
    dropped = (
        vetting.visual_dropped if vetting is not None else candidate.visual_dropped
    )
    return Observation(
        _ACT_OUTCOME[candidate.act],
        delivered_content=candidate.content,
        delivered_lessons=[item.model_dump(mode="json") for item in candidate.lessons],
        visual_payload=visual.model_dump(mode="json") if visual else None,
        visual_kind=visual.kind if visual else None,
        visual_text=describe(visual) if visual else None,
        visual_dropped=dropped,
        shape_flags=flags,
        **base,
    )
