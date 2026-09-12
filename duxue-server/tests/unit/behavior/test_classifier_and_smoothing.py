from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path
import pytest

from app.domain import Point, RuleClassifier, build_segments, smooth
from app.services import corrected_time


@pytest.fixture
def classifier():
    rules_path = Path(__file__).parents[3] / "classifier" / "rules.yaml"
    return RuleClassifier(rules_path)


def test_classifier_prioritizes_writing_over_phone_on_desk(classifier):
    """机位规则：手部动作握笔书写优先级高于桌面静止物品。"""
    label, confidence = classifier.classify({
        "hand_action": "右手握笔书写",
        "desk_objects": "桌面放置手机与草稿纸",
        "seat_status": "在座",
    })
    assert label == "学习"
    assert confidence == 1.0


def test_classifier_detects_away_when_not_in_seat(classifier):
    """座位状态不在画面中，应判定为离开。"""
    label, confidence = classifier.classify({
        "seat_status": "不在画面中",
        "hand_action": "不可见",
    })
    assert label == "离开"
    assert confidence == 1.0


def test_classifier_default_fallback_on_empty_fields(classifier):
    """空输入或无法识别的状态应安全降级到默认标签。"""
    label, confidence = classifier.classify({})
    assert label in {"走神/玩耍", "学习", "离开"}
    assert confidence == 0.0


def test_smoothing_preserves_short_sequences():
    """少于 3 个数据点时不执行平滑。"""
    base = datetime(2026, 9, 12, 10, 0, 0, tzinfo=timezone.utc)
    points = [
        Point("1", base, "学习", 0.9),
        Point("2", base + timedelta(seconds=15), "走神/玩耍", 0.8),
    ]
    result = smooth(points, radius=1)
    assert [p.label for p in result] == ["学习", "走神/玩耍"]


def test_smoothing_filters_single_frame_noise():
    """单帧突变噪声应该被多数投票滑动窗口平滑消除。"""
    base = datetime(2026, 9, 12, 10, 0, 0, tzinfo=timezone.utc)
    labels = ["学习", "学习", "走神/玩耍", "学习", "学习"]
    points = [Point(str(i), base + timedelta(seconds=i * 15), l, 1.0) for i, l in enumerate(labels)]
    smoothed = smooth(points, radius=1)
    assert [p.label for p in smoothed] == ["学习", "学习", "学习", "学习", "学习"]


def test_smoothing_preserves_center_on_tie():
    """滑动窗口平局时保留中心点原始标签，避免边界震荡。"""
    base = datetime(2026, 9, 12, 10, 0, 0, tzinfo=timezone.utc)
    points = [
        Point("1", base, "学习", 1.0),
        Point("2", base + timedelta(seconds=15), "离开", 1.0),
    ]
    # 模拟偶数或平局情况
    points_3 = [
        Point("1", base, "学习", 1.0),
        Point("2", base + timedelta(seconds=15), "离开", 1.0),
        Point("3", base + timedelta(seconds=30), "走神/玩耍", 1.0),
    ]
    smoothed = smooth(points_3, radius=1)
    # 中间点在 3 个各不相同的窗口中各出现 1 次，平局，应保留原始 center 标签 "离开"
    assert smoothed[1].label == "离开"


def test_build_segments_merges_contiguous_same_label():
    """连续相同标签且时间间隔正常的数据点应归并为单个片段。"""
    base = datetime(2026, 9, 12, 10, 0, 0, tzinfo=timezone.utc)
    points = [
        Point(str(i), base + timedelta(seconds=i * 15), "学习", 0.9, study_session_id="session-1")
        for i in range(4)
    ]
    segments = build_segments(points, interval_seconds=15)
    assert len(segments) == 1
    assert segments[0]["label"] == "学习"
    assert segments[0]["frame_count"] == 4
    assert segments[0]["duration_seconds"] == 60
    assert segments[0]["study_session_id"] == "session-1"


def test_build_segments_splits_on_large_time_gap():
    """即使标签相同，若时间间隔过大（超过 2 个采集周期），应切断为不同片段。"""
    base = datetime(2026, 9, 12, 10, 0, 0, tzinfo=timezone.utc)
    points = [
        Point("1", base, "学习", 1.0),
        Point("2", base + timedelta(seconds=15), "学习", 1.0),
        # 间隔 120 秒 (大幅超过 30 秒)
        Point("3", base + timedelta(seconds=135), "学习", 1.0),
    ]
    segments = build_segments(points, interval_seconds=15)
    assert len(segments) == 2


def test_build_segments_nullifies_mixed_sessions():
    """如果一个行为片段内的帧跨越了不同的学习会话，study_session_id 应置为空以确保准确性。"""
    base = datetime(2026, 9, 12, 10, 0, 0, tzinfo=timezone.utc)
    points = [
        Point("1", base, "学习", 1.0, study_session_id="session-a"),
        Point("2", base + timedelta(seconds=15), "学习", 1.0, study_session_id="session-b"),
    ]
    segments = build_segments(points, interval_seconds=15)
    assert len(segments) == 1
    assert segments[0]["study_session_id"] is None


def test_corrected_time_uses_monotonic_offset():
    """单调时钟基准时间校正。"""
    bound_time = datetime(2026, 9, 12, 10, 0, 0, tzinfo=timezone.utc)
    bound_elapsed = 10_000
    frame_elapsed = 25_000
    frame_raw_time = datetime(2020, 1, 1, 0, 0, 0, tzinfo=timezone.utc)

    corrected = corrected_time(
        frame_time=frame_raw_time,
        elapsed=frame_elapsed,
        bound_time=bound_time,
        bound_elapsed=bound_elapsed,
    )
    expected = bound_time + timedelta(milliseconds=15_000)
    assert corrected == expected
