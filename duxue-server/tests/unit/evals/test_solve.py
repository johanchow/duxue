"""Unit tests for evals.solve using the production Guardian mentor workflow."""

from evals import solve


def test_solve_execute_maps_guardian_mentor_explain_to_answer(monkeypatch):
    seen = {}

    def fake_explain(**kwargs):
        seen.update(kwargs)
        return {"act": "explain", "content": "答案是 C. deposition。"}

    monkeypatch.setattr(solve, "_has_mentor_workflow", lambda: True)
    monkeypatch.setattr(
        "app.application.workflows.guardian_mentor.explain_for_guardian",
        fake_explain,
    )
    obs = solve.execute("Mud is left behind along the sides of a river.", ["data:image/png;base64,AA=="])
    assert obs.outcome == "answer"
    assert obs.reason is None
    assert obs.delivered_content == "答案是 C. deposition。"
    assert seen["guardian_id"].startswith("eval-solve-")
    assert seen["content"] == "Mud is left behind along the sides of a river."
    assert seen["images"] == ["data:image/png;base64,AA=="]
    assert seen["window"] == []
    assert seen["rows"] == []


def test_solve_execute_maps_clarify_safety_and_unavailable(monkeypatch):
    monkeypatch.setattr(solve, "_has_mentor_workflow", lambda: True)

    def run_with(reply):
        monkeypatch.setattr(
            "app.application.workflows.guardian_mentor.explain_for_guardian",
            lambda **kwargs: reply,
        )
        return solve.execute("q", [])

    clarify = run_with({"act": "clarify", "content": "请补充条件"})
    assert clarify.outcome == "clarify"
    assert clarify.delivered_content == "请补充条件"

    safety = run_with({"act": "safety", "content": "安全提示"})
    assert safety.outcome == "blocked"
    assert safety.reason == "safety"

    unavailable = run_with({"act": "unavailable", "content": "暂时不可用"})
    assert unavailable.outcome == "fallback"
    assert unavailable.reason == "unavailable"
