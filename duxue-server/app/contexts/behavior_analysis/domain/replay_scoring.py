"""Compare explicit human frame labels; never ask a model to grade itself."""
from collections import Counter

from app.contexts.behavior_analysis.domain.observation import ACTIVITIES


def score_frames(snapshots, labels):
    predictions = {}
    for snapshot in snapshots:
        for run in snapshot['runs']:
            for frame_id in run['evidence']:
                predictions[frame_id] = run['activity']
    seen, confusion = set(), Counter()
    for label in labels:
        frame_id, expected = label['frame_id'], label['activity']
        if frame_id in seen or expected not in ACTIVITIES:
            raise ValueError('duplicate frame label or invalid activity')
        seen.add(frame_id)
        confusion[(expected, predictions.get(frame_id, 'unavailable'))] += 1
    correct = sum(count for (expected, actual), count in confusion.items() if expected == actual)
    return {'labeled_frames': len(seen), 'correct_frames': correct,
            'accuracy': correct/len(seen) if seen else None,
            'confusion': [{'expected': expected, 'actual': actual, 'count': count}
                          for (expected, actual), count in sorted(confusion.items())]}
