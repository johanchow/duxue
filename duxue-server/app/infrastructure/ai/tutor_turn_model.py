"""tutor-turn.v1 的模型适配器：主调用与泄露检查。

主调用每次都带窗口图片和本轮图片。适配器只返回原始 JSON，结构校验在 Application。
"""

from __future__ import annotations

import json

from app.infrastructure.ai import components
from app.infrastructure.ai.errors import ModelGatewayError
from app.infrastructure.ai.utterance_window import user_content


class QwenTutorTurnGateway:
    def complete(
        self, *, envelope: dict, instruction: str, recent_utterances: list[dict] | None = None,
        current_images: list[str | None] | None = None, repair_error: str | None = None,
        observations: list[dict] | None = None,
    ) -> dict:
        payload: dict = {"contract": "tutor-turn.v1", "instruction": instruction, "context": envelope}
        if observations:
            payload["observations"] = observations
        if repair_error:
            payload["repair_error"] = repair_error
        user = user_content(payload, recent_utterances, list(current_images or []))
        return components.invoke_json_component(
            spec=components.COMPONENTS.get("tutoring.turn"), user=user,
        )


class QwenLeakJudge:
    def leaks(self, *, text: str, task_title: str | None, problem_summary: str | None) -> bool | None:
        body = {"task_title": task_title, "problem": problem_summary, "reply": text}
        try:
            payload = components.invoke_json_component(
                spec=components.COMPONENTS.get("tutoring.leak-judge"),
                user=json.dumps(body, ensure_ascii=False),
            )
        except ModelGatewayError:
            return None
        value = payload.get("leaks")
        return value if isinstance(value, bool) else None
