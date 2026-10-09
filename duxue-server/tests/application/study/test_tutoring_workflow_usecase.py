from __future__ import annotations

import pytest

from app.application.ports.companion import RunInvocation
from app.application.workflows.tutoring_workflow import TutoringWorkflow
from app.infrastructure.persistence.models import (
    CompanionCommand, CompanionMessage, ConversationThread, OutboxEvent, StudySession, TutoringMessage,
    TutoringProblem, TutoringSession, uid,
)
from tests.support.factories import create_ward, create_task, create_study_session
from tests.support.fakes import StaticLeakJudge, StaticTutorModel, tutor_raw

ATTEMPT = tutor_raw(act="hint", student_turn_kind="attempt", progress="none")
KNOWLEDGE = tutor_raw(
    act="answer", question_kind="knowledge_lookup", content="diamond beach 的中文意思是钻石海滩。",
    student_turn_kind="other", same_problem=False, is_assignment_content=False,
)


def _events(db):
    return [e.payload.get("event_type") for e in db.query(OutboxEvent).all()]


def _ask(db, workflow, session, content="这道题怎么做", **turn):
    outcome = workflow.invoke(RunInvocation(
        run_id=uid(), thread_id=uid(), ward_id=session.ward_id, agent_type="tutoring",
        turn={"study_session_id": session.id, "content": content, "tutoring_directive": "ask", **turn},
    ))
    db.commit()
    return outcome


def _setup(db, title="初中代数"):
    ward = create_ward(db)
    session = create_study_session(db, ward=ward, task=create_task(db, ward=ward, title=title))
    db.commit()
    return ward, session


def _workflow(db, *raws, judge=None):
    model = StaticTutorModel(*raws)
    return TutoringWorkflow(db, turn_model=model, leak_judge=judge or StaticLeakJudge(False)), model


def test_tutoring_workflow_step_by_step_and_close(db):
    ward, session = _setup(db)
    workflow, _ = _workflow(db, ATTEMPT)

    outcome1 = _ask(db, workflow, session, "我先把 y 代入第一个式子，得到 3")
    assert outcome1.run_status == "waiting_for_ward"
    assert outcome1.next_interaction["hint_index"] == 1
    assert db.query(TutoringSession).filter_by(study_session_id=session.id).one().status == "active"
    assert "tutoring.attempt_recorded" in _events(db)
    assert "tutoring.hint_given" in _events(db)

    outcome2 = _ask(db, workflow, session, "我明白了", tutoring_directive="understood")
    assert outcome2.next_interaction["status"] == "understood"
    assert "tutoring.understanding_confirmed" in _events(db)

    outcome3 = _ask(db, workflow, session, tutoring_directive="close")
    assert outcome3.run_status == "closed"
    tutor = db.query(TutoringSession).filter_by(study_session_id=session.id).one()
    assert tutor.status == "closed" and tutor.closed_at is not None
    assert "tutoring.session_closed" in _events(db)


def test_locked_refuses_a_solution_and_writes_nothing(db):
    _, session = _setup(db)
    workflow, _ = _workflow(db, tutor_raw(act="answer", reveals_solution=True, content="答案是 5"))
    outcome = _ask(db, workflow, session, "直接告诉我答案")
    assert outcome.next_interaction["model_fallback"] is True
    assert "答案是 5" not in outcome.next_interaction["content"]
    assert _events(db) == []
    assert db.query(TutoringProblem).count() == 0


def test_two_attempts_without_progress_unlock_the_next_round(db):
    _, session = _setup(db)
    workflow, model = _workflow(db, ATTEMPT)
    _ask(db, workflow, session, "我觉得是 3")
    second = _ask(db, workflow, session, "那是 4")
    # 第二次尝试的这一轮仍按 locked 校验，下一轮才是 unlocked。
    assert second.next_interaction["solution_state"] == "unlocked"
    assert '"solution": "locked"' in model.calls[1]["instruction"]
    _ask(db, workflow, session, "还是不会")
    assert '"solution": "unlocked"' in model.calls[2]["instruction"]


def test_unlocked_reveal_needs_a_verification_question(db):
    _, session = _setup(db)
    workflow, _ = _workflow(db, ATTEMPT)
    _ask(db, workflow, session, "3")
    _ask(db, workflow, session, "4")
    reveal = tutor_raw(act="answer", reveals_solution=True, content="先消元得到 x=2，再代入。", student_turn_kind="ask_answer")
    workflow.turn_model = StaticTutorModel(reveal)
    rejected = _ask(db, workflow, session, "讲给我听")
    assert rejected.next_interaction["model_fallback"] is True
    workflow.turn_model = StaticTutorModel({**reveal, "follow_up_question": "把 x=2 代回去检验一下？"})
    accepted = _ask(db, workflow, session, "讲给我听")
    assert accepted.next_interaction["model_fallback"] is False
    assert "检验" in accepted.next_interaction["content"]


def test_asking_for_the_answer_without_attempts_never_unlocks(db):
    _, session = _setup(db)
    workflow, model = _workflow(db, tutor_raw(act="probe", student_turn_kind="ask_answer"))
    for _ in range(4):
        _ask(db, workflow, session, "告诉我答案")
    problem = db.query(TutoringProblem).one()
    assert problem.solution_state == "locked" and problem.substantive_attempts == 0


def test_solved_attempt_ends_the_problem_without_confirming_understanding(db):
    _, session = _setup(db)
    workflow, _ = _workflow(db, tutor_raw(act="confirm", student_turn_kind="attempt", progress="solved", content="对，x=2。"))
    outcome = _ask(db, workflow, session, "x=2")
    assert outcome.next_interaction["solution_state"] == "solved"
    assert "tutoring.understanding_confirmed" not in _events(db)


def test_confirm_without_solved_is_rejected(db):
    _, session = _setup(db)
    workflow, _ = _workflow(db, tutor_raw(act="confirm", student_turn_kind="attempt", progress="some", content="你已经懂了"))
    assert _ask(db, workflow, session).next_interaction["model_fallback"] is True


def test_new_problem_starts_locked(db):
    _, session = _setup(db)
    workflow, _ = _workflow(db, ATTEMPT)
    _ask(db, workflow, session, "3")
    _ask(db, workflow, session, "4")
    workflow.turn_model = StaticTutorModel(tutor_raw(act="hint", student_turn_kind="ask_hint", same_problem=False))
    _ask(db, workflow, session, "再看另一道题")
    rows = db.query(TutoringProblem).order_by(TutoringProblem.created_at).all()
    assert [r.status for r in rows] == ["abandoned", "open"]
    assert rows[1].solution_state == "locked" and rows[1].substantive_attempts == 0


def test_replayed_turn_counts_the_attempt_once(db):
    _, session = _setup(db)
    workflow, _ = _workflow(db, ATTEMPT)
    invocation = RunInvocation(
        run_id=uid(), thread_id=uid(), ward_id=session.ward_id, agent_type="tutoring",
        turn={"study_session_id": session.id, "content": "我觉得是 3", "tutoring_directive": "ask"},
    )
    workflow.invoke(invocation)
    workflow.invoke(invocation)
    assert db.query(TutoringProblem).one().substantive_attempts == 1


def test_leak_check_blocks_a_locked_reply_and_fails_closed(db):
    _, session = _setup(db)
    for verdict in (True, None):
        workflow, _ = _workflow(db, tutor_raw(act="hint", content="x 就是 2"), judge=StaticLeakJudge(verdict))
        outcome = _ask(db, workflow, session)
        assert outcome.next_interaction["model_fallback"] is True
    assert _events(db) == []


def test_knowledge_question_is_answered_directly_without_leak_check_or_problem(db):
    _, session = _setup(db, "英语阅读")
    judge = StaticLeakJudge(True)
    workflow = TutoringWorkflow(db, turn_model=StaticTutorModel(tutor_raw(
        act="hint", question_kind="knowledge_lookup", content="这是用相机拍的。", student_turn_kind="other",
        same_problem=False, is_assignment_content=False,
    )), leak_judge=judge)
    outcome = _ask(db, workflow, session, "这张图是哪个 App 拍的")
    assert judge.calls == 0
    assert db.query(TutoringProblem).count() == 0
    assert "tutoring.curiosity_observed" in _events(db)
    assert "tutoring.hint_given" not in _events(db)
    assert outcome.next_interaction["model_fallback"] is False


def test_open_problem_tightens_a_mislabeled_followup(db):
    _, session = _setup(db)
    workflow, _ = _workflow(db, ATTEMPT)
    _ask(db, workflow, session, "我觉得是 3")
    mislabeled = tutor_raw(
        act="answer", question_kind="knowledge_lookup", is_assignment_content=False, same_problem=True,
        student_turn_kind="ask_answer", reveals_solution=False, content="答案是 5",
    )
    workflow.turn_model = StaticTutorModel(mislabeled)
    outcome = _ask(db, workflow, session, "那答案呢")
    assert outcome.next_interaction["model_fallback"] is True


def test_history_ref_outside_the_candidates_is_dropped_not_rejected(db):
    _, session = _setup(db)
    workflow, _ = _workflow(db, tutor_raw(act="hint", history_ref="u99"))
    assert _ask(db, workflow, session).next_interaction["model_fallback"] is False


def test_a_task_session_gets_the_reminder_after_a_knowledge_answer(db):
    _, session = _setup(db, "英语的典范故事阅读")
    workflow, model = _workflow(db, KNOWLEDGE)
    outcome = _ask(db, workflow, session, "diamond beach 是什么意思")
    assert "钻石海滩" in outcome.next_interaction["content"]
    assert "先回到正在进行的任务" in outcome.next_interaction["content"]
    assert '"must_remind_task": true' in model.calls[0]["instruction"]
    assert "英语的典范故事阅读" in model.calls[0]["instruction"]


def test_structure_error_retries_once_then_falls_back(db):
    _, session = _setup(db)
    model = StaticTutorModel({"act": "hint"})
    workflow = TutoringWorkflow(db, turn_model=model, leak_judge=StaticLeakJudge())
    outcome = _ask(db, workflow, session)
    assert len(model.calls) == 2 and model.calls[1]["repair_error"]
    assert outcome.next_interaction["model_fallback"] is True
    assert _events(db) == []


def test_tutoring_without_session_opens_a_taskless_session_and_replies(db):
    ward = create_ward(db)
    db.commit()
    workflow = TutoringWorkflow(db, turn_model=StaticTutorModel(KNOWLEDGE), leak_judge=StaticLeakJudge())
    outcome = workflow.invoke(RunInvocation(
        run_id=uid(), thread_id=uid(), ward_id=ward.id, agent_type="tutoring",
        turn={"content": "铁木真统一了蒙古的什么？", "tutoring_directive": "ask"},
    ))
    db.commit()
    assert outcome.next_interaction["content"]
    session = db.query(StudySession).filter_by(ward_id=ward.id).one()
    assert session.task_id is None and session.status == "active"
    assert "先回到正在进行的任务" not in outcome.next_interaction["content"]


def test_the_window_reaches_the_model_and_history_is_authorized(db):
    ward = create_ward(db)
    thread = ConversationThread(ward_id=ward.id)
    db.add(thread)
    db.flush()
    command = CompanionCommand(id=uid(), ward_id=ward.id, thread_id=thread.id, payload_digest="prior")
    db.add(command)
    db.flush()
    db.add(CompanionMessage(
        ward_id=ward.id, thread_id=thread.id, command_id=command.id, turn_id=uid(), attempt=1,
        thread_version=1, author_type="companion", content="1. diamond beach\n2. kling beach",
    ))
    db.commit()
    model = StaticTutorModel(tutor_raw(
        act="clarify", question_kind="knowledge_lookup", content="你说的是上面列出的哪一句？",
        student_turn_kind="other", same_problem=False, is_assignment_content=False,
    ))
    outcome = TutoringWorkflow(db, turn_model=model, leak_judge=StaticLeakJudge()).invoke(RunInvocation(
        run_id=uid(), thread_id=thread.id, ward_id=ward.id, agent_type="tutoring",
        turn={"content": "他们都是什么意思", "tutoring_directive": "ask"},
    ))
    assert "diamond beach" in model.calls[0]["recent_utterances"][0]["text"]
    assert "diamond beach" in model.calls[0]["instruction"]  # 授权历史候选
    assert "你说的是上面列出的哪一句？" in outcome.next_interaction["content"]
    assert db.query(StudySession).count() == 0


def test_model_can_read_the_attempt_summary_through_a_tool(db):
    _, session = _setup(db)
    workflow, model = _workflow(db, ATTEMPT)
    _ask(db, workflow, session, "我觉得是 3")
    workflow.turn_model = model = StaticTutorModel(
        {"tool": "get_attempt_summary", "args": {}}, tutor_raw(act="hint"),
    )
    outcome = _ask(db, workflow, session, "再提示一下")
    assert len(model.calls) == 2
    seen = model.calls[1]["observations"][0]
    assert seen["tool"] == "get_attempt_summary" and seen["substantive_attempts"] == 1
    assert outcome.next_interaction["model_fallback"] is False


def test_tool_budget_and_unknown_tools_are_bounded(db):
    _, session = _setup(db)
    loop = {"tool": "get_task_context", "args": {}}
    workflow, model = _workflow(db, loop, loop, loop, {"tool": "delete_everything"}, tutor_raw())
    outcome = _ask(db, workflow, session)
    # 3 次工具后，第 4 次主调用仍要工具，预算耗尽，回退。
    assert len(model.calls) == 4
    assert outcome.next_interaction["model_fallback"] is True
    assert model.calls[3]["observations"][2]["tool"] == "get_task_context"


def test_unknown_tool_is_a_typed_error_observation(db):
    _, session = _setup(db)
    workflow, model = _workflow(db, {"tool": "delete_everything"}, tutor_raw())
    outcome = _ask(db, workflow, session)
    assert model.calls[1]["observations"][0]["status"] == "tool_error"
    assert outcome.next_interaction["model_fallback"] is False


def test_history_ref_from_lookup_history_is_authorized(db):
    _, session = _setup(db)
    workflow, _ = _workflow(db, ATTEMPT)
    _ask(db, workflow, session, "我觉得是 3 因为 y 等于 1")
    workflow.turn_model = model = StaticTutorModel(
        {"tool": "lookup_history", "args": {"query": "y 等于"}}, tutor_raw(act="hint", history_ref="u0"),
    )
    _ask(db, workflow, session, "再提示一下")
    obs = model.calls[1]["observations"][0]
    assert obs["status"] == "unique" and obs["matches"][0]["ref"].startswith("m:")
