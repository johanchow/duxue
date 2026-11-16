"""Count execution failures and repeated samples without hiding denominators."""

import math
from collections import Counter, defaultdict

OUTCOME_KEYS = (
    "ok",
    "stop_wire_gap",
    "length_truncated",
    "incomplete_stream",
    "non_stop_finish",
    "api_error",
    "json_parse_error",
    "contract_error",
)


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

    llm_calls = [call for c in checks for call in (c.get("llm_calls") or [])]
    finish_counts = Counter(
        str(call.get("finish_reason") or "none") for call in llm_calls
    )
    outcome_counts = Counter(str(call.get("outcome") or "unknown") for call in llm_calls)
    abrupt_details = Counter(
        str(call["abrupt_detail"])
        for call in llm_calls
        if call.get("abrupt_detail")
    )
    stop_valid_json_failed_checks = sum(
        1
        for c in checks
        if c.get("status") == "fail"
        and c.get("outcome") not in {"fallback", None}
        and bool(c.get("llm_calls"))
        and c["llm_calls"][-1].get("finish_reason") == "stop"
        and c["llm_calls"][-1].get("outcome") in {"ok", "stop_wire_gap"}
    )
    result["llm_completions"] = {
        "total_calls": len(llm_calls),
        "stream_completed": sum(
            1 for call in llm_calls if call.get("stream_completed") is True
        ),
        "stream_incomplete": sum(
            1 for call in llm_calls if call.get("stream_completed") is not True
        ),
        "by_finish_reason": dict(sorted(finish_counts.items())),
        "by_outcome": {
            **{k: outcome_counts.get(k, 0) for k in OUTCOME_KEYS},
            **{
                k: v
                for k, v in sorted(outcome_counts.items())
                if k not in OUTCOME_KEYS
            },
        },
        "stop_valid_json_failed_checks": stop_valid_json_failed_checks,
        "abrupt_details": dict(sorted(abrupt_details.items())),
        "tokens": {
            "input": sum(int(call.get("tokens_in") or 0) for call in llm_calls),
            "output": sum(int(call.get("tokens_out") or 0) for call in llm_calls),
            "answer": sum(int(call.get("tokens_answer") or 0) for call in llm_calls),
            "reasoning": sum(
                int(call.get("tokens_reasoning") or 0) for call in llm_calls
            ),
        },
    }
    return result
