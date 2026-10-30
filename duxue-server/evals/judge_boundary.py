"""Generic runner for one-file-per-case independent leak-judge evaluations.

Run from duxue-server/: python -m evals run-judges [--samples 3]
By default the reference transcription is used for labeling only. A case may
also name one local authorized image asset, which is sent directly to the
judge. The --with-reference counterfactual explicitly sends the reference text.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import time
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from pathlib import Path

from evals.dataset import ASSETS_DIR, DATA_DIR, read_object
from evals.schema import ASSET_NAME

os.environ["OTEL_SDK_DISABLED"] = "true"

DATA = DATA_DIR / "leak_judge"
STUDENT_SAID = "这题怎么做"
TASK_TITLE = "今日作业"


def load_cases(path: Path = DATA) -> list[dict]:
    files = [path] if path.is_file() else sorted(path.glob("*.json"))
    cases = [read_object(file) for file in files]
    for file, case in zip(files, cases):
        if file.suffix != ".json" or file.stem != case.get("id"):
            raise ValueError(f"{file.name}: each case must be <id>.json")
    ids: set[str] = set()
    for case in cases:
        if set(case) - {"id", "reference_problem", "reply", "expected_leaks", "rationale", "pair", "image", "problem", "expected_reason", "component", "source", "review_batch", "label_status", "reviewed_by"}:
            raise ValueError(f"unexpected fields in {case.get('id')}")
        if not all(isinstance(case.get(key), str) and case[key] for key in
                   ("id", "reference_problem", "reply", "rationale")):
            raise ValueError("each case needs an id, reference problem, reply and rationale")
        if type(case.get("expected_leaks")) is not bool:
            raise ValueError(f"invalid label: {case['id']}")
        if "problem" in case and (not isinstance(case["problem"], str) or not case["problem"].strip()):
            raise ValueError(f"invalid problem snapshot: {case['id']}")
        if "expected_reason" in case:
            reason = case["expected_reason"]
            if not isinstance(reason, str) or not reason.strip() or (reason == "none") != (not case["expected_leaks"]):
                raise ValueError(f"invalid expected reason: {case['id']}")
        if case.get("component", "tutoring.leak-judge") != "tutoring.leak-judge":
            raise ValueError(f"invalid judge component: {case['id']}")
        status = case.get("label_status", "proposed")
        if status not in {"proposed", "confirmed", "needs_decision"}:
            raise ValueError(f"invalid label status: {case['id']}")
        if (status == "confirmed") != bool(case.get("reviewed_by")):
            raise ValueError(f"confirmed needs reviewer; other labels cannot claim one: {case['id']}")
        if case["id"] in ids:
            raise ValueError(f"duplicate id: {case['id']}")
        if "image" in case and (not isinstance(case["image"], str) or not ASSET_NAME.match(case["image"])):
            raise ValueError(f"invalid image asset: {case['id']}")
        ids.add(case["id"])
    if not cases:
        raise ValueError("empty judge dataset")
    return cases


def production_summary() -> str:
    from app.application.workflows.tutor_loop import judge_problem_summary

    return judge_problem_summary([], STUDENT_SAID, recent_utterances=[])


def run_cases(
    cases: list[dict], judge: Callable[..., dict | None], *, samples: int = 1,
    workers: int = 4, summary: str | None = None, with_reference: bool = False,
) -> list[dict]:
    if samples < 1 or workers < 1:
        raise ValueError("samples and workers must be positive")
    problem_summary = summary if summary is not None else production_summary()
    results = [{"id": case["id"], "expected_leaks": case["expected_leaks"],
                "pair": case.get("pair"), "expected_reason": case.get("expected_reason"), "observations": [None] * samples} for case in cases]

    def call(case: dict) -> dict:
        started = time.monotonic()
        try:
            context = case.get("problem", problem_summary)
            case_summary = (f"第1题：{case['reference_problem']}\n{context}"
                            if with_reference else context)
            from evals.runner import read_asset
            images = [read_asset(ASSETS_DIR / case["image"])] if case.get("image") else None
            verdict = judge(
                text=case["reply"], task_title=TASK_TITLE, problem_summary=case_summary, images=images,
            )
            if not isinstance(verdict, dict) or type(verdict.get("leaks")) is not bool:
                return {"leaks": None, "reason": "judge_unavailable", "latency_ms": round((time.monotonic()-started)*1000)}
            return {"leaks": verdict["leaks"], "reason": verdict.get("reason"),
                    "latency_ms": round((time.monotonic()-started)*1000)}
        except Exception as error:  # noqa: BLE001 - Report failures; never count them as correct verdicts.
            return {"leaks": None, "reason": type(error).__name__,
                    "latency_ms": round((time.monotonic()-started)*1000)}

    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures = {pool.submit(call, case): (index, sample)
                   for index, case in enumerate(cases) for sample in range(samples)}
        for future in as_completed(futures):
            index, sample = futures[future]
            results[index]["observations"][sample] = future.result()
    return results


def summarize(results: list[dict]) -> dict:
    safe = [obs for row in results if not row["expected_leaks"] for obs in row["observations"]]
    leaks = [obs for row in results if row["expected_leaks"] for obs in row["observations"]]
    false_positive = sum(obs["leaks"] is True for obs in safe)
    false_negative = sum(obs["leaks"] is False for obs in leaks)
    safe_unavailable = sum(obs["leaks"] is None for obs in safe)
    leak_unavailable = sum(obs["leaks"] is None for obs in leaks)
    safe_judged = len(safe) - safe_unavailable
    leak_judged = len(leaks) - leak_unavailable
    reason_samples = [(row["expected_reason"], obs) for row in results if row.get("expected_reason")
                      for obs in row["observations"] if obs["leaks"] is not None]
    return {
        "wrong_reason": {"count": sum(obs.get("reason") != expected for expected, obs in reason_samples),
                         "judged": len(reason_samples)},
        "cases": len(results), "samples": len(safe) + len(leaks),
        "false_positive": {"count": false_positive, "judged": safe_judged,
                           "rate": false_positive / safe_judged if safe_judged else None},
        "false_negative": {"count": false_negative, "judged": leak_judged,
                           "rate": false_negative / leak_judged if leak_judged else None},
        "unavailable": safe_unavailable + leak_unavailable,
        "operational_false_block": {"count": false_positive + safe_unavailable, "safe_samples": len(safe)},
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data", type=Path, default=DATA)
    parser.add_argument("--batch")
    parser.add_argument("--status", default="confirmed,proposed,needs_decision")
    parser.add_argument("--samples", type=int, default=3)
    parser.add_argument("--workers", type=int, default=4)
    parser.add_argument("--out", type=Path)
    parser.add_argument("--case", action="append", help="Run only this case id; repeat for several cases")
    parser.add_argument("--with-reference", action="store_true",
                        help="Counterfactual: add the human transcription of the image to the judge input")
    parser.add_argument("--validate-only", action="store_true")
    args = parser.parse_args(argv)
    cases = load_cases(args.data)
    cases = [case for case in cases if case.get("label_status", "proposed") in args.status.split(",")
             and (not args.batch or case.get("review_batch") == args.batch)]
    if args.case:
        cases = [case for case in cases if case["id"] in args.case]
        if len(cases) != len(set(args.case)):
            parser.error("unknown or duplicate --case id")

    if not cases:
        parser.error("no matching judge cases")
    if args.validate_only:
        print(f"{len(cases)} judge cases valid")
        return 0

    from app.infrastructure.ai.components import COMPONENTS
    from app.infrastructure.ai.tutor_turn_model import QwenLeakJudge
    from evals.live import eval_settings, preflight

    preflight()
    spec = COMPONENTS.get("tutoring.leak-judge")
    judge = QwenLeakJudge(settings_obj=eval_settings())
    summary = production_summary()
    results = run_cases(cases, judge.leaks, samples=args.samples, workers=args.workers,
                        summary=summary, with_reference=args.with_reference)
    stats = summarize(results)
    output = args.out or Path("var/evals") / f"{datetime.now(timezone.utc):%Y%m%d-%H%M%S}-leak-judge.json"
    output.parent.mkdir(parents=True, exist_ok=True)
    sha = subprocess.run(["git", "rev-parse", "--short", "HEAD"], capture_output=True, text=True,
                         check=False).stdout.strip()
    report = {
        "meta": {"at": datetime.now(timezone.utc).isoformat(), "git_sha": sha,
                 "judge": spec.component_id, "version": spec.version, "model": spec.model,
                 "prompt_digest": spec.prompt.digest, "dataset_sha256": hashlib.sha256(json.dumps(cases, ensure_ascii=False, sort_keys=True).encode()).hexdigest(),
                 "student_said": STUDENT_SAID, "task_title": TASK_TITLE, "problem_summary": summary,
                 "context_mode": "reference_transcription" if args.with_reference else "case_snapshot_or_production_current",
                 "label_status": sorted({c.get("label_status", "proposed") for c in cases}),
                 "review_batch": args.batch, "samples_per_case": args.samples},
        "summary": stats, "cases": results,
    }
    output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"judge={spec.component_id}@{spec.version} model={spec.model} cases={stats['cases']} samples={stats['samples']}")
    print(f"误拦 FP={false_positive_display(stats)} 误放 FN={false_negative_display(stats)} 无有效裁决={stats['unavailable']}")
    print(f"结果：{output}")
    return 0 if stats["unavailable"] == 0 else 1


def false_positive_display(stats: dict) -> str:
    item = stats["false_positive"]
    return f"{item['count']}/{item['judged']}" if item["judged"] else "N/A"


def false_negative_display(stats: dict) -> str:
    item = stats["false_negative"]
    return f"{item['count']}/{item['judged']}" if item["judged"] else "N/A"


if __name__ == "__main__":
    raise SystemExit(main())
