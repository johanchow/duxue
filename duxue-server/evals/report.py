"""Metrics in three tiers, and honest uncertainty.

Offline evaluation here is a smoke test, not a hill-climbing target. The datasets are
small and were chosen because they once failed, so a pass rate is not a production
accuracy and a gain inside the interval is not a gain.
"""

from __future__ import annotations

import math
from collections import Counter

from evals.runner import CaseResult

WIDE_INTERVAL = 0.2


def wilson(k: int, n: int, z: float = 1.96) -> tuple[float, float]:
    if n == 0:
        return 0.0, 1.0
    p = k / n
    denom = 1 + z * z / n
    centre = (p + z * z / (2 * n)) / denom
    half = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / denom
    return max(0.0, centre - half), min(1.0, centre + half)


def _rate(k: int, n: int) -> dict:
    low, high = wilson(k, n)
    return {"k": k, "n": n, "rate": round(k / n, 3) if n else None, "ci95": [round(low, 3), round(high, 3)],
            "wide": (high - low) > WIDE_INTERVAL}


def _percentile(values: list[float], q: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    return round(ordered[min(len(ordered) - 1, int(q * len(ordered)))], 1)


def _group(results: list[CaseResult]) -> dict:
    """Pooled sample pass rate plus case-level stability. Samples of one case are correlated,
    so the case-level counts are the ones to trust; the pooled interval is optimistic."""
    ran = [r for r in results if r.status == "ran" and r.samples]
    stable = sum(all(s.passed for s in r.samples) for r in ran)
    failing = sum(not any(s.passed for s in r.samples) for r in ran)
    return {
        "cases": len(ran),
        "samples": _rate(sum(s.passed for r in ran for s in r.samples), sum(len(r.samples) for r in ran)),
        "cases_stable_pass": _rate(stable, len(ran)),
        "cases_flaky": len(ran) - stable - failing,
        "cases_always_fail": failing,
    }


def _expression(ran: list[CaseResult]) -> dict:
    """Shape and diagram metrics. Deterministic, observation only: none of them gates a release.

    Over samples whose words were shown (a fallback replaces the words, so it has no shape to judge).
    """
    shown = [
        (r, s) for r in ran if r.case.component == "tutoring.turn" for s in r.samples
        if s.observation.outcome != "fallback" and s.observation.content
    ]
    lengths = [len(s.observation.content) for _, s in shown]
    flagged = [s for _, s in shown if s.observation.shape_flags]
    with_visual = [s for _, s in shown if s.observation.visual_kind]
    dropped = [s for _, s in shown if s.observation.visual_dropped]
    wanted = [s for r, s in shown if r.case.expect.visual == "present"]
    unwanted = [s for r, s in shown if r.case.expect.visual == "absent"]
    return {
        "content_chars_p50": _percentile([float(n) for n in lengths], 0.5),
        "content_chars_p95": _percentile([float(n) for n in lengths], 0.95),
        "shape_lint": {
            "rate": _rate(len(flagged), len(shown)),
            "flags": dict(Counter(f for s in flagged for f in s.observation.shape_flags).most_common()),
        },
        "visual": {
            "shown": _rate(len(with_visual), len(shown)),
            "dropped_reasons": dict(Counter(s.observation.visual_dropped for s in dropped).most_common()),
            # Of the diagrams the model proposed, how many survived the exit checks.
            "structure_pass": _rate(len(with_visual), len(with_visual) + len(dropped)),
            "recall": _rate(sum(1 for s in wanted if s.observation.visual_kind), len(wanted)),
            "false_positive": _rate(sum(1 for s in unwanted if s.observation.visual_kind), len(unwanted)),
            "latency_ms_p50_with": _percentile([s.latency_ms for s in with_visual], 0.5),
            "latency_ms_p50_without": _percentile(
                [s.latency_ms for _, s in shown if not s.observation.visual_kind], 0.5,
            ),
        },
    }


def summarize(results: list[CaseResult]) -> dict:
    """Primary: confirmed cases (gating). ``proposed`` is reported apart until a human confirms it.
    Guardrail: fallback rate over every ran sample. Secondary: latency."""
    gradable = {
        status: [r for r in results if r.case.label_status == status]
        for status in ("confirmed", "proposed")
    }
    summary: dict = {"primary": {}, "guardrail": {}, "secondary": {}, "notes": []}
    for status, group in gradable.items():
        by_tag: dict[str, list[CaseResult]] = {}
        for result in group:
            for tag in result.case.tags:
                by_tag.setdefault(tag, []).append(result)
        summary["primary"][status] = {"overall": _group(group), "by_tag": {t: _group(g) for t, g in sorted(by_tag.items())}}

    ran = [r for r in results if r.status == "ran"]
    samples = [s for r in ran for s in r.samples]
    tutor_samples = [s for r in ran if r.case.component == "tutoring.turn" for s in r.samples]
    fallbacks = [s for s in tutor_samples if s.observation.outcome == "fallback"]
    summary["guardrail"] = {
        "fallback_rate": _rate(len(fallbacks), len(tutor_samples)),
        "fallback_reasons": dict(Counter(s.observation.reason or "unknown" for s in fallbacks).most_common()),
        "provider_errors": sum(1 for s in samples if s.observation.error),
        "leak_retries": sum(1 for s in tutor_samples if s.observation.leak_retried),
    }
    summary["secondary"] = {
        "latency_ms_p50": _percentile([s.latency_ms for s in samples], 0.5),
        "latency_ms_p95": _percentile([s.latency_ms for s in samples], 0.95),
        **_expression(ran),
    }
    summary["outcomes"] = {
        r.case.id: dict(Counter(s.observation.outcome for s in r.samples).most_common()) for r in ran
    }
    summary["skipped"] = {r.case.id: r.skip_reason for r in results if r.status == "skipped"}

    confirmed = summary["primary"]["confirmed"]["overall"]["cases_stable_pass"]
    if confirmed["n"] and confirmed["wide"]:
        summary["notes"].append(
            f"confirmed 集仅 {confirmed['n']} 例，95% 区间宽于 {WIDE_INTERVAL}：只能当冒烟，不能据此宣称提升。"
        )
    if not confirmed["n"]:
        summary["notes"].append("没有 confirmed 的 case：本次结果不构成任何门槛。")
    if summary["primary"]["proposed"]["overall"]["cases"]:
        summary["notes"].append("proposed 为待人工复核的标注，不得作为通过依据。")
    return summary


def to_json(results: list[CaseResult]) -> list[dict]:
    return [
        {
            "id": r.case.id, "component": r.case.component, "label_status": r.case.label_status,
            "tags": r.case.tags, "status": r.status, "skip_reason": r.skip_reason,
            "samples": [
                {"outcome": s.observation.outcome, "act": s.observation.act, "reason": s.observation.reason,
                 "error": s.observation.error, "passed": s.passed, "failures": s.failures,
                 "latency_ms": s.latency_ms, "content": s.observation.content,
                 "visual_kind": s.observation.visual_kind, "visual_text": s.observation.visual_text,
                 "visual_dropped": s.observation.visual_dropped, "shape_flags": s.observation.shape_flags,
                 "leak_retried": s.observation.leak_retried,
                 "lesson_source": s.observation.lesson_source, "candidates": s.observation.candidates}
                for s in r.samples
            ],
        }
        for r in results
    ]


def _fmt(rate: dict) -> str:
    if rate["n"] == 0:
        return "-"
    return f"{rate['k']}/{rate['n']} = {rate['rate']:.0%}  (95% CI {rate['ci95'][0]:.0%}-{rate['ci95'][1]:.0%})"


def render_text(meta: dict, summary: dict, results: list[CaseResult]) -> str:
    lines = [
        f"== {meta['component']}@{meta['component_version']}  model={meta['model']}  variant={meta['variant']}  "
        f"K={meta['samples']}  dataset={meta['dataset_hash']}  git={meta['git_sha']}",
    ]
    for status in ("confirmed", "proposed"):
        block = summary["primary"][status]
        overall = block["overall"]
        if not overall["cases"]:
            continue
        lines.append(f"-- primary [{status}]  {overall['cases']} cases")
        lines.append(f"   samples passed        {_fmt(overall['samples'])}")
        lines.append(f"   cases always passing  {_fmt(overall['cases_stable_pass'])}   "
                     f"flaky={overall['cases_flaky']}  always-fail={overall['cases_always_fail']}")
        for tag, group in block["by_tag"].items():
            lines.append(f"   tag {tag:<18}{group['cases']:>3} cases  stable {group['cases_stable_pass']['k']}/{group['cases_stable_pass']['n']}"
                         f"  flaky={group['cases_flaky']}  fail={group['cases_always_fail']}")
    guard = summary["guardrail"]
    lines.append(f"-- guardrail  fallback rate {_fmt(guard['fallback_rate'])}  reasons={guard['fallback_reasons']}  "
                 f"provider_errors={guard['provider_errors']}  leak_retries={guard['leak_retries']}")
    lines.append(f"-- latency    p50={summary['secondary']['latency_ms_p50']}ms  p95={summary['secondary']['latency_ms_p95']}ms")
    sec = summary["secondary"]
    if "visual" in sec and sec["visual"]["shown"]["n"]:
        vis = sec["visual"]
        lines.append(f"-- shape      content p50={sec['content_chars_p50']} p95={sec['content_chars_p95']} chars  "
                     f"lint {_fmt(sec['shape_lint']['rate'])}  flags={sec['shape_lint']['flags']}")
        lines.append(f"-- visual     shown {_fmt(vis['shown'])}  structure-pass {_fmt(vis['structure_pass'])}  "
                     f"dropped={vis['dropped_reasons']}")
        lines.append(f"              recall {_fmt(vis['recall'])}  false-positive {_fmt(vis['false_positive'])}  "
                     f"latency p50 with={vis['latency_ms_p50_with']}ms without={vis['latency_ms_p50_without']}ms")
    failing = [r for r in results if r.status == "ran" and r.samples and not all(s.passed for s in r.samples)]
    if failing:
        lines.append("-- cases with failures")
        for r in failing:
            passed = sum(s.passed for s in r.samples)
            first = next(s.failures[0] for s in r.samples if s.failures)
            lines.append(f"   {r.case.id:<34}{passed}/{len(r.samples)} [{r.case.label_status}]  {first}")
    for case_id, reason in summary["skipped"].items():
        lines.append(f"-- skipped {case_id}: {reason}")
    lines.extend(f"!! {note}" for note in summary["notes"])
    return "\n".join(lines)
