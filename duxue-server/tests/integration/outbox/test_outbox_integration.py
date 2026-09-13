from __future__ import annotations

from datetime import datetime, timezone
import pytest

from app.infrastructure.messaging.outbox import publish_learning_fact
from app.application.commands.memory_worker import consume_pending_learning_facts
from app.infrastructure.persistence.models import EpisodicMemory, EpisodicMemoryEvent, LearningEvent, OutboxEvent, uid
from tests.support.factories import create_ward


def test_outbox_transactional_publish_and_worker_consumption(db):
    """集成测试：Outbox 事务写入、Worker 消费、状态流转至 published 并沉淀记忆。"""
    ward = create_ward(db)
    tutoring_session_id = uid()

    # 1. 模拟业务在事务中发布 3 个连续事实事件
    for event_type in (
        "tutoring.ward_attempt_recorded",
        "tutoring.hint_given",
        "tutoring.session_closed",
    ):
        publish_learning_fact(
            db,
            ward_id=ward.id,
            event_type=event_type,
            source_type="tutoring_message",
            source_id=uid(),
            payload={"tutoring_session_id": tutoring_session_id},
        )
    db.commit()

    # 验证初始状态为 pending
    pending_count = db.query(OutboxEvent).filter_by(status="pending").count()
    assert pending_count == 3

    # 2. 模拟 Worker 批量拉取消费
    consumed = consume_pending_learning_facts(db)
    db.commit()

    assert consumed == 3

    # 验证 Outbox 表中的状态全部更新为 published
    published_events = db.query(OutboxEvent).filter_by(status="published").all()
    assert len(published_events) == 3
    for ev in published_events:
        assert ev.published_at is not None

    # 验证 LearningEvent 账本入库
    ledger_count = db.query(LearningEvent).filter_by(ward_id=ward.id).count()
    assert ledger_count == 3

    # 验证闭环自动结算生成了答疑 Episode
    episode = (
        db.query(EpisodicMemory)
        .filter_by(aggregate_ref=f"tutoring_session:{tutoring_session_id}")
        .one()
    )
    assert episode is not None
    assert (
        db.query(EpisodicMemoryEvent)
        .filter_by(episodic_memory_id=episode.id)
        .count()
        == 3
    )


def test_outbox_worker_idempotent_when_no_pending_events(db):
    """当没有 pending 事件时，Worker 返回 0 且无多余操作。"""
    consumed = consume_pending_learning_facts(db)
    assert consumed == 0
