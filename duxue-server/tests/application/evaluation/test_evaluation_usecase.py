from __future__ import annotations

from datetime import date
import pytest

from app.application.workflows.reflection_workflow import ReflectionWorkflow
from app.application.ports.companion import RunInvocation
from app.infrastructure.persistence.models import OutboxEvent, Report, SelfReview, uid
from tests.support.factories import create_ward


def test_reflection_usecase_with_objective_report(db):
    """复盘用例：当客观报告存在时，自评后返回 available 状态及针对性建议。"""
    ward = create_ward(db)
    day = date(2026, 9, 12)
    # 模拟当天客观分析报告已就绪
    report = Report(
        ward_id=ward.id,
        report_date=day,
        total_seconds=3600,
        label_breakdown={"学习": 3000, "走神/玩耍": 600},
        status="ready",
    )
    db.add(report)
    db.commit()

    workflow = ReflectionWorkflow(db)
    outcome = workflow.invoke(
        RunInvocation(
            run_id=uid(),
            thread_id=uid(),
            ward_id=ward.id,
            agent_type="reflection",
            turn={
                "review_date": day.isoformat(),
                "review_feeling": "stuck",
                "review_reflection": "英语阅读生词较多",
                "adopt_focus_kit": True,
            },
        )
    )
    db.commit()

    assert outcome.run_status == "closed"
    assert outcome.next_interaction["objective_evidence_status"] == "available"
    assert outcome.next_interaction["advice"] is not None

    review = db.query(SelfReview).filter_by(ward_id=ward.id, review_date=day).one()
    assert review.feeling == "stuck"

    # 验证 Outbox 发送了自评与锦囊采纳两个事件
    events = [e.payload["event_type"] for e in db.query(OutboxEvent).all()]
    assert "self_review.submitted" in events
    assert "focus_kit.adopted" in events
