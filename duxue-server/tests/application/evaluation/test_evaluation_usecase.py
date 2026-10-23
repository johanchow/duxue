from __future__ import annotations

from datetime import date

from app.application.ports.companion import RunInvocation
from app.application.workflows.reflection_workflow import ReflectionWorkflow
from app.infrastructure.persistence.models import OutboxEvent, Report, SelfReview, uid
from tests.support.factories import create_ward


def test_reflection_usecase_with_objective_report(db):
    """复盘用例：客观报告存在时，自评后返回证据状态，不生成锦囊。"""
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
            },
        )
    )
    db.commit()

    assert outcome.run_status == "closed"
    assert outcome.next_interaction["objective_evidence_status"] == "available"
    assert "advice" not in outcome.next_interaction

    review = db.query(SelfReview).filter_by(ward_id=ward.id, review_date=day).one()
    assert review.feeling == "stuck"

    # 总结由 Evaluation 直接保存，不再投递 Memory 事实。
    events = [e.payload["event_type"] for e in db.query(OutboxEvent).all()]
    assert "self_review.submitted" not in events
    assert "focus_kit.adopted" not in events
