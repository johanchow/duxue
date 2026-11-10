"""Replay real conversations without rewriting historical messages or semantic labels."""
from __future__ import annotations

import time
from dataclasses import asdict
from pathlib import Path

from app.application.workflows.tutor_turn import FALLBACK_TEXT
from app.contexts.tutoring.domain.tutor_permit import AttemptSummary, TutorPermit

from evals.conversations import GateCheck, turn_case
from evals.dataset import ASSETS_DIR
from evals.runner import Backends, build_input, read_asset, run_sample


def verdict_failures(actual, expected):
    if not isinstance(actual, dict) or type(actual.get("leaks")) is not bool:
        return ["judge_unavailable"]
    failures = []
    if actual["leaks"] != expected.leaks:
        failures.append("leaks_mismatch")
    reasons = getattr(expected, "reason_in", None) or [expected.reason]
    if actual.get("reason") not in reasons:
        failures.append("reason_mismatch")
    if expected.answer_protected is not None and actual.get("answer_protected") is not expected.answer_protected:
        failures.append("scope_mismatch")
    return failures


class RecordingJudge:
    def __init__(self, delegate):
        self.delegate = delegate
        self.calls = []

    def leaks(self, **kwargs):
        result = self.delegate.leaks(**kwargs)
        from app.agent_specs.image_refs import image_ref
        recorded = {key: value for key, value in kwargs.items() if key != "images"}
        if kwargs.get("images"):
            recorded["image_refs"] = [image_ref(value) for value in kwargs["images"]]
        self.calls.append({"input": recorded, "verdict": result})
        return result

    def check_math(self, **kwargs):
        check = getattr(self.delegate, "check_math", None)
        return check(**kwargs) if check else None

    def visual_leaks(self, **kwargs):
        return self.delegate.visual_leaks(**kwargs)


def run_conversations(rows, backends: Backends, *, samples: int = 3, assets_dir: Path = ASSETS_DIR):
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
                index = next(i for i, message in enumerate(row.messages) if message.id == check.after_message)
                names = (attempts[check.attempt_id].gate.input.images if isinstance(check, GateCheck)
                         else [name for message in row.messages[max(0, index - 8):index + 1] for name in message.images])
                missing = [name for name in names if not (assets_dir / name).is_file()]
                if missing:
                    observations.append({'failures': ['missing_asset:' + name for name in missing],
                                         'passed': False, 'semantic_status': 'missing_assets', 'status': 'skipped'})
                    continue
                if isinstance(check, GateCheck):
                    original = attempts[check.attempt_id]
                    gate_input = original.gate.input
                    try:
                        actual = backends.leak_judge.leaks(
                            text=gate_input.reply, task_title=gate_input.task_title,
                            problem_summary=gate_input.problem,
                            **({"images": [read_asset(assets_dir / name) for name in gate_input.images]} if gate_input.images else {}),
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
                    window, images = build_input(case, assets_dir)
                    recording = RecordingJudge(backends.leak_judge)
                    snapshot = check.input_snapshot.permit
                    permit = TutorPermit(
                        answer_protected=snapshot.answer_protected, active_subgoal=snapshot.active_subgoal,
                        attempt_summary=AttemptSummary(**snapshot.attempt_summary.model_dump()),
                    )
                    try:
                        sampled = run_sample(case, Backends(
                            tutor_model=backends.tutor_model, backup_model=backends.backup_model,
                            leak_judge=recording, image_target_selector=backends.image_target_selector,
                        ), window, images, permit_override=permit)
                        actual = recording.calls[-1]["verdict"] if recording.calls else None
                        failures = sampled.failures + verdict_failures(actual, check.expect.exit_gate)
                        observation = asdict(sampled.observation)
                        displayed = sampled.observation.delivered_content or sampled.observation.content or FALLBACK_TEXT
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


def run_image_context(rows, *, samples=1, assets_dir: Path = ASSETS_DIR, select=None):
    """Replay only production image preparation; do not claim tutor/Judge success."""
    from app.agent_specs.image_refs import image_ref
    from app.application.workflows.image_target import prepare_images
    from evals.conversations import TurnCheck

    if samples < 1:
        raise ValueError('samples must be positive')
    results = []
    for row in rows:
        checks = []
        eligible = [c for c in row.checks if isinstance(c, TurnCheck) and c.expect.selected_images is not None]
        if not eligible:
            raise ValueError(f'{row.id}: image-context scope requires selected_images expectations')
        for check in eligible:
            case = turn_case(row, check)
            observations = []
            for _ in range(samples):
                failures, selected, refs, history = [], [], [], []
                missing = [name for name in case.asset_names if not (assets_dir / name).is_file()]
                if missing:
                    failures = ['missing_asset:' + name for name in missing]
                else:
                    try:
                        window, images = build_input(case, assets_dir)
                        prepared = prepare_images(window, images, content=case.student_said, select=select)
                        refs, history = prepared.refs, prepared.window
                        pairs = [(name, url) for utterance, view in zip(case.history, window)
                                 for name, url in zip(utterance.images, view.get('image_urls', []))]
                        pairs.extend(zip(case.images, images))
                        selected = list(dict.fromkeys(name for name, url in pairs if image_ref(url) in refs))
                        if prepared.target.ambiguous:
                            failures.append('image_target_ambiguous')
                        if set(selected) != set(check.expect.selected_images):
                            failures.append('selected_images_mismatch')
                        # Exact source-message identity, never a semantic keyword scan.
                        picture_seen, prior_replies = False, []
                        for utterance in case.history:
                            picture_seen |= bool(utterance.images)
                            if utterance.author == 'companion' and (picture_seen or utterance.image_target_refs):
                                prior_replies.append(utterance.text)
                        if refs and any(view.get('author') == 'companion' and view.get('text') in prior_replies for view in history):
                            failures.append('prior_image_reply_retained')
                    except Exception as error:
                        failures.append('image_context_error:' + type(error).__name__)
                observations.append({
                    'selected_images': selected, 'selected_image_refs': refs,
                    'expected_selected_images': check.expect.selected_images,
                    'filtered_history': [{k: v for k, v in view.items() if k != 'image_urls'} for view in history],
                    'failures': failures, 'passed': not failures, 'semantic_status': 'image_context_only',
                })
            checks.append({'id': check.id, 'component': 'tutoring.image-target',
                           'after_message': check.after_message, 'samples': observations})
        results.append({'id': row.id, 'label_status': row.label_status, 'replay_mode': row.replay_mode,
                        'checks': checks, 'excluded_checks': [
                            {'id': c.id, 'component': c.component, 'reason': 'tutor response and math Judge outside image-context scope'}
                            for c in row.checks]})
    return results
