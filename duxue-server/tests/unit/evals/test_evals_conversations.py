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
    from evals.conversation_runner import run_conversations
    from evals.conversations import load_conversations, turn_case
    from evals.runner import Backends
    from tests.support.fakes import StaticLeakJudge, StaticTutorModel, tutor_raw
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
    from evals.conversation_runner import run_conversations
    from evals.conversations import load_conversations
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


def test_v1_cannot_silently_claim_multimodal_support_and_v2_preserves_images():
    from evals.conversations import ConversationEval, turn_case
    row = _row()
    row['messages'][0]['images'] = ['img-aaaaaaaaaaaa.jpg']
    with pytest.raises(ValueError):
        ConversationEval.model_validate(row)
    row['schema_version'] = 'conversation-eval.v2'
    parsed = ConversationEval.model_validate(row)
    case = turn_case(parsed, parsed.checks[0])
    assert case.history[0].images == ['img-aaaaaaaaaaaa.jpg']


def test_real_image_incident_preserves_original_error_and_new_target_expectations():
    from evals.conversations import load_conversations, turn_case
    row = next(row for row in load_conversations() if row.id == 'new-image-review-conversation')
    assert row.schema_version == 'conversation-eval.v2'
    assert len(row.messages) == 8 and len(row.attempts) == 6
    assert row.messages[0].images != row.messages[2].images
    for check in [check for check in row.checks if check.component == 'tutoring.turn']:
        case = turn_case(row, check)
        assert case.expect.selected_images
        assert any(message.images for message in case.history) or case.images
    repair = next(attempt for attempt in row.attempts if attempt.id == 'attempt-1-1')
    assert repair.shown_to_user and not repair.gate.observed_verdict.leaks
    assert repair.repair_feedback is None and repair.repair_feedback_status == 'unavailable'
    check = next(check for check in row.checks if getattr(check, 'attempt_id', None) == repair.id)
    assert check.expect.leaks and check.expect.reason == 'premature_conclusion'


def test_v2_preserves_picture_only_messages_without_inventing_student_text():
    from evals.conversations import ConversationEval
    row = _row()
    row['schema_version'] = 'conversation-eval.v2'
    row['messages'][0]['content'] = ''
    row['messages'][0]['images'] = ['img-aaaaaaaaaaaa.jpg']
    parsed = ConversationEval.model_validate(row)
    assert parsed.messages[0].content == ''

@pytest.mark.parametrize('change', ['v1', 'no_retry', 'fabricated'])
def test_unavailable_original_feedback_cannot_hide_observed_or_fabricated_data(change):
    from evals.conversations import ConversationEval
    row = dataset.read_object(dataset.DATA_DIR / 'conversation_replay/new-image-review-conversation.json')
    retry = next(a for a in row['attempts'] if a.get('repair_feedback_status') == 'unavailable')
    if change == 'v1':
        row['schema_version'] = 'conversation-eval.v1'
        for m in row['messages']: m.pop('images', None)
        for a in row['attempts']: a['gate']['input'].pop('images', None)
        for c in row['checks']: c['expect'].pop('selected_images', None)
    elif change == 'no_retry':
        retry['retry_of'] = None
    else:
        retry['repair_feedback'] = 'invented feedback'
    with pytest.raises(ValueError, match='unavailable feedback'):
        ConversationEval.model_validate(row)


def test_image_context_scope_checks_real_targets_without_running_math_or_changing_history(tmp_path):
    from evals.conversation_runner import run_image_context
    from evals.conversations import load_conversations
    row = next(r for r in load_conversations() if r.id == 'new-image-review-conversation')
    original = row.model_dump()
    for i, name in enumerate(dict.fromkeys(n for m in row.messages for n in m.images)):
        (tmp_path / name).write_bytes(str(i).encode())
    calls = []
    def select(window, content):
        calls.append(content)
        return {'target_image_ids': [2], 'ambiguous': False}
    result = run_image_context([row], samples=1, assets_dir=tmp_path, select=select)[0]
    assert len(result['checks']) == 3
    assert len(result['excluded_checks']) == 6
    assert all(s['passed'] for c in result['checks'] for s in c['samples'])
    assert calls == ['这不是同一个图片，这是一个新的图片。']
    assert row.model_dump() == original
    assert all(s['semantic_status'] == 'image_context_only' for c in result['checks'] for s in c['samples'])


def test_image_context_scope_does_not_hide_wrong_selection_or_missing_assets(tmp_path):
    from evals.conversation_runner import run_image_context
    from evals.conversations import load_conversations
    row = next(r for r in load_conversations() if r.id == 'new-image-review-conversation')
    for i, name in enumerate(dict.fromkeys(n for m in row.messages for n in m.images)):
        (tmp_path / name).write_bytes(str(i).encode())
    result = run_image_context([row], assets_dir=tmp_path, samples=1,
                              select=lambda *_: {'target_image_ids': [1], 'ambiguous': False})[0]
    correction = result['checks'][1]['samples'][0]
    assert not correction['passed'] and 'selected_images_mismatch' in correction['failures']
    (tmp_path / row.messages[2].images[0]).unlink()
    result = run_image_context([row], assets_dir=tmp_path, samples=1)[0]
    assert not result['checks'][0]['samples'][0]['passed']
    assert result['checks'][0]['samples'][0]['failures'][0].startswith('missing_asset:')


def test_image_context_scope_detects_prior_assistant_pollution_even_with_correct_pixels(tmp_path, monkeypatch):
    from evals.conversation_runner import run_image_context
    from evals.conversations import load_conversations
    from app.application.workflows import image_target
    row = next(r for r in load_conversations() if r.id == 'new-image-review-conversation')
    row.checks = [row.checks[0]]
    for i, name in enumerate(dict.fromkeys(n for m in row.messages for n in m.images)):
        (tmp_path / name).write_bytes(str(i).encode())
    original = image_target.prepare_images
    def polluted(window, images, **kwargs):
        prepared = original(window, images, **kwargs)
        prepared.window.append(next(view for view in window if view['author'] == 'companion'))
        return prepared
    monkeypatch.setattr(image_target, 'prepare_images', polluted)
    result = run_image_context([row], assets_dir=tmp_path, samples=1)[0]
    assert result['checks'][0]['samples'][0]['failures'] == ['prior_image_reply_retained']
