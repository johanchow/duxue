from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import Iterable

import yaml


BEHAVIOR_FIELDS = ("hand_action", "head_orientation", "body_pos", "seat_status", "motion_state", "desc_summary")


class RuleClassifier:
    def __init__(self, path: Path):
        config = yaml.safe_load(path.read_text(encoding="utf-8"))
        self.rules = sorted(config["rules"], key=lambda item: -item["priority"])
        self.default = config.get("default_label", "走神/玩耍")

    def classify(self, fields: dict) -> tuple[str, float]:
        for rule in self.rules:
            scope = rule.get("scope") or BEHAVIOR_FIELDS
            text = " ".join(str(fields.get(key, "")) for key in scope).lower()
            if any(word.lower() in text for word in rule.get("any_of", [])) and not any(
                word.lower() in text for word in rule.get("none_of", [])
            ):
                return rule["label"], 1.0
        return self.default, 0.0


@dataclass(frozen=True)
class Point:
    frame_id: str
    at: datetime
    label: str
    confidence: float


def smooth(points: list[Point], radius: int = 1) -> list[Point]:
    if len(points) < 3:
        return points
    result: list[Point] = []
    for index, point in enumerate(points):
        window = points[max(0, index - radius): min(len(points), index + radius + 1)]
        counts = Counter(item.label for item in window)
        winner, count = counts.most_common(1)[0]
        # Preserve the center on a tie so edges do not create artificial changes.
        tied = [label for label, value in counts.items() if value == count]
        label = point.label if point.label in tied else winner
        result.append(Point(point.frame_id, point.at, label, point.confidence))
    return result


def build_segments(points: Iterable[Point], interval_seconds: int = 15) -> list[dict]:
    ordered = sorted(points, key=lambda item: item.at)
    if not ordered:
        return []
    groups: list[list[Point]] = [[ordered[0]]]
    max_gap = timedelta(seconds=max(interval_seconds * 2, 30))
    for point in ordered[1:]:
        previous = groups[-1][-1]
        if point.label == previous.label and point.at - previous.at <= max_gap:
            groups[-1].append(point)
        else:
            groups.append([point])
    return [{
        "start": group[0].at,
        "end": group[-1].at + timedelta(seconds=interval_seconds),
        "label": group[0].label,
        "frame_count": len(group),
        "confidence_avg": sum(item.confidence for item in group) / len(group),
        "duration_seconds": len(group) * interval_seconds,
    } for group in groups]
