"""tutor-turn.v4 的模型适配器：主调用与泄露检查。

主调用每次都带窗口图片和本轮图片。适配器只返回原始 JSON，结构校验在 Application。
"""

from __future__ import annotations

import json

from app.infrastructure.ai import components
from app.infrastructure.ai.errors import ModelGatewayError
from app.infrastructure.ai.utterance_window import image_parts, user_content


class QwenTutorTurnGateway:
    """``spec`` / ``settings_obj`` exist for the offline evaluation to try a named candidate
    in its own process; production always uses the registered component."""

    def __init__(self, spec=None, settings_obj=None):
        self._spec = spec
        self._settings = settings_obj

    def complete(
        self, *, envelope: dict, instruction: str, recent_utterances: list[dict] | None = None,
        current_images: list[str | None] | None = None, repair_error: str | None = None,
        observations: list[dict] | None = None,
    ) -> dict:
        payload: dict = {"contract": "tutor-turn.v4", "instruction": instruction, "context": envelope}
        if observations:
            payload["observations"] = observations
        if repair_error:
            payload["repair_error"] = repair_error
        user = user_content(payload, recent_utterances, list(current_images or []))
        return components.invoke_json_component(
            spec=self._spec or components.COMPONENTS.get("tutoring.turn"), user=user,
            settings_obj=self._settings,
        )


class QwenLeakJudge:
    def __init__(self, settings_obj=None):
        self._settings = settings_obj  # offline evaluation only; production passes nothing

    def leaks(
        self, *, text: str, task_title: str | None, problem_summary: str | None,
        images: list[str] | None = None,
    ) -> dict | None:
        body = {"task_title": task_title, "problem": problem_summary, "reply": text}
        # A visual review happens only after Application has authorized these images
        # and the exit policy already requires a leak check. No image => preserve the
        # compact text request used by offline evaluation and ordinary turns.
        user: str | list[dict] = json.dumps(body, ensure_ascii=False)
        if images:
            user = [{"type": "text", "text": json.dumps(body, ensure_ascii=False)}, *image_parts([], images)]
        return self._judge(
            "tutoring.leak-judge", user, with_reason=True,
        )

    def visual_leaks(self, *, text: str, task_title: str | None, problem_summary: str | None) -> bool | None:
        """``text`` 是 ``describe(visual)``。独立的提示词与组件，不与文字判官共用。"""
        return self._judge(
            "tutoring.visual-leak-judge",
            json.dumps({"task_title": task_title, "problem": problem_summary, "visual": text}, ensure_ascii=False),
        )

    def _judge(self, component_id: str, user: str | list[dict], *, with_reason: bool = False) -> bool | dict | None:
        try:
            payload = components.invoke_json_component(
                spec=components.COMPONENTS.get(component_id),
                user=user, settings_obj=self._settings,
            )
        except ModelGatewayError:
            return None
        value = payload.get("leaks")
        if not isinstance(value, bool):
            return None
        if with_reason:
            return {"leaks": value, "reason": payload.get("reason")}
        return value
