from app.contexts.study.domain.execution import HintingPolicy, can_finish, should_auto_pause


def test_new_problem_starts_at_l1_and_l4_needs_three_failures():
    first = HintingPolicy.evaluate(failed_attempts=0, intent_label="problem", has_task=True, session_status="active")
    assert first.allowed_level == 1
    assert first.l4_walkthrough_allowed is False
    blocked = HintingPolicy.evaluate(failed_attempts=2, intent_label="problem", has_task=True, session_status="active")
    assert blocked.allowed_level == 3
    assert blocked.l4_walkthrough_allowed is False
    opened = HintingPolicy.evaluate(failed_attempts=3, intent_label="problem", has_task=True, session_status="active")
    assert opened.allowed_level == 4
    assert opened.l4_walkthrough_allowed is True


def test_answer_seeking_does_not_record_a_fact():
    decision = HintingPolicy.evaluate(failed_attempts=2, intent_label="answer_seeking", has_task=True, session_status="active")
    assert decision.record_fact is False
    assert decision.allowed_level == 1


def test_curiosity_during_a_task_asks_to_return_without_ending_it():
    decision = HintingPolicy.evaluate(failed_attempts=3, intent_label="curiosity", has_task=True, session_status="active")
    assert decision.return_to_task is True
    assert decision.allowed_level == 1
    assert decision.record_fact is True


def test_curiosity_without_a_task_does_not_ask_to_return():
    decision = HintingPolicy.evaluate(failed_attempts=0, intent_label="curiosity", has_task=False, session_status="active")
    assert decision.return_to_task is False


def test_display_rejects_final_answer_before_l4():
    early = HintingPolicy.evaluate(failed_attempts=0, intent_label="problem", has_task=True, session_status="active")
    assert HintingPolicy.accepts_display(early, "答案是 4") is False
    assert HintingPolicy.accepts_display(early, "先看看已知条件") is True


def test_l4_keeps_an_explanation_instead_of_requiring_magic_words():
    opened = HintingPolicy.evaluate(failed_attempts=3, intent_label="problem", has_task=False, session_status="active")
    explanation = "湿衣服上的水蒸发时会带走皮肤上的热量，所以会觉得更冷。"
    assert HintingPolicy.accepts_display(opened, explanation) is True


def test_finish_requires_a_task_and_long_sessions_pause():
    assert can_finish(None) is False
    assert can_finish("task-1") is True
    assert should_auto_pause(180 * 60) is True
    assert should_auto_pause(179 * 60) is False
