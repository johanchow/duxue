"""Execute production components without invoking any local evaluator."""

import base64
import hashlib
import tempfile
import time
from pathlib import Path
from dataclasses import asdict
from evals.platform.protocol import hydrate


def materialize_assets(client, item, directory):
    from evals.schema import ASSET_NAME

    for name, asset in item.input.get("assets", {}).items():
        if not ASSET_NAME.fullmatch(name):
            raise ValueError("invalid remote asset name")
        uri = client.resolve_media_references(
            obj=asset["media"],
            resolve_with="base64_data_uri",
            content_fetch_timeout_seconds=30,
        )
        if (
            not isinstance(uri, str)
            or not uri.startswith("data:image/")
            or ";base64," not in uri
        ):
            raise ValueError(f"unresolved image: {name}")
        content = base64.b64decode(uri.split(";base64,", 1)[1], validate=True)
        if hashlib.sha256(content).hexdigest() != asset["sha256"]:
            raise ValueError(f"image integrity mismatch: {name}")
        (directory / name).write_bytes(content)


def turn(case, backend, assets, permit=None):
    from evals.runner import build_input, _observe_intent, _observe_tutor, _evidence
    from evals.graders import observations

    if case.snapshot_origin == "missing":
        raise ValueError("missing_input_snapshot")
    window, images = build_input(case, assets)
    start = time.perf_counter()
    obs = (
        _observe_intent(case, backend, window, images)
        if case.component == "companion.intent"
        else _observe_tutor(case, backend, window, images, permit_override=permit)
    )
    latency = round((time.perf_counter() - start) * 1000, 1)
    evidence = _evidence(case, obs)
    if permit is not None:
        evidence["input_snapshot"]["permit"] = asdict(permit)
    # SDK uploads these data URIs as Langfuse media. Native LLM evaluators see attachments.
    evidence["images"] = [
        {"name": n, "image": url}
        for n, url in zip(
            [n for row in case.history for n in row.images] + case.images,
            [url for row in window for url in row.get("image_urls", [])] + list(images),
        )
    ]
    return observations(obs, latency), evidence, latency, obs.error


def fixed_judge(backend, context, reply, assets):
    from evals.runner import read_asset
    from evals.judge_boundary import production_summary

    start = time.perf_counter()
    problem = context.get("problem") or production_summary(
        context.get("current_request") or "这题怎么做"
    )
    names = context.get("images", [])
    images = [read_asset(assets / n) for n in names]
    result = backend.leak_judge.leaks(
        text=reply,
        task_title=context.get("task_title"),
        problem_summary=problem,
        images=images or None,
    )
    latency = round((time.perf_counter() - start) * 1000, 1)
    if not isinstance(result, dict) or type(result.get("leaks")) is not bool:
        raise ValueError("production_judge_unavailable")
    return (
        {**result, "latency_ms": latency},
        {
            "candidate": reply,
            "input_snapshot": context,
            "images": [{"name": n, "image": u} for n, u in zip(names, images)],
            "response": result,
        },
        latency,
        None,
    )


def execute_item(client, item, scorer, backends):
    from evals.dialogue import TurnRecord, EpisodeRecord
    from evals.conversations import (
        ConversationEval,
        GateCheck,
        turn_case as replay_case,
    )
    from evals.episodes import turn_case as episode_case
    from evals.schema import Utterance
    from app.contexts.tutoring.domain.tutor_permit import AttemptSummary, TutorPermit

    record = hydrate(item)
    checks, total_latency = [], 0
    with tempfile.TemporaryDirectory(prefix="duxue-eval-assets-") as tmp:
        assets = Path(tmp)
        try:
            materialize_assets(client, item, assets)
        except Exception as exc:
            return {
                "status": "error",
                "case_id": record["id"],
                "error": str(exc),
                "checks": [],
                "latency_ms": 0,
            }
        episode = (
            EpisodeRecord.model_validate(record).to_episode()
            if record["type"] == "episode"
            else None
        )
        replay = (
            ConversationEval.model_validate(record)
            if record["type"] == "conversation_replay"
            else None
        )
        history = list(episode.initial_history) if episode else []
        prior_outcome, stopped = None, False
        for index, check in enumerate(record["checks"]):
            if stopped:
                checks.append(
                    {
                        "case_id": record["id"],
                        "check_id": check["id"],
                        "status": "not_run",
                        "error": "prior_checkpoint_failed",
                    }
                )
                continue
            spec = item.expected_output["checks"][check["id"]]
            try:
                backend = backends[
                    "companion.intent"
                    if check["component"] == "companion.intent"
                    else "tutoring.turn"
                ]
                if record["type"] == "single_turn":
                    observed, evidence, latency, error = turn(
                        TurnRecord.model_validate(record).to_case(), backend, assets
                    )
                elif episode:
                    step = episode.turns[index]
                    said = step.student_on.get(prior_outcome, step.student_said)
                    case = episode_case(episode, index, history, said)
                    observed, evidence, latency, error = turn(case, backend, assets)
                elif replay:
                    parsed = replay.checks[index]
                    if isinstance(parsed, GateCheck):
                        original = next(
                            a for a in replay.attempts if a.id == parsed.attempt_id
                        )
                        observed, evidence, latency, error = fixed_judge(
                            backend,
                            original.gate.input.model_dump(mode="json"),
                            original.gate.input.reply,
                            assets,
                        )
                    else:
                        snapshot = parsed.input_snapshot.permit
                        permit = TutorPermit(
                            answer_protected=snapshot.answer_protected,
                            active_subgoal=snapshot.active_subgoal,
                            attempt_summary=AttemptSummary(
                                **snapshot.attempt_summary.model_dump()
                            ),
                        )
                        observed, evidence, latency, error = turn(
                            replay_case(replay, parsed), backend, assets, permit
                        )
                else:
                    candidate = next(
                        c
                        for c in record["candidates"]
                        if c["id"] == check["candidate_id"]
                    )
                    observed, evidence, latency, error = fixed_judge(
                        backend, check["input_snapshot"], candidate["content"], assets
                    )
            except Exception as exc:
                observed, evidence, latency, error = (
                    {},
                    {},
                    0,
                    f"{type(exc).__name__}: {exc}",
                )
            total_latency += latency
            result = scorer.evaluate(
                case_id=record["id"],
                check_id=check["id"],
                spec=spec,
                evidence=evidence,
                observed=observed,
                latency_ms=latency,
                execution_error=error,
            )
            checks.append(result)
            print(f"{record['id']}/{check['id']}: {result['status']}", flush=True)
            if episode:
                stopped = result["status"] != "pass"
                if not stopped:
                    history.extend(
                        [
                            Utterance(author="ward", text=said, images=step.images),
                            Utterance(
                                author="companion",
                                text=evidence["response"]["message"] or "",
                                image_target_refs=observed.get(
                                    "selected_image_refs", []
                                ),
                            ),
                        ]
                    )
                    prior_outcome = observed.get("outcome")
    states = {c["status"] for c in checks}
    status = next((s for s in ("error", "fail", "not_run") if s in states), "pass")
    return {
        "case_id": record["id"],
        "status": status,
        "checks": checks,
        "latency_ms": total_latency,
    }
