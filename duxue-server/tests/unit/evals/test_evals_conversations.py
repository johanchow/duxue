"""Real conversation snapshots stay fixed across checkpoints and samples."""

import copy
from pathlib import Path

FIXTURES = Path(__file__).resolve().parents[2] / "fixtures" / "eval_protocol"

import pytest
from evals import dataset
from evals.__main__ import main


def _row():
    return dataset.read_object(
        FIXTURES / "answer-feedback-conversation.json"
    )


def test_conversation_directory_validates_without_model_calls():
    from evals.conversations import load_conversations

    assert [row.id for row in load_conversations()] == ["protection-scope-conversation"]
    assert main(["validate", "--category", "guidance-logic"]) == 0
    assert dataset.validate_layout() == []
    assert all(row.review_batch != "answer-feedback-v1" for row in dataset.load_cases())


@pytest.mark.parametrize(
    "change",
    ["future", "retry_cycle", "delivery", "wrong_round", "duplicate", "unknown"],
)
def test_invalid_references_and_unknown_fields_are_rejected(change):
    from evals.conversations import ConversationEval

    row = copy.deepcopy(_row())
    if change == "future":
        row["checks"][0]["after_message"] = "m8"
    elif change == "retry_cycle":
        row["attempts"][0]["retry_of"] = row["attempts"][0]["id"]
    elif change == "delivery":
        row["attempts"][0]["delivered_as"] = "m10"
    elif change == "wrong_round":
        row["checks"][2]["after_message"] = "m9"
    elif change == "duplicate":
        row["messages"][1]["id"] = "m1"
    else:
        row["checks"][0]["grading"]["keyword_judge"] = True
    with pytest.raises(ValueError):
        ConversationEval.model_validate(row)


def test_fixed_history_and_snapshot_permit():
    from evals.conversation_runner import run_conversations
    from evals.conversations import load_conversations, turn_case
    from tests.support.eval_cases import Backends
    from tests.support.fakes import StaticLeakJudge, StaticTutorModel, tutor_raw

    row = load_conversations(FIXTURES / "answer-feedback-conversation.json")[0]
    first, second = [
        turn_case(row, c) for c in row.checks if c.component == "tutoring.turn"
    ]
    assert first.student_said == "等于八。"
    assert second.student_said == "那你告诉我有没有算对？"
    assert second.history[-1].text == row.messages[7].content
    model = StaticTutorModel(tutor_raw("guide", "本次生成的新回复"))

    class Judge(StaticLeakJudge):
        def leaks(self, **kwargs):
            super().leaks(**kwargs)
            return {"leaks": False, "reason": "none"}

    result = run_conversations(
        [row], Backends(tutor_model=model, leak_judge=Judge(False)), samples=2
    )
    assert len(result[0]["checks"]) == 5
    assert all(
        "本次生成的新回复" not in str(call["recent_utterances"]) for call in model.calls
    )
    assert all(
        s["calibration_status"] == "uncalibrated"
        for c in result[0]["checks"][:2]
        for s in c["samples"]
    )
    assert result[0]["checks"][0]["samples"][0]["quality_passed"] is None
    assert first.context.problem.substantive_attempts == 1
    assert second.context.problem.substantive_attempts == 2


def test_fixed_gate_preserves_input_and_reports_wrong_reason_and_unavailable():
    from evals.conversation_runner import run_conversations
    from evals.conversations import load_conversations
    from tests.support.eval_cases import Backends

    row = load_conversations(FIXTURES / "answer-feedback-conversation.json")[0]
    row.checks = [row.checks[3]]
    received = []

    class Judge:
        def leaks(self, **kwargs):
            received.append(kwargs)
            return (
                {"leaks": True, "reason": "incorrect_confirmation"}
                if len(received) == 1
                else None
            )

    samples = run_conversations([row], Backends(leak_judge=Judge()), samples=2)[0][
        "checks"
    ][0]["samples"]
    assert [
        (g["id"], g["status"]) for g in samples[0]["grades"] if g["status"] != "pass"
    ] == [("reason_eq", "fail")]
    assert samples[1]["status"] == "error"
    original = row.attempts[1].gate.input
    assert received[0] == {
        "text": original.reply,
        "task_title": original.task_title,
        "problem_summary": original.problem,
    }


def test_scope_snapshot_preserves_recent_problems_visual_and_scope_expectation():
    from evals.conversations import ConversationEval, turn_case

    row = _row()
    check = row["checks"][0]
    check["input_snapshot"]["recent_problems"] = ["当前铅笔题", "较早苹果题"]
    check["grading"]["deterministic"].extend(
        [
            {
                "id": "scope",
                "field": "exit_gate.answer_protected",
                "op": "eq",
                "expected": False,
            },
            {"id": "visual", "field": "visual_present", "op": "eq", "expected": True},
            {"id": "kind", "field": "visual_kind", "op": "in", "expected": ["compare"]},
        ]
    )
    parsed = ConversationEval.model_validate(row)
    case = turn_case(parsed, parsed.checks[0])
    assert case.context.recent_problems == ["当前铅笔题", "较早苹果题"]
    assert case.grading.expectation("exit_gate.answer_protected") is False
    assert case.grading.expectation("visual_present") is True
    assert case.grading.deterministic[-1].expected == ["compare"]


def test_replay_requires_the_expected_independent_scope_not_only_allow_verdict():
    from evals.grading import Grading, evaluate

    grading = Grading.model_validate(
        {
            "deterministic": [
                {
                    "id": "scope",
                    "field": "answer_protected",
                    "op": "eq",
                    "expected": False,
                }
            ]
        }
    )
    assert evaluate(grading, {"answer_protected": True}).status == "fail"
    assert evaluate(grading, {}).status == "error"


def test_original_rejected_attempts_remain_separate_from_visible_history_and_new_labels():
    from evals.conversations import load_conversations

    row = next(
        row for row in load_conversations() if row.id == "protection-scope-conversation"
    )
    assert len(row.messages) == 12 and len(row.attempts) == 3
    for attempt in row.attempts:
        assert not attempt.shown_to_user and attempt.delivered_as is None
        assert attempt.gate.observed_verdict.leaks
        assert (
            attempt.gate.observed_verdict.answer_protected is None
        )  # Not present in the old schema.
        assert attempt.gate.observed_facts["new_final_answer"] is True
        assert attempt.gate.observed_facts["complete_solution"] is True
    gates = [check for check in row.checks if check.component == "tutoring.leak-judge"]
    assert len(gates) == 3
    assert all(
        check.grading.expectation("leaks") is False
        and check.grading.expectation("answer_protected") is False
        for check in gates
    )


def test_legacy_versions_are_rejected_and_shared_messages_preserve_images():
    from evals.conversations import ConversationEval, turn_case

    row = _row()
    row["messages"][0]["images"] = ["img-aaaaaaaaaaaa.jpg"]
    parsed = ConversationEval.model_validate(row)
    assert turn_case(parsed, parsed.checks[0]).history[0].images == [
        "img-aaaaaaaaaaaa.jpg"
    ]
    for old_version in ("conversation-eval.v1", "conversation-eval.v2"):
        row["schema_version"] = old_version
        with pytest.raises(ValueError, match="schema_version"):
            ConversationEval.model_validate(row)


def test_real_image_incident_preserves_original_error_and_new_target_expectations():
    from evals.conversations import load_conversations, turn_case

    row = next(
        row for row in load_conversations(FIXTURES) if row.id == "new-image-review-conversation"
    )
    assert row.schema_version == "dialogue-eval.v2"
    assert len(row.messages) == 8 and len(row.attempts) == 6
    assert row.messages[0].images != row.messages[2].images
    for check in [check for check in row.checks if check.component == "tutoring.turn"]:
        case = turn_case(row, check)
        assert case.grading.expectation("selected_images")
        assert any(message.images for message in case.history) or case.images
    repair = next(attempt for attempt in row.attempts if attempt.id == "attempt-1-1")
    assert repair.shown_to_user and not repair.gate.observed_verdict.leaks
    assert (
        repair.repair_feedback is None
        and repair.repair_feedback_status == "unavailable"
    )
    check = next(
        check for check in row.checks if getattr(check, "attempt_id", None) == repair.id
    )
    assert (
        check.grading.expectation("leaks") is True
        and check.grading.expectation("reason") == "premature_conclusion"
    )


def test_shared_format_preserves_picture_only_messages_without_inventing_student_text():
    from evals.conversations import ConversationEval

    row = _row()
    row["messages"][0]["content"] = ""
    row["messages"][0]["images"] = ["img-aaaaaaaaaaaa.jpg"]
    parsed = ConversationEval.model_validate(row)
    assert parsed.messages[0].content == ""


@pytest.mark.parametrize("change", ["no_retry", "fabricated"])
def test_unavailable_original_feedback_cannot_hide_observed_or_fabricated_data(change):
    from evals.conversations import ConversationEval

    row = dataset.read_object(
        FIXTURES / "new-image-review-conversation.json"
    )
    retry = next(
        a for a in row["attempts"] if a.get("repair_feedback_status") == "unavailable"
    )
    if change == "no_retry":
        retry["retry_of"] = None
    else:
        retry["repair_feedback"] = "invented feedback"
    with pytest.raises(ValueError, match="unavailable feedback"):
        ConversationEval.model_validate(row)


def test_image_context_scope_checks_real_targets_without_running_math_or_changing_history(
    tmp_path,
):
    from evals.conversation_runner import run_image_context
    from evals.conversations import load_conversations

    row = next(
        r for r in load_conversations(FIXTURES) if r.id == "new-image-review-conversation"
    )
    original = row.model_dump()
    for i, name in enumerate(dict.fromkeys(n for m in row.messages for n in m.images)):
        (tmp_path / name).write_bytes(str(i).encode())
    calls = []

    def select(window, content):
        calls.append(content)
        return {"target_image_ids": [2], "ambiguous": False}

    result = run_image_context([row], samples=1, assets_dir=tmp_path, select=select)[0]
    assert len(result["checks"]) == 6
    assert len(result["excluded_checks"]) == 3
    assert all(s["status"] == "not_run" for c in result["checks"] for s in c["samples"])
    assert all(
        g["status"] == "pass"
        for c in result["checks"][:3]
        for s in c["samples"]
        for g in s["grades"]
        if g["id"].startswith("scope_") or g["id"] == "selected_images_set_eq"
    )
    assert calls == ["这不是同一个图片，这是一个新的图片。"]
    assert row.model_dump() == original
    assert all(
        g["status"] == "not_run"
        for c in result["checks"]
        for s in c["samples"]
        for g in s["grades"]
        if g["kind"] == "model_graded"
    )


def test_image_context_scope_does_not_hide_wrong_selection_or_missing_assets(tmp_path):
    from evals.conversation_runner import run_image_context
    from evals.conversations import load_conversations

    row = next(
        r for r in load_conversations(FIXTURES) if r.id == "new-image-review-conversation"
    )
    for i, name in enumerate(dict.fromkeys(n for m in row.messages for n in m.images)):
        (tmp_path / name).write_bytes(str(i).encode())
    result = run_image_context(
        [row],
        assets_dir=tmp_path,
        samples=1,
        select=lambda *_: {"target_image_ids": [1], "ambiguous": False},
    )[0]
    correction = result["checks"][1]["samples"][0]
    assert correction["status"] == "fail"
    assert (
        next(g for g in correction["grades"] if g["id"] == "selected_images_set_eq")[
            "status"
        ]
        == "fail"
    )
    (tmp_path / row.messages[2].images[0]).unlink()
    result = run_image_context([row], assets_dir=tmp_path, samples=1)[0]
    assert not result["checks"][0]["samples"][0]["passed"]
    assert result["checks"][0]["samples"][0]["status"] == "error"


def test_image_context_scope_detects_prior_assistant_pollution_even_with_correct_pixels(
    tmp_path, monkeypatch
):
    from evals.conversation_runner import run_image_context
    from evals.conversations import load_conversations
    from app.application.workflows import image_target

    row = next(
        r for r in load_conversations(FIXTURES) if r.id == "new-image-review-conversation"
    )
    row.checks = [row.checks[0]]
    for i, name in enumerate(dict.fromkeys(n for m in row.messages for n in m.images)):
        (tmp_path / name).write_bytes(str(i).encode())
    original = image_target.prepare_images

    def polluted(window, images, **kwargs):
        prepared = original(window, images, **kwargs)
        prepared.window.append(
            next(view for view in window if view["author"] == "companion")
        )
        return prepared

    monkeypatch.setattr(image_target, "prepare_images", polluted)
    result = run_image_context([row], assets_dir=tmp_path, samples=1)[0]
    assert (
        next(
            g
            for g in result["checks"][0]["samples"][0]["grades"]
            if g["id"] == "scope_history_isolated"
        )["status"]
        == "fail"
    )
