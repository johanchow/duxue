"""到点开始邀请。不访问数据库，也不修改计划时间。"""

from __future__ import annotations

from dataclasses import dataclass

SCENE_LABELS = frozenset({
    "already_working",
    "settling_in",
    "other_activity",
    "away",
    "unclear",
    "no_observation",
})
GAP_REASONS = frozenset({"no_device", "lease_denied", "no_frames"})
OPEN_STATUSES = frozenset({"pending", "held", "ready", "presented"})
START_ACTIONS = ("start_due_task", "snooze_once")
SWITCH_ACTIONS = ("continue_current", "pause_current_and_start_due", "snooze_once")


class StartCueError(Exception):
    def __init__(self, code: str):
        self.code = code
        super().__init__(code)


@dataclass(frozen=True)
class SceneRead:
    label: str
    gap_reason: str | None = None

    def __post_init__(self) -> None:
        if self.label not in SCENE_LABELS:
            raise StartCueError("invalid_scene")
        if self.label == "no_observation":
            if self.gap_reason not in GAP_REASONS:
                raise StartCueError("missing_gap_reason")
        elif self.gap_reason is not None:
            raise StartCueError("unexpected_gap_reason")


@dataclass(frozen=True)
class CueDecision:
    disposition: str
    actions: tuple[str, ...]
    scene_claim_allowed: bool

    @property
    def primary_action(self) -> str | None:
        return self.actions[0] if self.actions else None


class StartCuePolicy:
    """只看有没有另一条进行中或暂停的会话、现场标签，以及是否已经推迟过。"""

    @staticmethod
    def decide(*, other_session: bool, scene: SceneRead, snooze_count: int, past_end: bool) -> CueDecision:
        if past_end:
            return CueDecision("expire", (), False)
        if scene.label == "away":
            return CueDecision("hold", (), False)
        actions: list[str] = ["continue_current", "pause_current_and_start_due"] if other_session else ["start_due_task"]
        if snooze_count < 1:
            actions.append("snooze_once")
        return CueDecision(
            "present",
            tuple(actions),
            scene.label not in {"no_observation", "unclear", "away"},
        )


def fallback_text(
    *,
    due_title: str,
    start_label: str,
    planned_minutes: int | None,
    other_title: str | None,
    earlier_titles: list[str],
    scene: SceneRead,
) -> str:
    """策略兜底句。不声称没看见的书桌。"""
    if other_title:
        sentence = f"{due_title}到点了，{other_title}还在进行。先做完{other_title}，还是暂停{other_title}、开始{due_title}？"
        if scene.label in {"no_observation", "unclear"}:
            sentence = f"{due_title}到点了，我没看清书桌。要继续{other_title}，还是改做{due_title}？"
    elif scene.label == "already_working":
        sentence = f"看起来已经在写{due_title}了。要把现在记成开始吗？"
    elif scene.label == "settling_in":
        minutes = f"这 {planned_minutes} 分钟" if planned_minutes else "这项"
        sentence = f"{due_title}的材料已经准备好了。现在开始{minutes}？"
    elif scene.label == "no_observation":
        sentence = f"{due_title} {start_label} 到了，我没看到书桌。要现在开始吗？"
    elif scene.label == "unclear":
        sentence = f"{due_title}到点了，我没看清书桌。要现在开始吗？"
    else:
        sentence = f"{due_title}到点了。要现在开始，还是等一下？"
    if earlier_titles:
        names = "、".join(earlier_titles)
        sentence = f"{names}也还没开始。{sentence}"
    return sentence


def admits(actions: tuple[str, ...] | list[str], command: str) -> bool:
    return command in actions
