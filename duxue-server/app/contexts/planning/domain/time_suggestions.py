"""Soft planning time guidance, independent of historical activity."""

from datetime import date, datetime, time, timedelta
from hashlib import sha256
import json

from .scheduling import PLAN_TIME_ZONE, SchedulingService


EARLIEST_START = time(7, 0)
LATEST_END = time(22, 0)


def suggest_plan_time(item: dict, items: list[dict], plan_date: date) -> dict | None:
    if not item.get("start_at") or not item.get("end_at") or item.get("deferred"):
        return None
    start = SchedulingService.instant(item["start_at"]).astimezone(PLAN_TIME_ZONE)
    end = SchedulingService.instant(item["end_at"]).astimezone(PLAN_TIME_ZONE)
    if start.date() != plan_date:
        return None  # This is a hard wrong_plan_date conflict, not a soft suggestion.
    earliest = datetime.combine(plan_date, EARLIEST_START, PLAN_TIME_ZONE)
    latest = datetime.combine(plan_date, LATEST_END, PLAN_TIME_ZONE)
    if start < earliest:
        code, proposed_start = "too_early", earliest
    elif end > latest:
        code, proposed_start = "too_late", latest - timedelta(minutes=item["planned_minutes"])
    else:
        return None
    result = {
        "code": code,
        "reason": "建议在07:00后开始" if code == "too_early" else "建议在22:00前结束",
        "suggested_start_at": None,
        "suggested_end_at": None,
    }
    evidence = [(other.get("assignment_id"), other.get("start_at"),
                 other.get("end_at"), other.get("planned_minutes")) for other in items]
    result["fingerprint"] = sha256(json.dumps(evidence, sort_keys=True).encode()).hexdigest()
    proposed_end = proposed_start + timedelta(minutes=item["planned_minutes"])
    if proposed_start < earliest or proposed_end > latest:
        return result
    replacement = dict(item, start_at=proposed_start.isoformat(), end_at=proposed_end.isoformat())
    candidate_items = [replacement if other.get("assignment_id") == item.get("assignment_id")
                       else other for other in items]
    conflicts = SchedulingService.validate_schedule(candidate_items, plan_date=plan_date)
    if any(item["assignment_id"] in conflict["task_ids"] for conflict in conflicts):
        return result
    result["suggested_start_at"] = proposed_start.isoformat()
    result["suggested_end_at"] = proposed_end.isoformat()
    return result
