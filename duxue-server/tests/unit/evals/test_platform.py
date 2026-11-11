import json
from types import SimpleNamespace as Obj
import pytest
from evals.dataset import DATA_DIR
from evals.platform.protocol import convert, hydrate, summarize_scores


def test_all_records_roundtrip_without_gold_in_application_input():
    paths = list(DATA_DIR.glob("*/*.json"))
    assert len(paths) == 41
    for p in paths:
        original = json.loads(p.read_text())
        row = convert(original, p.parent.name)
        assert all("grading" not in c for c in row["input"]["record"]["checks"])
        restored = hydrate(Obj(**row))
        assert restored.get("messages") == original.get("messages")
        assert len(restored["checks"]) == len(original["checks"])
        assert row == convert(original, p.parent.name)
        for check in original["checks"]:
            assert row["expected_output"]["checks"][check["id"]]["rationale"] == check[
                "grading"
            ].get("rationale", [])
        assert all(not c["grading"]["model_graded"] for c in restored["checks"])


@pytest.mark.parametrize(
    "scores,status",
    [
        ([], "error"),
        ([{"name": "eval.safety", "source": "API", "value": 1}], "error"),
        ([{"name": "eval.safety", "source": "EVAL", "value": 1}], "pass"),
        ([{"name": "eval.safety", "source": "EVAL", "value": 0}], "fail"),
        ([{"name": "eval.safety", "source": "EVAL", "value": "true"}], "error"),
        ([{"name": "eval.safety", "source": "EVAL", "value": 1}] * 2, "error"),
    ],
)
def test_scores_fail_closed(scores, status):
    assert (
        summarize_scores({"eval.safety": {"equals": True}}, scores)["status"] == status
    )


def test_numeric_threshold_is_not_hardcoded():
    scores = [{"name": "q", "source": "EVAL", "value": 4}]
    assert summarize_scores({"q": {"min": 5}}, scores)["status"] == "fail"
    assert summarize_scores({"q": {"min": 4}}, scores)["status"] == "pass"


def test_empty_requirements_not_pass():
    assert summarize_scores({}, [])["status"] == "error"


def test_missing_semantic_evaluator_is_rejected():
    p = next(DATA_DIR.rglob("pedagogy-cone-rounding.json"))
    row = convert(json.loads(p.read_text()), p.parent.name)
    row["expected_output"]["checks"]["check-1"]["evaluators"] = {
        "eval.deterministic_pass": {"equals": True}
    }
    with pytest.raises(ValueError, match="semantic"):
        hydrate(Obj(**row))


def test_remote_media_integrity_and_path(tmp_path):
    import base64, hashlib
    from evals.platform.execution import materialize_assets

    raw = b"image"
    client = Obj(
        resolve_media_references=lambda **kw: (
            "data:image/png;base64," + base64.b64encode(raw).decode()
        )
    )
    item = Obj(
        input={
            "assets": {
                "a.png": {"media": "ref", "sha256": hashlib.sha256(raw).hexdigest()}
            }
        }
    )
    materialize_assets(client, item, tmp_path)
    assert (tmp_path / "a.png").read_bytes() == raw
    item.input["assets"]["a.png"]["sha256"] = "wrong"
    with pytest.raises(ValueError, match="integrity"):
        materialize_assets(client, item, tmp_path)
    item.input["assets"] = {"../a.png": {"media": "ref"}}
    with pytest.raises(ValueError, match="name"):
        materialize_assets(client, item, tmp_path)


def test_migration_refuses_remote_edit_even_with_old_digest(tmp_path, monkeypatch):
    from evals.platform import migration

    p = next(DATA_DIR.rglob("pedagogy-cone-rounding.json"))
    row = convert(json.loads(p.read_text()), p.parent.name)
    row["input"]["record"]["title"] = "remote edit"
    monkeypatch.setattr(migration, "dataset_items", lambda *args: [Obj(**row)])
    (tmp_path / p.parent.name).mkdir()
    (tmp_path / p.parent.name / p.name).write_text(p.read_text())
    with pytest.raises(ValueError, match="refusing overwrite"):
        migration.migrate(
            None, {"datasets": [{"name": p.parent.name}]}, tmp_path, tmp_path
        )


def test_native_collect_checks_real_api_shape_and_version():
    from evals.platform.native import NativeScorer

    class Score:
        def __init__(self, version):
            self.version = version

        def model_dump(self, **kw):
            return {
                "id": "score",
                "name": "eval.safety",
                "source": "EVAL",
                "value": True,
                "metadata": {"evaluator_version_id": self.version},
            }

    calls = []

    def get_many(**kw):
        calls.append(kw)
        return Obj(data=[Score("v1")], meta=Obj(cursor=None))

    client = Obj(api=Obj(scores=Obj(get_many=get_many)))
    scorer = NativeScorer(client, {"eval.safety": {"versionId": "v1"}}, interval=0)
    assert (
        scorer.collect({"eval.safety": {"equals": True}}, "trace", "observation")[
            "status"
        ]
        == "pass"
    )
    assert calls[0]["fields"] == "core,details,subject"
    scorer.versions["eval.safety"]["versionId"] = "v2"
    assert (
        scorer.collect({"eval.safety": {"equals": True}}, "trace", "observation")[
            "status"
        ]
        == "error"
    )


def test_default_cli_dispatches_live_run_only_to_hosted_runner(monkeypatch):
    from evals.__main__ import main
    from evals.platform import __main__ as remote

    seen = []
    monkeypatch.setattr(remote, "main", lambda args: seen.extend(args) or 0)
    assert main(["run", "--config-snapshot", "config.json"]) == 0
    assert seen == ["run", "--config-snapshot", "config.json"]


@pytest.mark.parametrize("fail_on,expected_calls", [(None, 6), (2, 2)])
def test_hosted_episode_uses_actual_history_and_stops_on_cloud_failure(
    fail_on, expected_calls
):
    from evals.platform.execution import execute_item
    from evals.runner import Backends
    from tests.support.fakes import StaticLeakJudge, StaticTutorModel, tutor_raw

    p = next(DATA_DIR.rglob("episode-mathdial-balance.json"))
    item = Obj(**convert(json.loads(p.read_text()), p.parent.name))
    model = StaticTutorModel(
        *[tutor_raw("guide", f"actual reply {i}") for i in range(6)]
    )
    backend = Backends(tutor_model=model, leak_judge=StaticLeakJudge(False))
    seen = []

    class Scorer:
        def evaluate(self, **kw):
            seen.append(kw)
            assert not kw["execution_error"]
            return {"status": "fail" if len(seen) == fail_on else "pass"}

    result = execute_item(Obj(), item, Scorer(), {"tutoring.turn": backend})
    assert len(model.calls) == expected_calls
    assert {"author": "companion", "text": "actual reply 0"} in model.calls[1][
        "recent_utterances"
    ]
    assert result["status"] == ("fail" if fail_on else "pass")
    if fail_on:
        assert [c["status"] for c in result["checks"][2:]] == ["not_run"] * 4


def test_score_pagination_never_passes_from_partial_page():
    from evals.platform.native import NativeScorer

    class Score:
        def model_dump(self, **kw):
            return {"name": "x", "source": "EVAL", "value": True}

    client = Obj(
        api=Obj(
            scores=Obj(
                get_many=lambda **kw: Obj(data=[Score()], meta=Obj(cursor="next"))
            )
        )
    )
    result = NativeScorer(client, {"x": {"versionId": "v"}}, interval=0).collect(
        {"x": {"equals": True}}, "t", "o"
    )
    assert result["status"] == "error"
    assert result["error"] == "ambiguous_score_pagination"


def test_task_summary_scores_explain_failure_and_point_to_native_grades():
    from evals.platform.__main__ import aggregate

    calls = []
    result = {
        "status": "fail",
        "latency_ms": 10,
        "checks": [
            {
                "check_id": "check-1",
                "observation_id": "child",
                "status": "fail",
                "grades": [
                    {
                        "name": "eval.teaching_correctness",
                        "value": 2,
                        "status": "fail",
                        "comment": "需要复核的裁判理由",
                    }
                ],
            }
        ],
    }
    aggregate(
        Obj(create_score=lambda **kw: calls.append(kw)),
        {n: n for n in ("eval.status", "eval.task_success", "eval.latency_ms")},
        result,
        "trace",
        "root",
    )
    assert len(calls) == 3
    status = next(c for c in calls if c["name"] == "eval.status")
    assert "eval.teaching_correctness" in status["comment"]
    assert "child" in status["comment"]
    assert "需要复核的裁判理由" in status["comment"]
    assert all(c["comment"] for c in calls)
    assert all(c["observation_id"] == "root" for c in calls)


@pytest.mark.parametrize(
    "status,level",
    [
        ("pass", "DEFAULT"),
        ("fail", "DEFAULT"),
        ("not_run", "DEFAULT"),
        ("error", "ERROR"),
    ],
)
def test_task_observation_level_distinguishes_grading_failure_from_execution_error(
    status, level
):
    from evals.platform.reporting import report_task_status

    updates = []
    report_task_status(
        Obj(update_current_span=lambda **kw: updates.append(kw)),
        {
            "status": status,
            "checks": [
                {
                    "check_id": "check-1",
                    "status": status,
                    "error": "native_evaluation_missing_or_ambiguous",
                }
            ],
        },
    )
    assert updates[0]["level"] == level
    if status == "error":
        assert "check-1" in updates[0]["status_message"]
        assert "native_evaluation_missing_or_ambiguous" in updates[0]["status_message"]
    else:
        assert updates[0]["status_message"] == ""


def test_task_observation_preserves_uncaught_execution_error():
    from evals.platform.reporting import report_task_status

    updates = []
    report_task_status(
        Obj(update_current_span=lambda **kw: updates.append(kw)),
        {"status": "error", "error": "RuntimeError: execution exploded", "checks": []},
    )
    assert updates == [
        {"level": "ERROR", "status_message": "RuntimeError: execution exploded"}
    ]


def test_offline_task_overrides_sdk_forced_environment_on_active_experiment_span(
    monkeypatch,
):
    from opentelemetry.sdk.trace import TracerProvider
    from evals.platform.reporting import call_offline_task
    from evals.platform.client import EVALUATION_ENVIRONMENT

    monkeypatch.setenv("OTEL_SDK_DISABLED", "false")
    provider = TracerProvider()
    try:
        with provider.get_tracer("offline-test").start_as_current_span(
            "experiment-item-task",
            attributes={"langfuse.environment": "sdk-experiment"},
        ) as span:
            assert (
                call_offline_task(lambda: span.attributes["langfuse.environment"])
                == "offline-evaluation"
            )
            assert span.attributes["langfuse.environment"] == EVALUATION_ENVIRONMENT
    finally:
        provider.shutdown()


def test_native_checkpoint_overrides_sdk_experiment_environment(monkeypatch):
    from contextlib import contextmanager
    from opentelemetry.sdk.trace import TracerProvider
    from evals.platform.native import NativeScorer

    monkeypatch.setenv("OTEL_SDK_DISABLED", "false")
    provider = TracerProvider()
    finished = []

    @contextmanager
    def start(**kwargs):
        with provider.get_tracer("sdk-simulation").start_as_current_span(
            "eval.checkpoint", attributes={"langfuse.environment": "sdk-experiment"}
        ) as span:
            yield Obj(trace_id="trace", id="checkpoint")
            finished.append(span.attributes["langfuse.environment"])

    try:
        scorer = NativeScorer(
            Obj(start_as_current_observation=start, flush=lambda: None),
            {"eval.deterministic_pass": {}},
        )
        monkeypatch.setattr(scorer, "collect", lambda *args: {"status": "pass"})
        scorer.evaluate(
            case_id="case",
            check_id="check",
            spec={
                "evaluators": {"eval.deterministic_pass": {"equals": True}},
                "deterministic": [],
                "case_criteria": [],
            },
            evidence={},
            observed={},
            latency_ms=1,
        )
        assert finished == ["offline-evaluation"]
    finally:
        provider.shutdown()
