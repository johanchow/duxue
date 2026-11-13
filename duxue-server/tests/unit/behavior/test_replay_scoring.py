import pytest

from app.contexts.behavior_analysis.domain.replay_scoring import score_frames


def test_unavailable_prediction_is_counted_not_dropped():
    result = score_frames([{'runs': [{'activity': 'writing', 'evidence': ['a']}]}],
                          [{'frame_id': 'a', 'activity': 'writing'}, {'frame_id': 'b', 'activity': 'reading_material'}])
    assert result['labeled_frames'] == 2
    assert result['accuracy'] == 0.5
    assert {'expected': 'reading_material', 'actual': 'unavailable', 'count': 1} in result['confusion']


def test_duplicate_annotation_is_rejected():
    with pytest.raises(ValueError):
        score_frames([], [{'frame_id': 'a', 'activity': 'away'}]*2)
