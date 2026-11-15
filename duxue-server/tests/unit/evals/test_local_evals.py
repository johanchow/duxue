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
