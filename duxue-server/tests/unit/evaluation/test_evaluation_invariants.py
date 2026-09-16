from __future__ import annotations

from datetime import date
import pytest

from app.application.workflows.reflection_workflow import ReflectionWorkflow
from app.application.ports.companion import RunInvocation
from app.infrastructure.persistence.models import OutboxEvent, SelfReview, FocusKit, uid
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
    assert len(facts) == 2
    assert [f["source_version"] for f in facts] == [1, 2]


def test_focus_kit_only_adopted_when_explicitly_requested(db):
    """仅当 adopt_focus_kit 为 True 时才沉淀锦囊采纳事实。"""
    ward = create_ward(db)
    db.commit()

    workflow = ReflectionWorkflow(db)
    # 不采纳锦囊
    workflow.invoke(
        RunInvocation(
            run_id=uid(),
            thread_id=uid(),
            ward_id=ward.id,
            agent_type="reflection",
            turn={
                "review_date": "2026-09-12",
                "review_feeling": "smooth",
                "adopt_focus_kit": False,
            },
        )
    )
    db.commit()
    adopted_facts = [
        event for event in db.query(OutboxEvent).all()
        if event.payload.get("event_type") == "focus_kit.adopted"
    ]
    assert len(adopted_facts) == 0

    # 显式采纳锦囊
    workflow.invoke(
        RunInvocation(
            run_id=uid(),
            thread_id=uid(),
            ward_id=ward.id,
            agent_type="reflection",
            turn={
                "review_date": "2026-09-12",
                "review_feeling": "smooth",
                "adopt_focus_kit": True,
            },
        )
    )
    db.commit()
    adopted_facts2 = [
        event for event in db.query(OutboxEvent).all()
        if event.payload.get("event_type") == "focus_kit.adopted"
    ]
    assert len(adopted_facts2) == 1
