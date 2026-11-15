"""Count execution failures and repeated samples without hiding denominators."""

import math
from collections import Counter, defaultdict


def _percentile(sorted_values: list[float], p: float) -> float | None:
    if not sorted_values:
        return None
    rank = max(
        0, min(len(sorted_values) - 1, math.ceil((p / 100.0) * len(sorted_values)) - 1)
    )
    return round(sorted_values[rank], 1)


def summarize(rows):
    def counts(items):
        c = Counter(r["status"] for r in items)
        return {
            "total": len(items),
            **{s: c[s] for s in ("pass", "fail", "error", "not_run")},
        }

    families = defaultdict(list)
    for row in rows:
        families[row["case_id"]].append(row)
    result = {
        "calibration_status": "uncalibrated",
        "quality_passed": None,
        "samples": counts(rows),
        "tasks": {
            "total": len(families),
            "all_samples_passed": sum(
                all(r["status"] == "pass" for r in samples)
                for samples in families.values()
            ),
        },
    }
    for key in ("subject", "level", "dataset", "execution_target", "split"):
        groups = defaultdict(list)
        for row in rows:
            groups[row.get(key, "unknown")].append(row)
        result["by_" + key] = {
            name: counts(items) for name, items in sorted(groups.items())
        }
    checks = [c for row in rows for c in row.get("checks", [])]
    result["checkpoints"] = counts(checks)

    latencies = sorted(
        float(c["latency_ms"])
        for c in checks
        if c.get("status") != "not_run"
        and isinstance(c.get("latency_ms"), (int, float))
    )
    result["latency_ms"] = {
        "count": len(latencies),
        "mean": round(sum(latencies) / len(latencies), 1) if latencies else None,
        "p50": _percentile(latencies, 50),
        "p90": _percentile(latencies, 90),
        "max": round(latencies[-1], 1) if latencies else None,
    }

    tutoring_checks = [
        c
        for r in rows
        if r.get("execution_target") == "tutoring"
        for c in r.get("checks", [])
        if c.get("status") != "not_run"
    ]
    retried = sum(bool(c.get("leak_retried")) for c in tutoring_checks)
    fallback_reasons = Counter(
        str(c.get("reason") or "unknown")
        for c in tutoring_checks
        if c.get("outcome") == "fallback"
    )
    result["tutoring_diagnostics"] = {
        "evaluated_checkpoints": len(tutoring_checks),
        "leak_retried": retried,
        "leak_retry_rate": round(retried / len(tutoring_checks), 4)
        if tutoring_checks
        else None,
        "fallbacks": sum(fallback_reasons.values()),
        "fallback_reasons": dict(sorted(fallback_reasons.items())),
    }
    return result
