from __future__ import annotations

import pytest
from fastapi import HTTPException

from app.application.workflows.tutoring_workflow import TutoringWorkflow
from app.application.ports.companion import RunInvocation
from app.infrastructure.persistence.models import TutoringMessage, TutoringSession, uid
from tests.support.fakes import StaticLeakJudge, StaticTutorModel, tutor_raw
from tests.support.factories import create_ward, create_task, create_study_session


KNOWLEDGE = tutor_raw(
    act="answer", question_kind="knowledge_lookup", content="蚂蚁靠气味信息素找路。",
    student_turn_kind="other", same_problem=False, is_assignment_content=False,
)


def test_cannot_access_another_wards_study_session(db):
    """学生不能向属于其他学生的学习会话发起答疑。"""
    ward1 = create_ward(db, display_name="学生甲")
    ward2 = create_ward(db, display_name="学生乙")
    task2 = create_task(db, ward=ward2, title="乙的任务")
    session2 = create_study_session(db, ward=ward2, task=task2)
    db.commit()

    workflow = TutoringWorkflow(db, turn_model=StaticTutorModel(), leak_judge=StaticLeakJudge())
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

    workflow = TutoringWorkflow(db, turn_model=StaticTutorModel(), leak_judge=StaticLeakJudge())
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


def test_hint_index_counts_hints_on_one_problem(db):
    """同一道题的提示按次数计，不再有等级和封顶。"""
    ward = create_ward(db)
    task = create_task(db, ward=ward, title="奥数题")
    session = create_study_session(db, ward=ward, task=task)
    db.commit()

    workflow = TutoringWorkflow(db, turn_model=StaticTutorModel(tutor_raw(act="hint")), leak_judge=StaticLeakJudge())
    for expected in (1, 2, 3, 4, 5):
        outcome = workflow.invoke(RunInvocation(
            run_id=uid(), thread_id=uid(), ward_id=ward.id, agent_type="tutoring",
            turn={"study_session_id": session.id, "content": "还是不理解", "tutoring_directive": "ask"},
        ))
        assert outcome.next_interaction["hint_index"] == expected


def test_off_task_question_during_a_task_stays_brief_and_keeps_the_session(db):
    """任务进行中问了别的：简短回答并提醒回任务，不结束原来的学习会话。"""
    ward = create_ward(db)
    task = create_task(db, ward=ward, title="数学练习")
    session = create_study_session(db, ward=ward, task=task)
    db.commit()

    outcome = TutoringWorkflow(db, turn_model=StaticTutorModel(KNOWLEDGE), leak_judge=StaticLeakJudge()).invoke(
        RunInvocation(
            run_id=uid(),
            thread_id=uid(),
            ward_id=ward.id,
            agent_type="tutoring",
            turn={
                "study_session_id": session.id,
                "content": "蚂蚁为什么排成一条线",
            },
        )
    )
    db.refresh(session)
    assert session.status == "active"
    assert outcome.next_interaction["return_to_task"] is True
    assert "先回到正在进行的任务" in outcome.next_interaction["content"]


def test_taskless_curiosity_does_not_ask_to_return(db):
    ward = create_ward(db)
    session = create_study_session(db, ward=ward, task=None)
    db.commit()

    outcome = TutoringWorkflow(db, turn_model=StaticTutorModel(KNOWLEDGE), leak_judge=StaticLeakJudge()).invoke(
        RunInvocation(
            run_id=uid(),
            thread_id=uid(),
            ward_id=ward.id,
            agent_type="tutoring",
            turn={
                "study_session_id": session.id,
                "content": "蚂蚁为什么排成一条线",
            },
        )
    )
    assert outcome.next_interaction["return_to_task"] is False
    assert "先回到正在进行的任务" not in outcome.next_interaction["content"]


def test_safety_candidate_is_replaced_by_the_safe_text_and_writes_no_fact(db):
    ward = create_ward(db)
    task = create_task(db, ward=ward, title="语文练习")
    session = create_study_session(db, ward=ward, task=task)
    db.commit()

    model = StaticTutorModel(tutor_raw(
        act="answer", question_kind="safety", content="模型自己写的话", student_turn_kind="other",
        same_problem=False, is_assignment_content=False,
    ))
    outcome = TutoringWorkflow(db, turn_model=model, leak_judge=StaticLeakJudge()).invoke(RunInvocation(
        run_id=uid(), thread_id=uid(), ward_id=ward.id, agent_type="tutoring",
        turn={"study_session_id": session.id, "content": "我不想活了"},
    ))
    assert outcome.next_interaction["safety_blocked"] is True
    assert "模型自己写的话" not in outcome.next_interaction["content"]
    messages = db.query(TutoringMessage).order_by(TutoringMessage.created_at.asc()).all()
    assert len(messages) == 2
    assert messages[1].safety_blocked is True
    from app.infrastructure.persistence.models import OutboxEvent
    assert db.query(OutboxEvent).count() == 0
