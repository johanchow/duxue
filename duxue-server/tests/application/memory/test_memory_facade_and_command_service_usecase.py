from __future__ import annotations

from datetime import datetime, timezone
import pytest

from app.application.commands.memory import (
    MemoryAccessDenied,
    MemoryContextRequest,
    SqlAlchemyMemoryCommandService,
    SqlAlchemyMemoryFacade,
)
from app.infrastructure.persistence.models import (
    DerivedSignal,
    EpisodicMemory,
    EpisodicMemoryEvent,
    LongTermProfile,
    uid,
)
from tests.support.factories import create_ward, make_learning_fact


def test_resolve_context_enforces_budget_and_filters_candidates(db):
    """上下文解析门面：严格遵守 item_budget、排除 candidate 信号并脱敏 raw_cues。"""
    ward = create_ward(db)

    # 准备 2 条事件记忆
    for i in range(3):
        ep = EpisodicMemory(
            ward_id=ward.id,
            memory_type="tutoring_episode",
            event_type="tutoring_episode",
            aggregate_ref=f"tutoring_session:{uid()}",
            aggregate_version=1,
            event_date=datetime.now(timezone.utc).date(),
            summary=f"学习经历摘要_{i}",
            raw_cues={"sensitive_cue": "secret_123"},
        )
        db.add(ep)

    # 准备 1 条 active signal 和 1 条 candidate signal
    db.add(
        DerivedSignal(
            ward_id=ward.id,
            signal_type="effective_strategy",
            scope="recent",
            dimension_key="visual",
            value={"type": "diagram"},
            statement="画图有效",
            confidence=0.8,
            status="active",
            observed_from=datetime.now(timezone.utc),
        )
    )
    db.add(
        DerivedSignal(
            ward_id=ward.id,
            signal_type="knowledge_gap",
            scope="recent",
            dimension_key="calc_error",
            value={"type": "calc"},
            statement="疑似计算薄弱",
            confidence=0.3,
            status="candidate",
            observed_from=datetime.now(timezone.utc),
        )
    )
    db.commit()

    facade = SqlAlchemyMemoryFacade(db)
    # 请求 item_budget = 5
    bundle = facade.resolve_context(
        MemoryContextRequest(
            ward_id=ward.id,
            actor_id=ward.id,
            actor_role="ward",
            use_case="tutoring",
            memory_types={"episodic", "signal"},
            visibility_scope={"ward", "system"},
            item_budget=5,
            token_budget=500,
        )
    )

    # 最多返回 5 条记忆
    assert len(bundle.episodic_memories) <= 3
    # raw_cues 脱敏不暴露
    for item in bundle.episodic_memories:
        assert "raw_cues" not in item

    # candidate 信号不泄露，仅包含 active 信号
    statements = [sig["statement"] for sig in bundle.active_signals]
    assert "画图有效" in statements
    assert "疑似计算薄弱" not in statements


def test_resolve_context_unauthorized_actor_denied(db):
    """跨学生非法读取记忆，必须抛出 MemoryAccessDenied 异常。"""
    ward1 = create_ward(db, display_name="学生1")
    ward2 = create_ward(db, display_name="学生2")
    db.commit()

    facade = SqlAlchemyMemoryFacade(db)
    with pytest.raises(MemoryAccessDenied):
        facade.resolve_context(
            MemoryContextRequest(
                ward_id=ward1.id,
                actor_id=ward2.id,  # 试图以学生2身份读取学生1的记忆
                actor_role="ward",
                use_case="tutoring",
                memory_types={"episodic"},
                visibility_scope={"ward"},
                item_budget=5,
                token_budget=500,
            )
        )
