import subprocess
import sys


def test_validate_is_offline_and_reports_missing_dataset(tmp_path):
    p = subprocess.run(
        [sys.executable, "-m", "evals.local", "validate", "--data", str(tmp_path)],
        capture_output=True,
        text=True,
        check=False,
    )
    assert p.returncode != 0
    assert "manifest.json" in p.stderr
    assert "LANGFUSE" not in p.stderr


def test_local_cli_does_not_import_cloud_runner():
    code = "from evals.local.__main__ import parser; import sys; parser().parse_args(['validate']); assert 'evals.platform.client' not in sys.modules; assert 'langfuse' not in sys.modules"
    p = subprocess.run(
        [sys.executable, "-c", code], capture_output=True, text=True, check=False
    )
    assert p.returncode == 0, p.stderr


def test_summary_keeps_errors_not_run_and_replicates_separate():
    from evals.local.report import summarize

    rows = [
        {
            "case_id": "a",
            "sample_index": 0,
            "status": "pass",
            "subject": "math",
            "level": "gaokao_equivalent",
            "dataset": "teaching-correctness",
            "execution_target": "solve",
        },
        {
            "case_id": "a",
            "sample_index": 1,
            "status": "error",
            "subject": "math",
            "level": "gaokao_equivalent",
            "dataset": "teaching-correctness",
            "execution_target": "solve",
        },
        {
            "case_id": "b",
            "sample_index": 0,
            "status": "not_run",
            "subject": "english",
            "level": "other_k12",
            "dataset": "guidance-logic",
            "execution_target": "tutoring",
        },
    ]
    s = summarize(rows)
    assert s["samples"]["error"] == 1
    assert s["samples"]["not_run"] == 1
    assert s["tasks"]["total"] == 2
    assert s["tasks"]["all_samples_passed"] == 0
    assert s["by_subject"]["math"]["total"] == 2


def test_summary_reports_p90_latency_and_leak_retry_diagnostics():
    from evals.local.report import summarize

    rows = [
        {
            "case_id": f"c{i}",
            "sample_index": 0,
            "status": "pass" if i < 9 else "fail",
            "subject": "math",
            "level": "gaokao_equivalent",
            "dataset": "guidance-logic",
            "execution_target": "tutoring",
            "checks": [
                {
                    "status": "pass" if i < 9 else "fail",
                    "latency_ms": float((i + 1) * 100),
                    "leak_retried": i in (1, 9),
                    "outcome": "fallback" if i == 9 else "hint_like",
                    "reason": "leak_detected" if i == 9 else None,
                }
            ],
        }
        for i in range(10)
    ]
    s = summarize(rows)
    assert s["latency_ms"]["count"] == 10
    assert s["latency_ms"]["p50"] == 500.0
    assert s["latency_ms"]["p90"] == 900.0
    assert s["latency_ms"]["max"] == 1000.0
    assert s["tutoring_diagnostics"] == {
        "evaluated_checkpoints": 10,
        "leak_retried": 2,
        "leak_retry_rate": 0.2,
        "fallbacks": 1,
        "fallback_reasons": {"leak_detected": 1},
    }


def test_math_preflight_blocks_when_enabled_executor_is_down(monkeypatch):
    from types import SimpleNamespace

    from app.agent_specs.admin_bundle import compile_bundle
    from app.agent_specs.configuration import read_snapshot
    from app.agent_specs.definitions import use_definitions
    from evals import live
    from scripts.upgrade_math_bundle import upgrade

    monkeypatch.setattr(live, "settings", SimpleNamespace(dashscope_api_key="test-key"))
    compiled = compile_bundle(upgrade(read_snapshot(), enable=True)["bundle"])
    with use_definitions(compiled.catalog):
        monkeypatch.setenv("MATH_ENGINE_MODE", "socket")
        monkeypatch.setenv("MATH_ENGINE_SOCKET", "/tmp/nonexistent-duxue-math.sock")
        try:
            live.preflight()
        except SystemExit as exc:
            assert "数学执行器预检未通过" in str(exc)
        else:
            raise AssertionError("preflight should fail when socket executor is down")

        monkeypatch.setenv("MATH_ENGINE_MODE", "subprocess")
        live.preflight()


def test_summary_aggregates_llm_completion_outcomes_and_tokens():
    from evals.local.report import summarize

    rows = [
        {
            "case_id": "c1",
            "sample_index": 0,
            "status": "pass",
            "subject": "history",
            "level": "gaokao_equivalent",
            "dataset": "guidance-logic",
            "execution_target": "tutoring",
            "checks": [
                {
                    "status": "pass",
                    "latency_ms": 1200.0,
                    "outcome": "hint_like",
                    "llm_calls": [
                        {
                            "provider_request_id": "r1",
                            "finish_reason": "stop",
                            "stream_completed": True,
                            "tokens_in": 100,
                            "tokens_out": 80,
                            "tokens_answer": 30,
                            "tokens_reasoning": 50,
                            "outcome": "ok",
                            "abrupt_detail": None,
                        },
                        {
                            "provider_request_id": "r2",
                            "finish_reason": "stop",
                            "stream_completed": True,
                            "tokens_in": 90,
                            "tokens_out": 40,
                            "tokens_answer": 40,
                            "tokens_reasoning": None,
                            "outcome": "stop_wire_gap",
                            "abrupt_detail": "structured_decode_gap",
                        },
                        {
                            "provider_request_id": "r3",
                            "finish_reason": "length",
                            "stream_completed": True,
                            "tokens_in": 50,
                            "tokens_out": 200,
                            "tokens_answer": 10,
                            "tokens_reasoning": 190,
                            "outcome": "length_truncated",
                            "abrupt_detail": None,
                        },
                        {
                            "provider_request_id": "r4",
                            "finish_reason": None,
                            "stream_completed": False,
                            "tokens_in": None,
                            "tokens_out": None,
                            "tokens_answer": None,
                            "tokens_reasoning": None,
                            "outcome": "incomplete_stream",
                            "abrupt_detail": None,
                        },
                    ],
                }
            ],
        }
    ]
    comp = summarize(rows)["llm_completions"]
    assert comp["total_calls"] == 4
    assert comp["stream_completed"] == 3
    assert comp["stream_incomplete"] == 1
    assert comp["by_finish_reason"] == {"length": 1, "none": 1, "stop": 2}
    assert comp["by_outcome"]["ok"] == 1
    assert comp["by_outcome"]["stop_wire_gap"] == 1
    assert comp["by_outcome"]["length_truncated"] == 1
    assert comp["by_outcome"]["incomplete_stream"] == 1
    assert comp["by_outcome"]["api_error"] == 0
    assert comp["by_outcome"]["json_parse_error"] == 0
    assert comp["by_outcome"]["contract_error"] == 0
    assert comp["abrupt_details"] == {"structured_decode_gap": 1}
    assert comp["tokens"] == {
        "input": 240,
        "output": 320,
        "answer": 80,
        "reasoning": 240,
    }
