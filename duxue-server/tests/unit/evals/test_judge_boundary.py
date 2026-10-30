from __future__ import annotations

import base64

from evals import judge_boundary


def test_first_image_cases_have_no_text_problem_context_and_include_indistinguishable_pair():
    cases = judge_boundary.load_cases()
    pair = [case for case in cases if case.get("pair") == "length-8"]
    assert len(pair) == 2
    assert pair[0]["reply"] == pair[1]["reply"]
    assert pair[0]["expected_leaks"] is False
    assert pair[1]["expected_leaks"] is True
    assert judge_boundary.production_summary() == "孩子本轮说：这题怎么做"

    received = []

    def judge(**kwargs):
        received.append(kwargs)
        return {"leaks": False, "reason": "none"}

    results = judge_boundary.run_cases(pair, judge, samples=1, workers=1)
    assert len(received) == 2
    assert received[0] == received[1]
    assert received[0]["problem_summary"] == "孩子本轮说：这题怎么做"
    assert all(case["reference_problem"] not in str(received) for case in pair)
    assert judge_boundary.summarize(results)["false_negative"]["count"] == 1

    received.clear()
    judge_boundary.run_cases(pair, judge, samples=1, workers=1, with_reference=True)
    assert received[0]["problem_summary"] != received[1]["problem_summary"]
    assert pair[0]["reference_problem"] in received[0]["problem_summary"]


def test_judge_errors_are_reported_separately_from_false_negatives():
    all_cases = judge_boundary.load_cases()
    cases = [next(c for c in all_cases if c["expected_leaks"] is wanted) for wanted in (False, True)]

    def unavailable(**_kwargs):
        return None

    summary = judge_boundary.summarize(
        judge_boundary.run_cases(cases, unavailable, samples=2, workers=1, summary="孩子本轮说：这题怎么做")
    )
    assert summary["unavailable"] == 4
    assert summary["false_positive"] == {"count": 0, "judged": 0, "rate": None}
    assert summary["false_negative"] == {"count": 0, "judged": 0, "rate": None}
    assert summary["operational_false_block"] == {"count": 2, "safe_samples": 2}


def test_worked_image_case_sends_the_original_asset_to_the_judge(tmp_path, monkeypatch):
    asset = "image-answer-check-worked.png"
    (tmp_path / asset).write_bytes(b"\x89PNGfixture")
    monkeypatch.setattr(judge_boundary, "ASSETS_DIR", tmp_path)
    case = next(case for case in judge_boundary.load_cases() if case["id"] == "worked-image-answer-confirmation")
    received = []

    def judge(**kwargs):
        received.append(kwargs)
        return {"leaks": False, "reason": "none"}

    result = judge_boundary.run_cases([case], judge, samples=1, workers=1)
    assert result[0]["observations"][0]["leaks"] is False
    assert received[0]["images"] == [f"data:image/png;base64,{base64.b64encode(b'\x89PNGfixture').decode()}"]


def test_case_problem_is_replayed_and_wrong_reason_is_counted(tmp_path):
    import json
    path = tmp_path / "trace-feedback.json"
    case = {"id": "trace-feedback", "reference_problem": "人工参考",
            "problem": "学生已经提交8，现在追问是否算对", "reply": "纠错候选",
            "expected_leaks": True, "expected_reason": "final_answer", "rationale": "保留计算给孩子"}
    path.write_text(json.dumps(case, ensure_ascii=False) + "\n")
    cases = judge_boundary.load_cases(path)
    received = []
    def judge(**kwargs):
        received.append(kwargs)
        return {"leaks": True, "reason": "incorrect_confirmation"}
    results = judge_boundary.run_cases(cases, judge, samples=2, workers=1)
    assert received[0]["problem_summary"] == case["problem"]
    assert judge_boundary.summarize(results)["wrong_reason"] == {"count": 2, "judged": 2}


def test_answer_feedback_diagnostic_turns_validate_without_changing_seed():
    from evals import dataset
    cases = dataset.load_cases()
    assert len([row for row in cases if row.review_batch == "answer-feedback-v1"]) == 0
    seed = [row for row in cases if row.review_batch == "seed-v1"]
    assert len(seed) == 16
    assert dataset.dataset_hash(seed) == "7084bc6835908cf9"
    assert len([row for row in judge_boundary.load_cases() if row["review_batch"] == "answer-feedback-v1"]) == 0


def test_judge_cases_are_individual_formatted_json_objects():
    from evals import dataset
    folder = dataset.DATA_DIR / 'leak_judge'
    files = list(folder.glob('*.json'))
    assert len(files) == 15
    for file in files:
        record = dataset.read_object(file)
        assert record['id'] == file.stem
        assert record['component'] == 'tutoring.leak-judge'
        assert '\n  "' in file.read_text()
    assert len(judge_boundary.load_cases(folder)) == 15
    assert not list(dataset.DATA_DIR.rglob('*.jsonl'))


def test_answer_feedback_uses_the_common_runner_and_batch():
    from evals import dataset
    from evals.__main__ import main
    cases = [row for row in dataset.load_cases() if row.review_batch == 'answer-feedback-v1']
    assert cases == []
    from evals.conversations import load_conversations
    assert len([row for row in load_conversations() if row.review_batch == "answer-feedback-v1"]) == 1
    assert main(['validate', '--batch', 'answer-feedback-v1']) == 0
    assert not (dataset.ROOT / 'evals' / 'answer_feedback.py').exists()


def test_common_cli_dispatches_to_the_generic_judge_runner(monkeypatch):
    from evals.__main__ import main
    received = []
    monkeypatch.setattr(judge_boundary, "main", lambda options: received.extend(options) or 0)
    assert main(["run-judges", "--batch", "answer-feedback-v1", "--case", "feedback-trace-first-draft", "--samples", "2"]) == 0
    assert received == ["--samples", "2", "--workers", "4", "--status", "confirmed,proposed,needs_decision",
                        "--batch", "answer-feedback-v1", "--case", "feedback-trace-first-draft"]


def test_judge_loader_rejects_jsonl_and_filename_mismatches(tmp_path):
    import json
    import pytest
    case = judge_boundary.load_cases()[0]
    for name in (case["id"] + ".jsonl", "wrong-id.json"):
        path = tmp_path / name
        path.write_text(json.dumps(case, ensure_ascii=False, indent=2))
        with pytest.raises(ValueError, match="<id>.json"):
            judge_boundary.load_cases(path)
