"""Replay real conversations without rewriting historical messages or semantic labels."""
from __future__ import annotations

import time
from dataclasses import asdict

from app.contexts.tutoring.domain.tutor_permit import AttemptSummary, TutorPermit
from app.application.workflows.tutor_turn import FALLBACK_TEXT
from evals.conversations import GateCheck, turn_case
from evals.runner import Backends, build_input, run_sample
from evals.dataset import ASSETS_DIR


def verdict_failures(actual, expected):
    if not isinstance(actual, dict) or type(actual.get("leaks")) is not bool:
        return ["judge_unavailable"]
    failures = []
    if actual["leaks"] != expected.leaks:
        failures.append("leaks_mismatch")
    if actual.get("reason") != expected.reason:
        failures.append("reason_mismatch")
    return failures


class RecordingJudge:
    def __init__(self, delegate):
        self.delegate = delegate
        self.calls = []

    def leaks(self, **kwargs):
        result = self.delegate.leaks(**kwargs)
        self.calls.append({"input": kwargs, "verdict": result})
        return result

    def visual_leaks(self, **kwargs):
        return self.delegate.visual_leaks(**kwargs)


def run_conversations(rows, backends: Backends, *, samples: int = 3):
    if samples < 1:
        raise ValueError("samples must be positive")
    if backends.leak_judge is None:
        raise ValueError("conversation replay requires an explicit judge")
    results = []
    for row in rows:
        attempts = {a.id: a for a in row.attempts}
        checks = []
        for check in row.checks:
            observations = []
            for _ in range(samples):
                started = time.perf_counter()
                if isinstance(check, GateCheck):
                    original = attempts[check.attempt_id]
                    gate_input = original.gate.input
                    try:
                        actual = backends.leak_judge.leaks(
                            text=gate_input.reply, task_title=gate_input.task_title,
                            problem_summary=gate_input.problem,
                        )
                        failures = verdict_failures(actual, check.expect)
                        error = None
                    except Exception as exc:  # A failed call is never a successful verdict.
                        actual, failures, error = None, ["judge_unavailable"], type(exc).__name__
                    observations.append({
                        "verdict": actual, "observed_verdict": original.gate.observed_verdict.model_dump(),
                        "failures": failures, "passed": not failures,
                        "semantic_status": "label_comparison", "error": error,
                        "latency_ms": round((time.perf_counter() - started) * 1000, 1),
                    })
                else:
                    case = turn_case(row, check)
                    window, images = build_input(case, ASSETS_DIR)
                    recording = RecordingJudge(backends.leak_judge)
                    snapshot = check.input_snapshot.permit
                    permit = TutorPermit(
                        answer_protected=snapshot.answer_protected, active_subgoal=snapshot.active_subgoal,
                        attempt_summary=AttemptSummary(**snapshot.attempt_summary.model_dump()),
                    )
                    try:
                        sampled = run_sample(case, Backends(
                            tutor_model=backends.tutor_model, backup_model=backends.backup_model,
                            leak_judge=recording,
                        ), window, images, permit_override=permit)
                        actual = recording.calls[-1]["verdict"] if recording.calls else None
                        failures = sampled.failures + verdict_failures(actual, check.expect.exit_gate)
                        observation = asdict(sampled.observation)
                        displayed = FALLBACK_TEXT if sampled.observation.outcome == "fallback" else sampled.observation.content
                        error = None
                    except Exception as exc:
                        observation, displayed, actual = None, None, None
                        failures, error = ["replay_error"], type(exc).__name__
                    observations.append({
                        "response": {"message": displayed}, "observation": observation,
                        "exit_gate": actual, "gate_calls": recording.calls,
                        "failures": failures, "structural_passed": not failures,
                        "semantic_status": "pending_review", "passed": False if failures else None,
                        "error": error, "latency_ms": round((time.perf_counter() - started) * 1000, 1),
                    })
            checks.append({"id": check.id, "component": check.component, "after_message": check.after_message,
                           "expect": check.expect.model_dump(), "samples": observations})
        results.append({"id": row.id, "label_status": row.label_status, "replay_mode": row.replay_mode,
                        "checks": checks})
    return results


def summarize(results):
    samples = [s for r in results for c in r["checks"] for s in c["samples"]]
    return {"samples": len(samples), "passed": sum(s["passed"] is True for s in samples),
            "failed": sum(s["passed"] is False for s in samples),
            "pending_review": sum(s["passed"] is None for s in samples),
            "note": "主回复语义需人工复核；结构通过不等于满足参考回复和 criteria。"}
