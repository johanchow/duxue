"""Fixed-history replay with the same v2 scoring used by generated conversations."""

from __future__ import annotations

import time
from pathlib import Path
from collections import Counter

from app.contexts.tutoring.domain.tutor_permit import AttemptSummary, TutorPermit
from evals.conversations import GateCheck, TurnCheck, turn_case
from evals.dataset import ASSETS_DIR
from evals.grading import evaluate, unavailable
from evals.runner import (
    Backends,
    build_input,
    read_asset,
    run_sample,
    sample_json,
    unrun_sample,
)


def _scored(check, score, case_id, index, **extra):
    return {
        **score.model_dump(mode="json"),
        "case_id": case_id,
        "check_id": check.id,
        "sample_index": index,
        "passed": score.status == "pass",
        **extra,
    }


def run_conversations(
    rows, backends: Backends, *, samples=3, assets_dir: Path = ASSETS_DIR
):
    if samples < 1:
        raise ValueError("samples must be positive")
    results = []
    for row in rows:
        attempts = {a.id: a for a in row.attempts}
        checks = []
        for check in row.checks:
            observations = []
            for index in range(samples):
                if isinstance(check, GateCheck):
                    started = time.perf_counter()
                    original = attempts[check.attempt_id]
                    context = original.gate.input
                    actual = None
                    try:
                        images = [
                            read_asset(assets_dir / name) for name in context.images
                        ]
                        if backends.leak_judge is None:
                            raise ValueError("judge unavailable")
                        actual = backends.leak_judge.leaks(
                            text=context.reply,
                            task_title=context.task_title,
                            problem_summary=context.problem,
                            **({"images": images} if images else {}),
                        )
                        if (
                            not isinstance(actual, dict)
                            or type(actual.get("leaks")) is not bool
                        ):
                            raise ValueError("judge unavailable")
                        # Fixed judge checks compare its output labels, not a new tutor response.
                        score = evaluate(
                            check.grading,
                            {
                                **actual,
                                "latency_ms": round(
                                    (time.perf_counter() - started) * 1000, 1
                                ),
                            },
                        )
                    except Exception as exc:
                        score = unavailable(
                            check.grading, f"judge_error:{type(exc).__name__}"
                        )
                    observations.append(
                        _scored(
                            check,
                            score,
                            row.id,
                            index,
                            verdict=actual,
                            observed_verdict=original.gate.observed_verdict.model_dump(),
                            evidence={
                                "candidate": context.reply,
                                "input_snapshot": context.model_dump(mode="json"),
                            },
                            latency_ms=round((time.perf_counter() - started) * 1000, 1),
                        )
                    )
                else:
                    case = turn_case(row, check)
                    try:
                        window, images = build_input(case, assets_dir)
                    except (OSError, ValueError):
                        sampled = unrun_sample(
                            case, "missing_asset", sample_index=index
                        )
                    else:
                        snapshot = check.input_snapshot.permit
                        permit = TutorPermit(
                            answer_protected=snapshot.answer_protected,
                            active_subgoal=snapshot.active_subgoal,
                            attempt_summary=AttemptSummary(
                                **snapshot.attempt_summary.model_dump()
                            ),
                        )
                        sampled = run_sample(
                            case,
                            backends,
                            window,
                            images,
                            permit_override=permit,
                            sample_index=index,
                        )
                    observations.append(sample_json(sampled))
            checks.append(
                {
                    "id": check.id,
                    "component": check.component,
                    "after_message": check.after_message,
                    "grading": check.grading.model_dump(mode="json", by_alias=True),
                    "samples": observations,
                }
            )
        results.append(
            {
                "id": row.id,
                "label_status": row.label_status,
                "reviewed_by": row.reviewed_by,
                "review_batch": row.review_batch,
                "replay_mode": row.replay_mode,
                "checks": checks,
            }
        )
    return results


def summarize(results):
    samples = [s for r in results for c in r["checks"] for s in c["samples"]]
    counts = Counter(s["status"] for s in samples)
    return {
        "samples": len(samples),
        "passed": counts["pass"],
        "failed": counts["fail"],
        "errors": counts["error"],
        "not_run": counts["not_run"],
        "grading_counts": {k: counts[k] for k in ("pass", "fail", "error", "not_run")},
        "calibration_status": "uncalibrated",
        "quality_passed": None,
        "note": "语义评分未校准，不构成正式质量结论或发布门槛。",
    }


def run_image_context(rows, *, samples=1, assets_dir: Path = ASSETS_DIR, select=None):
    from app.agent_specs.image_refs import image_ref
    from app.application.workflows.image_target import prepare_images

    if samples < 1:
        raise ValueError("samples must be positive")
    results = []
    for row in rows:
        eligible = [
            c
            for c in row.checks
            if isinstance(c, TurnCheck)
            and c.grading.expectation("selected_images") is not None
        ]
        if not eligible:
            raise ValueError(f"{row.id}: image-context requires selected_images")
        checks = []
        for check in row.checks:
            observations = []
            for index in range(samples):
                if check not in eligible:
                    scoring = unavailable(
                        check.grading, "excluded_by_scope", status="not_run"
                    )
                    observations.append(_scored(check, scoring, row.id, index))
                    continue
                case = turn_case(row, check)
                try:
                    window, images = build_input(case, assets_dir)
                    prepared = prepare_images(
                        window, images, content=case.student_said, select=select
                    )
                    pairs = [
                        (name, url)
                        for utterance, view in zip(case.history, window)
                        for name, url in zip(
                            utterance.images, view.get("image_urls", [])
                        )
                    ]
                    pairs.extend(zip(case.images, images))
                    selected = list(
                        dict.fromkeys(
                            name
                            for name, url in pairs
                            if image_ref(url) in prepared.refs
                        )
                    )
                    picture_seen, prior_replies = False, []
                    for utterance in case.history:
                        picture_seen |= bool(utterance.images)
                        if utterance.author == "companion" and (
                            picture_seen or utterance.image_target_refs
                        ):
                            prior_replies.append(utterance.text)
                    # Exact source-message identity, not semantic text matching.
                    isolated = not (
                        prepared.refs
                        and any(
                            view.get("author") == "companion"
                            and view.get("text") in prior_replies
                            for view in prepared.window
                        )
                    )
                    values = {
                        "selected_images": selected,
                        "image_target_unambiguous": not prepared.target.ambiguous,
                        "history_isolated": isolated,
                    }
                    scoring = evaluate(check.grading, values, only_fields=set(values))
                    # These scope invariants belong to prepare_images, independent of response grading.
                    from evals.grading import Grade, aggregate

                    for key in ("image_target_unambiguous", "history_isolated"):
                        scoring.grades.append(
                            Grade(
                                id="scope_" + key,
                                kind="deterministic",
                                status="pass" if values[key] else "fail",
                                actual=values[key],
                                expected=True,
                            )
                        )
                    scoring.status = aggregate(g.status for g in scoring.grades)
                    observations.append(
                        _scored(
                            check,
                            scoring,
                            row.id,
                            index,
                            selected_images=selected,
                            selected_image_refs=prepared.refs,
                        )
                    )
                except Exception as exc:
                    scoring = unavailable(
                        check.grading, f"image_context_error:{type(exc).__name__}"
                    )
                    observations.append(_scored(check, scoring, row.id, index))
            checks.append(
                {
                    "id": check.id,
                    "component": check.component,
                    "samples": observations,
                    "grading": check.grading.model_dump(mode="json", by_alias=True),
                }
            )
        results.append(
            {
                "id": row.id,
                "label_status": row.label_status,
                "reviewed_by": row.reviewed_by,
                "review_batch": row.review_batch,
                "checks": checks,
                "excluded_checks": [c.id for c in row.checks if c not in eligible],
                "scope": "image-context",
            }
        )
    return results
