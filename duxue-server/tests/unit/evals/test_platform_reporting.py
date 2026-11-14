import copy
import json
from types import SimpleNamespace as Obj

from evals.platform.protocol import summarize_scores


def mixed_check():
    required = {
        "eval.answer_protection": {"equals": True},
        "eval.teaching_correctness": {"min": 4},
        "eval.safety": {"equals": True},
        "eval.case_requirements": {"equals": True},
        "eval.guidance_logic": {"min": 4},
        "eval.deterministic_pass": {"equals": True},
    }
    values = [False, 3, True, False, 4, True]
    scores = [
        {"name": name, "source": "EVAL", "value": value, "comment": "原始裁判理由"}
        for name, value in zip(required, values)
    ]
    check = {
        "check_id": "check-1",
        "trace_id": "trace",
        "observation_id": "child",
        **summarize_scores(required, scores),
    }
    return required, check


def test_checkpoint_explains_all_six_grades_without_changing_native_scores():
    from evals.platform.reporting import report_checkpoints

    required, check = mixed_check()
    original = copy.deepcopy(check)
    calls = []
    client = Obj(create_score=lambda **kw: calls.append(kw))
    result = {"checks": [check]}
    report_checkpoints(
        client, "status-config", result, {"check-1": {"evaluators": required}}
    )
    report_checkpoints(
        client, "status-config", result, {"check-1": {"evaluators": required}}
    )
    assert check["grades"] == original["grades"]
    assert calls[0] == calls[1]  # resume updates the same derived score
    score = calls[0]
    assert score["name"] == "eval.status"
    assert score["value"] == "fail"
    assert score["metadata"]["scope"] == "checkpoint"
    assert score["observation_id"] == "child"
    assert "❌ 不通过" in score["comment"]
    assert "3/5；要求 ≥4" in score["comment"]
    assert "✅ 通过 · 引导逻辑" in score["comment"]
    assert "False；要求 True" in score["comment"]
    for name in required:
        assert name in score["comment"]
    assert score["comment"].count("原始裁判理由：原始裁判理由") == 6


def test_summary_uses_remote_threshold_and_preserves_version_errors():
    from evals.platform.reporting import checkpoint_comment

    required = {"eval.guidance_logic": {"min": 5}}
    check = {
        **summarize_scores(
            required, [{"name": "eval.guidance_logic", "source": "EVAL", "value": 4}]
        ),
        "error": "evaluator_version_mismatch",
        "status": "error",
    }
    comment = checkpoint_comment(check, required)
    assert comment.startswith("⚠️ 评分/执行异常")
    assert "4/5；要求 ≥5" in comment
    assert "evaluator_version_mismatch" in comment
    missing = checkpoint_comment({"status": "error", "grades": []}, required)
    assert "⚠️" in missing and "缺少有效评分" in missing
    assert "✅" not in missing
    wrong_version = checkpoint_comment(
        {
            "status": "error",
            "wrong_versions": ["eval.safety"],
            "grades": [{"name": "eval.safety", "value": True, "status": "pass"}],
        },
        {"eval.safety": {"equals": True}},
    )
    assert "⚠️ 评分/执行异常 · 内容安全" in wrong_version
    assert "✅" not in wrong_version


def test_unexecuted_checkpoint_has_no_fabricated_observation():
    from evals.platform.reporting import report_checkpoints

    calls = []
    report_checkpoints(
        Obj(create_score=lambda **kw: calls.append(kw)),
        "config",
        {"checks": [{"status": "not_run", "check_id": "later"}]},
        {},
    )
    assert calls == []


def test_resume_backfills_checkpoint_display_without_rerunning_model(tmp_path):
    from evals.platform.resume import resume

    required, check = mixed_check()
    result = {
        "checks": [check, {"check_id": "later", "status": "not_run"}],
        "status": "fail",
        "trace_id": "trace",
        "observation_id": "root",
        "latency_ms": 10,
    }
    (tmp_path / "evaluators.json").write_text("{}")
    (tmp_path / "datasets.json").write_text(
        json.dumps(
            {
                "ds": [
                    {
                        "id": "item",
                        "expectedOutput": {
                            "checks": {"check-1": {"evaluators": required}}
                        },
                    }
                ]
            }
        )
    )
    (tmp_path / "item.json").write_text(json.dumps(result))
    calls = []
    client = Obj(
        api=Obj(
            score_configs=Obj(
                get=lambda **kw: Obj(
                    data=[
                        Obj(name=n, id=n, is_archived=False)
                        for n in ("eval.status", "eval.task_success", "eval.latency_ms")
                    ]
                )
            )
        ),
        create_score=lambda **kw: calls.append(kw),
        flush=lambda: None,
    )
    assert resume(client, tmp_path, 1) == 1
    assert [c["observation_id"] for c in calls].count("child") == 1
    assert all(
        c["name"] in ("eval.status", "eval.task_success", "eval.latency_ms")
        for c in calls
    )
    root = next(
        c for c in calls if c["name"] == "eval.status" and c["observation_id"] == "root"
    )
    assert "❌ 不通过" in root["comment"]
    assert "⏸️ 未执行" in root["comment"]
    assert "3/5；要求 ≥4" in root["comment"]
