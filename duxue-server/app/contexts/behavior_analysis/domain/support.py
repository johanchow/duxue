"""Eligibility for semantic assessment; decisions themselves come from a model."""

from datetime import timedelta


def eligible_runs(runs, current):
    result = []
    for run in runs:
        threshold = {"still_with_material": 240, "other_visible_activity": 120}.get(
            run["activity"]
        )
        if threshold is None or run["seconds"] < threshold:
            continue
        # The last evidence sample, not the extrapolated slot end, owns freshness.
        if not timedelta(0) <= current - run["observed_at"] <= timedelta(seconds=60):
            continue
        if run is not runs[-1]:
            continue
        result.append(run)
    return result


def validate_assessment(result, frame_ids, *, has_learning_context):
    from app.contexts.behavior_analysis.domain.model_contracts import (
        SupportOpportunityResult,
    )

    parsed = SupportOpportunityResult.model_validate(result)
    if not set(parsed.evidence_refs) <= set(frame_ids):
        raise ValueError("foreign assessment evidence")
    if parsed.decision in {"offer_help", "invite_return"} and not parsed.evidence_refs:
        raise ValueError("candidate requires evidence")
    if parsed.decision == "invite_return" and not has_learning_context:
        return None
    return parsed if parsed.decision in {"offer_help", "invite_return"} else None
