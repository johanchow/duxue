from __future__ import annotations

from datetime import datetime, timedelta, timezone
import pytest

from app.application.commands.memory import (
    LearningFactRecorded,
    SqlAlchemyMemoryCommandService,
)
from app.infrastructure.persistence.models import (
    DerivedSignal,
    EpisodicMemory,
    EpisodicMemoryEvent,
    LearningEvent,
    LongTermProfile,
    uid,
)
from tests.support.factories import create_ward, make_learning_fact


def test_fact_deduplication_by_source_quadruple(db):
    """(source_type, source_id, event_type, source_version) 必须完全幂等去重。"""
    ward = create_ward(db)
    db.commit()

    service = SqlAlchemyMemoryCommandService(db)
    fact = make_learning_fact(
        ward.id,
        event_type="test.fact",
        source_type="test_service",
        source_id=uid(),
        source_version=1,
    )

    first = service.ingest_learning_fact(fact)
    second = service.ingest_learning_fact(fact)
    db.commit()

    assert first.id == second.id
    assert db.query(LearningEvent).filter_by(ward_id=ward.id).count() == 1


def test_tutoring_episode_requires_closed_and_interaction(db):
    """答疑经历结算必须包含 closed 且至少一条有效互动；纯粹打开关闭无互动时不结算。"""
    ward = create_ward(db)
    db.commit()

    service = SqlAlchemyMemoryCommandService(db)
    empty_session_id = uid()

    # 只有 closed，没有互动
    service.ingest_learning_fact(
        make_learning_fact(
            ward.id,
            event_type="tutoring.session_closed",
            source_type="tutoring_session",
            source_id=empty_session_id,
            payload={"tutoring_session_id": empty_session_id},
        )
    )
    result = service.settle_tutoring_episode(empty_session_id)
    assert result is None

    # 加入互动事实
    valid_session_id = uid()
    service.ingest_learning_fact(
        make_learning_fact(
            ward.id,
            event_type="tutoring.ward_attempt_recorded",
            source_type="tutoring_message",
            source_id=uid(),
            payload={"tutoring_session_id": valid_session_id},
        )
    )
    service.ingest_learning_fact(
        make_learning_fact(
            ward.id,
            event_type="tutoring.session_closed",
            source_type="tutoring_session",
            source_id=valid_session_id,
            payload={"tutoring_session_id": valid_session_id},
        )
    )
    episode = service.settle_tutoring_episode(valid_session_id)
    db.commit()

    assert episode is not None
    assert episode.memory_type == "tutoring_episode"
    assert db.query(EpisodicMemoryEvent).filter_by(episodic_memory_id=episode.id).count() == 2


def test_signal_promotion_requires_two_independent_episodes(db):
    """候选理解信号晋升需要至少 2 个独立 Episode 支撑。"""
    ward = create_ward(db)
    db.commit()

    service = SqlAlchemyMemoryCommandService(db)

    # 构造两个支撑事实
    event1 = service.ingest_learning_fact(make_learning_fact(ward.id, source_id=uid()))
    event2 = service.ingest_learning_fact(make_learning_fact(ward.id, source_id=uid()))

    # 只关联到同一个 episode
    episode1 = EpisodicMemory(
        ward_id=ward.id,
        memory_type="tutoring_episode",
        event_type="tutoring_episode",
        aggregate_ref=f"tutoring_session:{uid()}",
        aggregate_version=1,
        event_date=datetime.now(timezone.utc).date(),
        summary="经历1",
        raw_cues={},
    )
    db.add(episode1)
    db.flush()
    db.add(EpisodicMemoryEvent(episodic_memory_id=episode1.id, learning_event_id=event1.id))
    db.add(EpisodicMemoryEvent(episodic_memory_id=episode1.id, learning_event_id=event2.id))
    db.commit()

    signal = service.propose_candidate_signal(
        ward_id=ward.id,
        signal_type="effective_strategy",
        scope="long_term",
        dimension_key="test_strategy",
        statement="测试策略",
        value={"sample_size": 2, "window": "5d", "calculation_method": "v1"},
        confidence=0.85,
        evidence_event_ids=[event1.id, event2.id],
    )
    db.commit()

    # 只有一个独立 episode，不应晋升
    service.evolve_signals()
    db.commit()
    assert db.get(DerivedSignal, signal.id).status == "candidate"

    # 将 event2 重新关联到第二个独立的 episode
    episode2 = EpisodicMemory(
        ward_id=ward.id,
        memory_type="tutoring_episode",
        event_type="tutoring_episode",
        aggregate_ref=f"tutoring_session:{uid()}",
        aggregate_version=1,
        event_date=datetime.now(timezone.utc).date(),
        summary="经历2",
        raw_cues={},
    )
    db.add(episode2)
    db.flush()
    db.query(EpisodicMemoryEvent).filter_by(learning_event_id=event2.id).delete()
    db.add(EpisodicMemoryEvent(episodic_memory_id=episode2.id, learning_event_id=event2.id))
    db.commit()

    # 具备 2 个独立 episode，晋升为 active
    service.evolve_signals()
    db.commit()
    assert db.get(DerivedSignal, signal.id).status == "active"


def test_challenged_signal_removed_from_profile_projection(db):
    """被质疑的 Signal 立即退出长期画像投影。"""
    ward = create_ward(db)
    db.commit()

    service = SqlAlchemyMemoryCommandService(db)
    signal = DerivedSignal(
        ward_id=ward.id,
        signal_type="effective_strategy",
        scope="long_term",
        dimension_key="visual_mindmap",
        value={"sample_size": 2, "window": "5d", "calculation_method": "v1"},
        statement="思维导图有效",
        confidence=0.9,
        observed_from=datetime.now(timezone.utc),
        status="active",
    )
    db.add(signal)
    db.commit()

    service.rebuild_long_term_profile(ward.id)
    profile = db.get(LongTermProfile, ward.id)
    assert "visual_mindmap" in profile.learning_strategy_profile

    # 提出反证挑战
    service.challenge_signal(signal.id, ward.id, "学生表示画导图太耗时")
    service.rebuild_long_term_profile(ward.id)

    assert db.get(DerivedSignal, signal.id).status == "challenged"
    profile_updated = db.get(LongTermProfile, ward.id)
    assert "visual_mindmap" not in profile_updated.learning_strategy_profile
