from __future__ import annotations

import pytest
from fastapi import HTTPException

from app.application.workflows.tutoring_workflow import TutoringWorkflow
from app.application.ports.companion import RunInvocation
from app.infrastructure.persistence.models import TutoringMessage, TutoringSession, uid
from tests.support.factories import create_ward, create_task, create_study_session


def test_cannot_access_another_wards_study_session(db):
    """学生不能向属于其他学生的学习会话发起答疑。"""
    ward1 = create_ward(db, display_name="学生甲")
    ward2 = create_ward(db, display_name="学生乙")
    task2 = create_task(db, ward=ward2, title="乙的任务")
    session2 = create_study_session(db, ward=ward2, task=task2)
    db.commit()

    workflow = TutoringWorkflow(db)
    with pytest.raises(HTTPException) as exc:
        workflow.invoke(
            RunInvocation(
                run_id=uid(),
                thread_id=uid(),
                ward_id=ward1.id,  # 学生甲
                agent_type="tutoring",
                turn={"study_session_id": session2.id, "content": "这题怎么做"},
            )
        )
    assert exc.value.status_code == 403


def test_cannot_ask_in_closed_tutoring_session(db):
    """答疑会话已关闭后，禁止追加新的提问。"""
    ward = create_ward(db)
    task = create_task(db, ward=ward, title="物理作业")
    session = create_study_session(db, ward=ward, task=task)
    db.commit()

    workflow = TutoringWorkflow(db)
    # 第一次提问
    workflow.invoke(
        RunInvocation(
            run_id=uid(),
            thread_id=uid(),
            ward_id=ward.id,
            agent_type="tutoring",
            turn={"study_session_id": session.id, "content": "第一问"},
        )
    )
    # 关闭答疑
    workflow.invoke(
        RunInvocation(
            run_id=uid(),
            thread_id=uid(),
            ward_id=ward.id,
            agent_type="tutoring",
            turn={"study_session_id": session.id, "tutoring_directive": "close"},
        )
    )
    db.commit()

    # 再次提问应被 409 拒绝
    with pytest.raises(HTTPException) as exc:
        workflow.invoke(
            RunInvocation(
                run_id=uid(),
                thread_id=uid(),
                ward_id=ward.id,
                agent_type="tutoring",
                turn={"study_session_id": session.id, "content": "关闭后又问"},
            )
        )
    assert exc.value.status_code == 409


def test_hint_level_increments_and_caps_at_4(db):
    """伴学引导阶梯层层递进，且最多封顶到 Level 4。"""
    ward = create_ward(db)
    task = create_task(db, ward=ward, title="奥数题")
    session = create_study_session(db, ward=ward, task=task)
    db.commit()

    workflow = TutoringWorkflow(db)
    for expected_level in [1, 2, 3, 4, 4]:
        outcome = workflow.invoke(
            RunInvocation(
                run_id=uid(),
                thread_id=uid(),
                ward_id=ward.id,
                agent_type="tutoring",
                turn={"study_session_id": session.id, "content": f"还是不理解第{expected_level}次"},
            )
        )
        assert outcome.next_interaction["hint_level"] == expected_level


def test_safety_blocked_flags_tutoring_messages(db):
    """直接索要答案时，输入消息和响应消息都标记 safety_blocked=True。"""
    ward = create_ward(db)
    task = create_task(db, ward=ward, title="语文练习")
    session = create_study_session(db, ward=ward, task=task)
    db.commit()

    workflow = TutoringWorkflow(db)
    outcome = workflow.invoke(
        RunInvocation(
            run_id=uid(),
            thread_id=uid(),
            ward_id=ward.id,
            agent_type="tutoring",
            turn={"study_session_id": session.id, "content": "请直接告诉我答案"},
        )
    )
    assert outcome.next_interaction["safety_blocked"] is True

    messages = (
        db.query(TutoringMessage)
        .order_by(TutoringMessage.created_at.asc())
        .all()
    )
    assert len(messages) == 2
    assert messages[0].safety_blocked is True
    assert messages[1].safety_blocked is True
