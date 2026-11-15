"""Reuse production tutoring and independent local scoring, without cloud datasets."""

import time

from evals.local import solve


def execute(
    entry, record, backend, assets, solver_spec, sample_index=0, solve_call=None
):
    from evals.episode_runner import run_episode
    from evals.graders import failures, grade_result
    from evals.grading import unavailable
    from evals.outcome import Observation
    from evals.runner import Sample, _evidence, build_input, run_sample, sample_json

    if record.type == "episode":
        if entry["execution_target"] != "tutoring":
            raise ValueError("solution target does not accept episodes")
        result = run_episode(record.to_episode(), backend, assets_dir=assets)
        for step in result.steps:
            step.sample_index = sample_index
        checks = [sample_json(s) for s in result.steps]
    else:
        case = record.to_case()
        window, images = build_input(case, assets)
        if entry["execution_target"] == "tutoring":
            sample = run_sample(
                case, backend, window, images, sample_index=sample_index
            )
        else:
            started = time.perf_counter()
            latency_ms = None
            try:
                content = (solve_call or solve.complete)(case, solver_spec, images)
                if not isinstance(content, str) or not content.strip():
                    raise ValueError("empty_solution")
                obs = Observation(
                    "answer", content=content, delivered_content=content, tool_calls=[]
                )
                evidence = _evidence(case, obs)
                evidence["execution_target"] = "solve"
                pairs = list(zip(case.images, images))

                def judge(rule):
                    return backend.semantic_grader.grade(
                        rule,
                        evidence=evidence,
                        image_pairs=pairs,
                        reference=case.grading.reference_response,
                        criteria=[
                            {"id": c.id, "rubric": c.instructions()}
                            for c in case.grading.model_graded
                        ],
                    )

                latency_ms = round((time.perf_counter() - started) * 1000, 1)
                grading_started = time.perf_counter()
                grading = grade_result(case, obs, judge=judge, latency_ms=latency_ms)
                grading.meta["grading_latency_ms"] = round(
                    (time.perf_counter() - grading_started) * 1000, 1
                )
            except Exception as exc:  # noqa: BLE001 - isolate one failed evaluation sample
                obs = Observation("fallback", error=f"{type(exc).__name__}: {exc}")
                evidence = {}
                grading = unavailable(case.grading, obs.error)
            sample = Sample(
                obs,
                failures(grading),
                latency_ms
                if latency_ms is not None
                else round((time.perf_counter() - started) * 1000, 1),
                grading,
                case.id,
                case.check_id,
                sample_index,
                evidence,
            )
        checks = [sample_json(sample)]
    statuses = [c.get("status", "error") for c in checks]
    status = (
        "error"
        if "error" in statuses
        else "fail"
        if "fail" in statuses
        else "not_run"
        if "not_run" in statuses or not statuses
        else "pass"
    )
    return {
        **{
            k: entry[k]
            for k in (
                "subject",
                "level",
                "dataset",
                "execution_target",
                "split",
                "family_id",
            )
        },
        "case_id": record.id,
        "sample_index": sample_index,
        "status": status,
        "checks": checks,
        "calibration_status": "uncalibrated",
    }
