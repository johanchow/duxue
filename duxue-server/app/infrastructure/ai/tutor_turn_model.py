"""tutor-turn.v4 的模型适配器：主调用与泄露检查。

主调用每次都带窗口图片和本轮图片。适配器只返回原始 JSON，结构校验在 Application。
"""

from __future__ import annotations

from app.agent_specs.catalog import load_catalog
from app.agent_specs.contexts import build_context
from app.agent_specs.verdicts import normalize_judge
from app.infrastructure.ai import components
from app.infrastructure.ai.errors import ModelGatewayError


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
        user = build_context("tutoring.turn", envelope=envelope, instruction=instruction,
                             observations=observations, repair_error=repair_error,
                             recent_utterances=recent_utterances, current_images=current_images)
        return components.invoke_agent_component(
            spec=self._spec or load_catalog().component("tutoring", "attempt"), user=user,
            settings_obj=self._settings,
        ).unwrap()


class QwenLeakJudge:
    def __init__(self, settings_obj=None):
        self._settings = settings_obj  # offline evaluation only; production passes nothing

    def leaks(
        self, *, text: str, task_title: str | None, problem_summary: str | None,
        images: list[str] | None = None,
    ) -> dict | None:
        # A visual review happens only after Application has authorized these images
        # and the exit policy already requires a leak check. No image => preserve the
        # compact text request used by offline evaluation and ordinary turns.
        user = build_context("tutoring.leak-judge", text=text, task_title=task_title,
                             problem_summary=problem_summary, images=images)
        return self._judge(
            "tutoring.leak-judge", user, with_reason=True,
        )

    def visual_leaks(self, *, text: str, task_title: str | None, problem_summary: str | None) -> bool | None:
        """``text`` 是 ``describe(visual)``。独立的提示词与组件，不与文字判官共用。"""
        return self._judge(
            "tutoring.visual-leak-judge",
            build_context("tutoring.visual-leak-judge", text=text, task_title=task_title,
                          problem_summary=problem_summary),
        )

    def _judge(self, component_id: str, user: str | list[dict], *, with_reason: bool = False) -> bool | dict | None:
        try:
            payload = components.invoke_json_component(
                spec=load_catalog().component_by_id("tutoring-vet", component_id),
                user=user, settings_obj=self._settings,
            )
        except ModelGatewayError:
            return None
        verdict = normalize_judge(component_id, payload)
        if verdict.verdict == "unknown":
            return None
        value = verdict.verdict == "deny"
        if with_reason:
            return {"leaks": value, "reason": payload.get("reason")}
        return value
