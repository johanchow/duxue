"""Deterministic invitation policy. Does not interpret images or prose."""
from datetime import timedelta


def invitation_allowed(*, current, observed_at, fresh_until, reserved_count,
                       last_reserved_at, has_active, same_run, channel_active,
                       opted_in, interaction_busy):
    if not opted_in or not channel_active or interaction_busy:
        return False
    if not timedelta(0) <= current-observed_at <= timedelta(seconds=60) or current >= fresh_until:
        return False
    if reserved_count >= 2 or has_active or same_run:
        return False
    return last_reserved_at is None or current-last_reserved_at >= timedelta(minutes=20)
