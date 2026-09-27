"""Study 领域规则。不访问数据库，也不修改 Planning 的 Task。"""

from __future__ import annotations

from dataclasses import dataclass

MAX_ACTIVE_SECONDS = 180 * 60
_ANSWER_LEAK = ("最终答案", "答案是", "所以选")


@dataclass(frozen=True)
class HintingDecision:
    allowed_level: int
    return_to_task: bool
    l4_walkthrough_allowed: bool
    record_fact: bool


class HintingPolicy:
    """根据已验证尝试次数和意图标签决定本轮允许的提示等级。"""

    @staticmethod
    def evaluate(
        *,
        failed_attempts: int,
        intent_label: str,
        has_task: bool,
        session_status: str,
    ) -> HintingDecision:
        curiosity = intent_label in {"curiosity", "chat"}
        return_to_task = bool(
            curiosity and has_task and session_status in {"active", "paused"}
        )
        if intent_label == "answer_seeking":
            return HintingDecision(1, return_to_task, False, False)
        if curiosity and not has_task:
            return HintingDecision(1, False, False, True)
        level = min(4, failed_attempts + 1)
        return HintingDecision(
            allowed_level=level,
            return_to_task=return_to_task,
            l4_walkthrough_allowed=failed_attempts >= 3,
            record_fact=True,
        )

    @staticmethod
    def accepts_display(decision: HintingDecision, text: str) -> bool:
        leaked = any(marker in text for marker in _ANSWER_LEAK)
        if decision.allowed_level >= 4 and decision.l4_walkthrough_allowed:
            has_check = "验证" in text or "如果" in text or "？" in text or "?" in text
            return has_check or not leaked
        return not leaked


def should_auto_pause(active_seconds: int) -> bool:
    return active_seconds >= MAX_ACTIVE_SECONDS


def can_finish(task_id: str | None) -> bool:
    """无任务会话不能当作任务完成。"""
    return bool(task_id)
