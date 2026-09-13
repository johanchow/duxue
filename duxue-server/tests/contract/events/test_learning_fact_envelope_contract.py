from __future__ import annotations

from datetime import datetime, timezone
import pytest
from pydantic import ValidationError

from app.application.commands.memory import LearningFactRecorded
from app.infrastructure.persistence.models import uid


def test_learning_fact_recorded_envelope_schema_valid():
    """验证标准 LearningFactRecorded.v1 事件信封。"""
    now_dt = datetime.now(timezone.utc)
    source_id = uid()
    ward_id = uid()

    fact = LearningFactRecorded(
        ward_id=ward_id,
        event_type="tutoring.hint_given",
        source_type="tutoring_message",
        source_id=source_id,
        source_version=1,
        occurred_at=now_dt,
        source="system",
        visibility="ward",
        payload={"hint_level": 2, "topic": "equation"},
    )

    dumped = fact.model_dump(mode="json")
    assert dumped["schema_version"] == "LearningFactRecorded.v1"
    assert dumped["event_type"] == "tutoring.hint_given"
    assert dumped["ward_id"] == ward_id
    assert dumped["source_id"] == source_id
    assert dumped["payload"] == {"hint_level": 2, "topic": "equation"}

    # 能正确从 payload 再次反序列化
    reloaded = LearningFactRecorded.model_validate(dumped)
    assert reloaded.ward_id == ward_id
    assert reloaded.source_version == 1


def test_learning_fact_missing_required_fields_raises_validation_error():
    """缺少必填字段时必须抛出 Pydantic ValidationError。"""
    with pytest.raises(ValidationError):
        LearningFactRecorded(
            ward_id=uid(),
            event_type="tutoring.hint_given",
            # 缺失 source_type 和 source_id
        )
