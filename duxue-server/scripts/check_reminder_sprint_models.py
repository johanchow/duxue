"""Explicit live-model smoke check; uses canned inputs and never writes to a DB.

Run from duxue-server: .venv/bin/python -m scripts.check_reminder_sprint_models
"""

import os


def main():
    os.environ["OTEL_SDK_DISABLED"] = "true"
    from app.application.commands.plan_intake import PlanIntakeInput, PlanIntakeService
    from app.infrastructure.ai.scene_switch_verifier import ModelSceneSwitchVerifier

    existing = [{"title": "英语", "planned_minutes": None, "scheduled": False}]
    cases = [
        ([], "帮我记一下，今天还有英语", "note"),
        ([], "七点提醒我读英语", "start"),
        ([], "英语大概需要二十分钟", "estimate"),
        ([], "七点读英语，二十分钟后提醒我休息", "scheduled"),
        (existing, "现在开始英语，二十分钟后提醒我", "elapsed"),
        ([], "现在开始读英语，二十分钟后提醒我", "new"),
    ]
    for tasks, content, kind in cases:
        result = PlanIntakeService().respond(
            ward={"display_name": "测试学生"},
            tasks=tasks,
            request=PlanIntakeInput(content=content),
        )
        assert not result.clarification_required, (kind, result)
        if kind == "elapsed":
            action = result.study_action
            assert action is not None and action.action == "task_start", result
            assert action.task_reference == "英语", result
            assert action.end_reminder_mode == "elapsed", result
            assert action.target_minutes == 20 and not result.operations, result
        else:
            assert result.operations and result.study_action is None, result
            operation = result.operations[0]
            expected_mode = {"scheduled": "scheduled", "new": "elapsed"}.get(kind)
            assert operation.end_reminder_mode == expected_mode, result
            if kind in {"note", "estimate", "new"}:
                assert operation.start_at is None, result
            if kind == "note":
                assert operation.planned_minutes is None, result
            if kind == "start":
                assert operation.start_at and operation.planned_minutes is None, result
            if kind in {"estimate", "scheduled", "new"}:
                assert operation.planned_minutes == 20, result
        print(f"PASS reminder: {kind}", flush=True)

    window = [
        {"author": "ward", "text": "三盒彩笔，每盒一样多，一共二十四支。我该怎么想？"},
        {"author": "companion", "text": "想想看，哪个数乘以3等于24？"},
        {"author": "ward", "text": "我自己再试一分钟"},
        {"author": "companion", "text": "好的，这一分钟交给你。算好后告诉我结果。"},
    ]
    verifier = ModelSceneSwitchVerifier()
    for content, expected in [
        ("帮我开启一轮一分钟的专注挑战，我想自己试这道题", True),
        ("这题大概十分钟能做完", False),
        ("我想到用二十四除以三，这样想对吗？", False),
    ]:
        allowed = verifier.confirm(
            content=content,
            current_agent_type="tutoring",
            proposed_agent_type="planning",
            recent_utterances=window,
            current_images=[],
        )
        assert allowed is expected, (content, allowed, expected)
        print(f"PASS switch: {content}", flush=True)


if __name__ == "__main__":
    main()
