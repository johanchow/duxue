"""Policy shared by every educational artifact's active version branch."""

from datetime import timedelta

MAX_VERSIONS = 20
TEMPORARY_LIFETIME = timedelta(hours=4)


def active_prefix(branch, cursor):
    return list(branch[: cursor + 1])


def move_cursor(branch, cursor, action):
    target = cursor + {"undo": -1, "redo": 1}[action]
    if not 0 <= target < len(branch):
        raise ValueError("version operation unavailable")
    return target
