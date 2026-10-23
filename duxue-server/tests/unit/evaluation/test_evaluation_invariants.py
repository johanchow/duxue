from __future__ import annotations

from sqlalchemy import inspect

from app.application.ports.companion import RunInvocation
from app.application.process_managers.companion_coordinator import CompanionCoordinator
from app.application.workflows.reflection_workflow import ReflectionWorkflow
from app.infrastructure.persistence.models import OutboxEvent, SelfReview, uid
from tests.support.factories import create_ward


def test_reflection_waits_for_self_review_input(db):
    """缺少复盘日期或体感输入时，工作流应保持 waiting_for_ward 状态。"""
    ward = create_ward(db)
    db.commit()

    workflow = ReflectionWorkflow(db)
    # 无 review_date
    outcome1 = workflow.invoke(
        RunInvocation(
            run_id=uid(),
            thread_id=uid(),
            ward_id=ward.id,
            agent_type="reflection",
            turn={},
        )
    )
    assert outcome1.run_status == "waiting_for_ward"
    assert outcome1.next_interaction["status"] == "needs_self_review"
    assert CompanionCoordinator._visible_outcome_content(outcome1)

    # 有 review_date 但无 review_feeling
    outcome2 = workflow.invoke(
        RunInvocation(
            run_id=uid(),
            thread_id=uid(),
            ward_id=ward.id,
            agent_type="reflection",
            turn={"review_date": "2026-09-12"},
        )
    )
    assert outcome2.run_status == "waiting_for_ward"
    assert outcome2.next_interaction["status"] == "needs_self_review"
    assert CompanionCoordinator._visible_outcome_content(outcome2)


def test_self_review_versioning_and_fact_emission(db):
    """重复修改自评时版本号自增，每次提交产生不同 source_version 的事实。"""
    ward = create_ward(db)
    db.commit()

    workflow = ReflectionWorkflow(db)
    review_date_str = "2026-09-12"

    # 第一次自评
    workflow.invoke(
        RunInvocation(
            run_id=uid(),
            thread_id=uid(),
            ward_id=ward.id,
            agent_type="reflection",
            turn={
                "review_date": review_date_str,
                "review_feeling": "stuck",
                "review_reflection": "卡在最后一题",
            },
        )
    )
    db.commit()

    review = db.query(SelfReview).filter_by(ward_id=ward.id).one()
    assert review.version == 1
    assert review.feeling == "stuck"

    # 修改自评
    workflow.invoke(
        RunInvocation(
            run_id=uid(),
            thread_id=uid(),
            ward_id=ward.id,
            agent_type="reflection",
            turn={
                "review_date": review_date_str,
                "review_feeling": "smooth",
                "review_reflection": "后来想通了",
            },
        )
    )
    db.commit()

    review_after = db.query(SelfReview).filter_by(ward_id=ward.id).one()
    assert review_after.version == 2
    assert review_after.feeling == "smooth"

    facts = [
        event.payload
        for event in db.query(OutboxEvent).all()
        if event.payload.get("event_type") == "self_review.submitted"
    ]
    assert facts == []


def test_self_review_does_not_emit_focus_kit_fact(db):
    """提交自述不会自动生成锦囊采纳事实。"""
    ward = create_ward(db)
    db.commit()

    workflow = ReflectionWorkflow(db)
    workflow.invoke(
        RunInvocation(
            run_id=uid(),
            thread_id=uid(),
            ward_id=ward.id,
            agent_type="reflection",
            turn={
                "review_date": "2026-09-12",
                "review_feeling": "smooth",
            },
        )
    )
    db.commit()
    adopted_facts = [
        event for event in db.query(OutboxEvent).all()
        if event.payload.get("event_type") == "focus_kit.adopted"
    ]
    assert adopted_facts == []


def test_retired_focus_kit_table_is_absent(db_engine):
    assert not inspect(db_engine).has_table("focus_kits")
