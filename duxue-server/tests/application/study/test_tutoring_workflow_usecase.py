from __future__ import annotations

import pytest

from app.application.workflows.tutoring_workflow import TutoringWorkflow
from app.application.ports.companion import RunInvocation
from app.infrastructure.ai.model_gateway import AgentTextCandidate
from app.infrastructure.persistence.models import (
    CompanionCommand, CompanionMessage, ConversationThread, OutboxEvent, StudySession, TutoringMessage, TutoringSession, uid,
)
from tests.support.factories import create_ward, create_task, create_study_session
from tests.support.fakes import StaticTutoringIntent


def test_tutoring_workflow_step_by_step_and_close(db):
    """答疑工作流用例：提问 -> 确认理解 -> 关闭会话，全流程产生对应领域事件。"""
    ward = create_ward(db)
    task = create_task(db, ward=ward, title="初中代数")
    session = create_study_session(db, ward=ward, task=task)
    db.commit()

    workflow = TutoringWorkflow(db, intent_proposer=StaticTutoringIntent())

    # 1. 第一轮提问
    turn1_invocation = RunInvocation(
        run_id=uid(),
        thread_id=uid(),
        ward_id=ward.id,
        agent_type="tutoring",
        turn={"study_session_id": session.id, "content": "这道二元一次方程怎么消元？", "tutoring_directive": "ask"},
    )
    outcome1 = workflow.invoke(turn1_invocation)
    db.commit()

    assert outcome1.run_status == "waiting_for_ward"
    assert outcome1.next_interaction["hint_level"] == 1
    tutor_session = db.query(TutoringSession).filter_by(study_session_id=session.id).one()
    assert tutor_session.status == "active"

    # 检查 Outbox 生成的两个事件 (attempt, hint)
    outbox_events_1 = db.query(OutboxEvent).all()
    event_types_1 = [e.payload.get("event_type") for e in outbox_events_1]
    assert "tutoring.attempt_recorded" in event_types_1
    assert "tutoring.hint_given" in event_types_1

    # 2. 学生确认理解了当前步骤
    turn2_invocation = RunInvocation(
        run_id=uid(),
        thread_id=uid(),
        ward_id=ward.id,
        agent_type="tutoring",
        turn={"study_session_id": session.id, "content": "我明白了，把y代入第一个式子", "tutoring_directive": "understood"},
    )
    outcome2 = workflow.invoke(turn2_invocation)
    db.commit()

    assert outcome2.run_status == "waiting_for_ward"
    outbox_events_2 = db.query(OutboxEvent).all()
    event_types_2 = [e.payload.get("event_type") for e in outbox_events_2]
    assert "tutoring.understanding_confirmed" in event_types_2

    # 3. 关闭会话
    turn3_invocation = RunInvocation(
        run_id=uid(),
        thread_id=uid(),
        ward_id=ward.id,
        agent_type="tutoring",
        turn={"study_session_id": session.id, "tutoring_directive": "close"},
    )
    outcome3 = workflow.invoke(turn3_invocation)
    db.commit()

    assert outcome3.run_status == "closed"
    assert outcome3.outcome_type == "completed"

    tutor_session_closed = db.get(TutoringSession, tutor_session.id)
    assert tutor_session_closed.status == "closed"
    assert tutor_session_closed.closed_at is not None

    outbox_events_3 = db.query(OutboxEvent).all()
    event_types_3 = [e.payload.get("event_type") for e in outbox_events_3]
    assert "tutoring.session_closed" in event_types_3


def test_a_new_question_stays_at_level_one_after_earlier_questions(db):
    ward = create_ward(db)
    task = create_task(db, ward=ward, title="科学")
    session = create_study_session(db, ward=ward, task=task)
    db.commit()
    workflow = TutoringWorkflow(db, intent_proposer=StaticTutoringIntent())
    for content in ("铁木真统一了蒙古的什么？", "五的英语单词是什么？", "任务的英语单词是什么？"):
        workflow.invoke(RunInvocation(
            run_id=uid(), thread_id=uid(), ward_id=ward.id, agent_type="tutoring",
            turn={"study_session_id": session.id, "content": content, "tutoring_directive": "ask"},
        ))
    outcome = workflow.invoke(RunInvocation(
        run_id=uid(), thread_id=uid(), ward_id=ward.id, agent_type="tutoring",
        turn={"study_session_id": session.id, "content": "为什么穿湿的衣服会越来越冷？", "tutoring_directive": "ask"},
    ))
    db.commit()
    assert outcome.next_interaction["hint_level"] == 1
    assert "已知条件和下一步" not in outcome.next_interaction["content"]


def test_tutoring_without_session_opens_a_taskless_session_and_replies(db):
    ward = create_ward(db)
    db.commit()
    outcome = TutoringWorkflow(db, intent_proposer=StaticTutoringIntent()).invoke(RunInvocation(
        run_id=uid(), thread_id=uid(), ward_id=ward.id, agent_type="tutoring",
        turn={"content": "铁木真统一了蒙古的什么？", "tutoring_directive": "ask"},
    ))
    db.commit()
    assert outcome.next_interaction["content"]
    session = db.query(StudySession).filter_by(ward_id=ward.id).one()
    assert session.task_id is None
    assert session.status == "active"


def test_hint_reply_includes_the_recent_window(db, monkeypatch):
    ward = create_ward(db)
    thread = ConversationThread(ward_id=ward.id)
    db.add(thread)
    db.flush()
    command = CompanionCommand(id=uid(), ward_id=ward.id, thread_id=thread.id, payload_digest="prior")
    db.add(command)
    db.flush()
    db.add(CompanionMessage(
        ward_id=ward.id, thread_id=thread.id, command_id=command.id,
        turn_id=uid(), attempt=1, thread_version=1, author_type="companion",
        content="1. diamond beach\n2. kling beach",
    ))
    db.commit()
    seen: dict[str, str] = {}

    def generate(self, *, agent_type, envelope, instruction):
        seen["instruction"] = instruction
        return AgentTextCandidate(content="你说的是上面列出的哪一句？")

    monkeypatch.setattr(
        "app.application.workflows.tutoring_workflow.QwenAgentModelGateway.generate",
        generate,
    )
    proposer = StaticTutoringIntent("curiosity")
    outcome = TutoringWorkflow(db, intent_proposer=proposer).invoke(RunInvocation(
        run_id=uid(), thread_id=thread.id, ward_id=ward.id, agent_type="tutoring",
        turn={"content": "他们都是什么意思", "tutoring_directive": "ask"},
    ))
    assert "diamond beach" in seen["instruction"]
    assert "追问" in seen["instruction"]
    assert "他们都是什么意思" not in proposer.windows[0][0]["text"]
    assert outcome.next_interaction["content"] == "你说的是上面列出的哪一句？"
