"""Study 领域规则。不访问数据库，也不修改 Planning 的 Task。"""

from __future__ import annotations

MAX_ACTIVE_SECONDS = 180 * 60
ANSWER_LEAK_MARKERS = ("最终答案", "答案是", "所以选")


def should_auto_pause(active_seconds: int) -> bool:
    return active_seconds >= MAX_ACTIVE_SECONDS


def can_finish(task_id: str | None) -> bool:
    """无任务会话不能当作任务完成。"""
    return bool(task_id)
