from __future__ import annotations

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
    cases = judge_boundary.load_cases()[:2]

    def unavailable(**_kwargs):
        return None

    summary = judge_boundary.summarize(
        judge_boundary.run_cases(cases, unavailable, samples=2, workers=1, summary="孩子本轮说：这题怎么做")
    )
    assert summary["unavailable"] == 4
    assert summary["false_positive"] == {"count": 0, "judged": 0, "rate": None}
    assert summary["false_negative"] == {"count": 0, "judged": 0, "rate": None}
    assert summary["operational_false_block"] == {"count": 2, "safe_samples": 2}
