"""Apply the shared v2 grader to measured turn outputs."""

from dataclasses import asdict
from evals.grading import evaluate


def observations(obs, latency_ms=0):
    values = asdict(obs)
    values.update(
        intent=obs.outcome,
        visual_present=obs.visual_kind is not None,
        lesson_count=len(obs.lesson_sources),
        latency_ms=latency_ms,
    )
    for key, value in (obs.exit_gate or {}).items():
        values["exit_gate." + key] = value
    return values


def grade_result(case, obs, *, judge=None, latency_ms=0, meta=None):
    return evaluate(case.grading, observations(obs, latency_ms), judge=judge, meta=meta)


def failures(result):
    return [
        f"{g.id}:{g.status}: {g.explanation or str(g.actual) + ' != ' + str(g.expected)}"
        for g in result.grades
        if g.status != "pass"
    ]


def grade(case, obs):
    return failures(grade_result(case, obs))
