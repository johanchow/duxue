"""Real conversation snapshots stay fixed across checkpoints and samples."""
import copy
import pytest
from evals import dataset
from evals.__main__ import main


def _row():
    return dataset.read_object(dataset.DATA_DIR / "conversation_replay" / "answer-feedback-conversation.json")


def test_conversation_directory_validates_without_model_calls():
    from evals.conversations import load_conversations
    assert load_conversations()[0].id == "answer-feedback-conversation"
    assert main(["validate", "--category", "conversation_replay"]) == 0
    assert dataset.validate_layout() == []
    assert all(row.review_batch != "answer-feedback-v1" for row in dataset.load_cases())


@pytest.mark.parametrize("change", ["future", "retry_cycle", "delivery", "wrong_round", "duplicate", "unknown"])
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
        row["checks"][0]["expect"]["keyword_judge"] = True
    with pytest.raises(ValueError):
        ConversationEval.model_validate(row)


def test_fixed_history_and_snapshot_permit():
    from evals.conversations import load_conversations, turn_case
    from evals.conversation_runner import run_conversations
    from evals.runner import Backends
    from tests.support.fakes import StaticTutorModel, StaticLeakJudge, tutor_raw
    row = load_conversations()[0]
    first, second = [turn_case(row, c) for c in row.checks if c.component == "tutoring.turn"]
    assert first.student_said == "等于八。"
    assert second.student_said == "那你告诉我有没有算对？"
    assert second.history[-1].text == row.messages[7].content
    model = StaticTutorModel(tutor_raw("guide", "本次生成的新回复"))
    class Judge(StaticLeakJudge):
        def leaks(self, **kwargs):
            super().leaks(**kwargs)
            return {"leaks": False, "reason": "none"}
    result = run_conversations([row], Backends(tutor_model=model, leak_judge=Judge(False)), samples=2)
    assert len(result[0]["checks"]) == 5
    assert all("本次生成的新回复" not in str(call["recent_utterances"]) for call in model.calls)
    assert all(s["semantic_status"] == "pending_review" for c in result[0]["checks"][:2] for s in c["samples"])
    assert result[0]["checks"][0]["samples"][0]["passed"] is None
    assert first.context.problem.substantive_attempts == 1
    assert second.context.problem.substantive_attempts == 2


def test_fixed_gate_preserves_input_and_reports_wrong_reason_and_unavailable():
    from evals.conversations import load_conversations
    from evals.conversation_runner import run_conversations
    from evals.runner import Backends
    row = load_conversations()[0]
    row.checks = [row.checks[3]]
    received = []
    class Judge:
        def leaks(self, **kwargs):
            received.append(kwargs)
            return {"leaks": True, "reason": "incorrect_confirmation"} if len(received) == 1 else None
    samples = run_conversations([row], Backends(leak_judge=Judge()), samples=2)[0]["checks"][0]["samples"]
    assert samples[0]["failures"] == ["reason_mismatch"]
    assert samples[1]["failures"] == ["judge_unavailable"]
    original = row.attempts[1].gate.input
    assert received[0] == {"text": original.reply, "task_title": original.task_title, "problem_summary": original.problem}


def test_scope_snapshot_preserves_recent_problems_visual_and_scope_expectation():
    from evals.conversations import ConversationEval, turn_case
    row = _row()
    check = row['checks'][0]
    check['input_snapshot']['recent_problems'] = ['当前铅笔题', '较早苹果题']
    check['expect']['exit_gate']['answer_protected'] = False
    check['expect']['visual'] = 'present'
    check['expect']['visual_kind_in'] = ['compare']
    parsed = ConversationEval.model_validate(row)
    case = turn_case(parsed, parsed.checks[0])
    assert case.context.recent_problems == ['当前铅笔题', '较早苹果题']
    assert case.expect.answer_protected is False
    assert case.expect.visual == 'present' and case.expect.visual_kind_in == ['compare']


def test_replay_requires_the_expected_independent_scope_not_only_allow_verdict():
    from types import SimpleNamespace

    from evals.conversation_runner import verdict_failures
    expected = SimpleNamespace(leaks=False, reason='none', answer_protected=False)
    assert verdict_failures({'leaks': False, 'reason': 'none', 'answer_protected': True}, expected) == ['scope_mismatch']
    assert verdict_failures({'leaks': False, 'reason': 'none'}, expected) == ['scope_mismatch']


def test_original_rejected_attempts_remain_separate_from_visible_history_and_new_labels():
    from evals.conversations import load_conversations
    row = next(row for row in load_conversations() if row.id == "protection-scope-conversation")
    assert len(row.messages) == 12 and len(row.attempts) == 3
    for attempt in row.attempts:
        assert not attempt.shown_to_user and attempt.delivered_as is None
        assert attempt.gate.observed_verdict.leaks
        assert attempt.gate.observed_verdict.answer_protected is None  # Not present in the old schema.
        assert attempt.gate.observed_facts["new_final_answer"] is True
        assert attempt.gate.observed_facts["complete_solution"] is True
    gates = [check for check in row.checks if check.component == "tutoring.leak-judge"]
    assert len(gates) == 3
    assert all(not check.expect.leaks and check.expect.answer_protected is False for check in gates)
