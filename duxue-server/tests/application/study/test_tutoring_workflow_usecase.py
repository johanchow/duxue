from __future__ import annotations

import pytest

from app.ai_agents.tutoring_workflow import TutoringWorkflow
from app.ai_runtime.contracts import RunInvocation
from app.models import OutboxEvent, TutoringMessage, TutoringSession, uid
from tests.support.factories import create_ward, create_task, create_study_session


def test_tutoring_workflow_step_by_step_and_close(db):
    """答疑工作流用例：提问 -> 确认理解 -> 关闭会话，全流程产生对应领域事件。"""
    ward = create_ward(db)
    task = create_task(db, ward=ward, title="初中代数")
    session = create_study_session(db, ward=ward, task=task)
    db.commit()

    workflow = TutoringWorkflow(db)

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
    assert "tutoring.ward_attempt_recorded" in event_types_1
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
