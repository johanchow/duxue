"""tutor-turn.v4 的模型适配器：主调用与泄露检查。

主调用每次都带窗口图片和本轮图片。适配器只返回原始 JSON，结构校验在 Application。
"""

from __future__ import annotations

from app.agent_specs.catalog import load_catalog
from app.agent_specs.contexts import build_context
from app.agent_specs.subworkflows import review_workflow_id
from app.agent_specs.verdicts import normalize_judge
from app.infrastructure.ai import components
from app.infrastructure.ai.errors import ModelGatewayError


class QwenTutorTurnGateway:
    """``spec`` / ``settings_obj`` exist for the offline evaluation to try a named candidate
    in its own process; production always uses the registered component."""

    def __init__(self, spec=None, settings_obj=None, component_id="tutoring.turn"):
        self._spec = spec
        self._component_id = component_id
        self._settings = settings_obj

    def complete(
        self, *, envelope: dict, instruction: str, recent_utterances: list[dict] | None = None,
        current_images: list[str | None] | None = None, repair_error: str | None = None,
        observations: list[dict] | None = None,
    ) -> dict:
        from dataclasses import replace

        user = build_context("tutoring.turn", envelope=envelope, instruction=instruction,
                             observations=observations, repair_error=repair_error,
                             recent_utterances=recent_utterances, current_images=current_images)
        spec = self._spec or components.COMPONENTS.get(self._component_id)
        if isinstance(envelope, dict) and envelope.get("_disable_thinking") and getattr(spec, "enable_thinking", False):
            spec = replace(spec, enable_thinking=False, thinking_budget=None)
        return components.invoke_agent_component(
            spec=spec, user=user,
            settings_obj=self._settings,
        ).unwrap()


class QwenLeakJudge:
    @property
    def supports_joint_math_review(self) -> bool:
        from app.agent_specs.definitions import load_definitions

        unit = load_definitions().units["tutoring.leak-judge"]
        return "[submitted-feedback.v1]" in unit.prompt.template and "math_consistent" in unit.provider_output_schema.get("properties", {})

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

    def check_math(self, *, text: str, context: dict, images: list[str]) -> bool | None:
        import json
        user = build_context("tutoring.leak-judge", text=text, task_title=None,
                             problem_summary=json.dumps(context, ensure_ascii=False), images=images)
        from contextlib import nullcontext

        from app.agent_specs.catalog import executing_node
        from app.agent_specs.subworkflows import MATH_NODE
        from app.infrastructure.observability.telemetry import agent_step_span
        catalog = load_catalog()
        review_id = review_workflow_id(catalog.specs)
        review = (nullcontext() if executing_node.get() in {("tutoring", MATH_NODE), (review_id, f"{review_id}.math_consistency")} else
                  agent_step_span("check", "tutoring.text_leak", **{"math.review.phase": "consistency"}))
        try:
            with review:
                payload = components.invoke_json_component(
                    spec=catalog.component_by_id(review_id, "tutoring.leak-judge"),
                    user=user, settings_obj=self._settings,
                )
        except ModelGatewayError:
            return None
        value = payload.get("math_consistent") if isinstance(payload, dict) else None
        return value if type(value) is bool else None

    def visual_leaks(self, *, text: str, task_title: str | None, problem_summary: str | None, image: str | None = None) -> bool | None:
        """``text`` 是 ``describe(visual)``。独立的提示词与组件，不与文字判官共用。"""
        return self._judge(
            "tutoring.visual-leak-judge",
            build_context("tutoring.visual-leak-judge", text=text, task_title=task_title,
                          problem_summary=problem_summary, image=image),
            photo_review=image is not None,
        )

    def _judge(self, component_id: str, user: str | list[dict], *, with_reason: bool = False, photo_review: bool = False) -> bool | dict | None:
        catalog = load_catalog()
        try:
            payload = components.invoke_json_component(
                spec=catalog.component_by_id(review_workflow_id(catalog.specs), component_id),
                user=user, settings_obj=self._settings,
            )
        except ModelGatewayError:
            return None
        if photo_review:
            from app.agent_specs.web_search import PHOTO_CHECKS
            review = payload.get("photo_review")
            if not isinstance(review, dict):
                return None
            if any(review.get(key) is not True for key in PHOTO_CHECKS):
                return True
        verdict = normalize_judge(component_id, payload)
        if verdict.verdict == "unknown":
            return None
        value = verdict.verdict == "deny"
        if with_reason:
            out = {
                "leaks": value,
                "reason": verdict.reason_code,
                "answer_protected": payload["answer_protected"],
                **(
                    {
                        key: payload[key]
                        for key in ("visual_need", "visual_adequate", "visual_evidence", "math_consistent")
                        if key in payload
                    }
                ),
            }
            if payload.get("affirms_student_answer") is True:
                out["affirms_student_answer"] = True
            return out
        return value
