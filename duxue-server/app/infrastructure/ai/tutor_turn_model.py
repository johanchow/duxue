"""tutor-turn.v4 的模型适配器：主调用与泄露检查。

主调用每次都带窗口图片和本轮图片。适配器只返回原始 JSON，结构校验在 Application。
"""

from __future__ import annotations

import json
from dataclasses import replace

from app.agent_specs.catalog import load_catalog
from app.agent_specs.contexts import build_context
from app.agent_specs.subworkflows import review_workflow_id
from app.agent_specs.verdicts import normalize_judge
from app.infrastructure.ai import components
from app.infrastructure.ai.errors import ModelGatewayError
from app.infrastructure.ai.prompts import PromptTemplate, compose_system_prompt


def _strip_prompt_section(prompt_text: str, marker: str) -> str:
    """Omit a tagged top-level block separated by blank lines when not applicable."""
    if marker not in prompt_text:
        return prompt_text
    blocks = prompt_text.split("\n\n")
    kept = [block for block in blocks if not block.lstrip().startswith(marker)]
    return "\n\n".join(kept)


def _strip_image_review_section(prompt_text: str) -> str:
    """Omit the `[image-review.v1]` protocol block on pure-text turns with zero images."""
    return _strip_prompt_section(prompt_text, "[image-review.v1]")


def _tutor_turn_fragment_names(
    envelope: dict | None,
    *,
    has_images: bool,
    observations: list[dict] | None = None,
) -> tuple[str, ...]:
    """Select optional scenario fragments for `tutoring.turn` in deterministic tail order."""
    env = envelope if isinstance(envelope, dict) else {}
    actor = env.get("actor") if isinstance(env.get("actor"), dict) else {}
    grade_stage = actor.get("grade_stage")
    names: list[str] = []
    if (
        grade_stage in {"high", "senior"}
        or env.get("problem_dossier")
        or env.get("internal_blueprint")
    ):
        names.append("gaokao_blueprint")
    has_svg_guidelines = bool(
        env.get("_preload_svg_guidelines")
        or any(isinstance(obs, dict) and obs.get("tool") == "widget_guidelines" for obs in (observations or []))
    )
    if has_svg_guidelines:
        names.append("visual_delivery_detail")
    if has_images and env.get("image_review_phase") != "response":
        names.append("image_review")
    return tuple(names)


def _leak_judge_fragment_names(
    *,
    images: list[str] | None = None,
    problem_summary: str | None = None,
    context: dict | None = None,
    force_math: bool = False,
) -> tuple[str, ...]:
    """Select optional scenario fragments for `tutoring.leak-judge` in deterministic tail order."""
    parsed: dict | None = context if isinstance(context, dict) else None
    if parsed is None and isinstance(problem_summary, str):
        text = problem_summary.strip()
        if text.startswith("{"):
            try:
                loaded = json.loads(text)
                if isinstance(loaded, dict):
                    parsed = loaded
            except ValueError:
                parsed = None
    names: list[str] = []
    if force_math or (parsed is not None and parsed.get("math_review_required") is True):
        names.append("math_review")
    if images:
        names.append("image_review")
    candidate_visual = parsed.get("candidate_visual") if parsed is not None else None
    if candidate_visual:
        names.append("visual_svg_geometry")
        if isinstance(candidate_visual, dict) and candidate_visual.get("kind") == "web_photo":
            names.append("web_photo")
    return tuple(names)


def _with_system_fragments(spec, unit_id: str, fragment_names: tuple[str, ...]):
    if not fragment_names or not isinstance(getattr(spec, "prompt", None), PromptTemplate):
        return spec
    composed = compose_system_prompt(spec.prompt, unit_id, fragment_names)
    return replace(spec, prompt=composed) if composed is not spec.prompt else spec


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
        user = build_context("tutoring.turn", envelope=envelope, instruction=instruction,
                             observations=observations, repair_error=repair_error,
                             recent_utterances=recent_utterances, current_images=current_images)
        spec = self._spec or components.COMPONENTS.get(self._component_id)
        if isinstance(envelope, dict) and getattr(spec, "enable_thinking", False):
            if envelope.get("_disable_thinking"):
                spec = replace(spec, enable_thinking=False, thinking_budget=None)
            elif isinstance(envelope.get("_thinking_budget"), int) and envelope["_thinking_budget"] > 0:
                requested_budget = envelope["_thinking_budget"]
                effective_budget = (
                    min(spec.thinking_budget, requested_budget)
                    if isinstance(spec.thinking_budget, int) and spec.thinking_budget > 0
                    else requested_budget
                )
                spec = replace(spec, thinking_budget=effective_budget)
        has_images = bool(current_images or any(row.get("image_urls") for row in (recent_utterances or [])))
        env = envelope if isinstance(envelope, dict) else {}
        actor = env.get("actor") if isinstance(env.get("actor"), dict) else {}
        grade_stage = actor.get("grade_stage")
        if isinstance(getattr(spec, "prompt", None), PromptTemplate):
            prompt_text = spec.prompt.text
            if not has_images or env.get("image_review_phase") == "response":
                prompt_text = _strip_image_review_section(prompt_text)
            if (
                grade_stage == "primary"
                and not env.get("problem_dossier")
                and not env.get("internal_blueprint")
            ):
                prompt_text = _strip_prompt_section(prompt_text, "[gaokao-blueprint-science.v1]")
            if prompt_text != spec.prompt.text:
                spec = replace(spec, prompt=PromptTemplate(spec.prompt.id, prompt_text))
        fragment_names = _tutor_turn_fragment_names(
            env, has_images=has_images, observations=observations,
        )
        if fragment_names:
            spec = _with_system_fragments(spec, "tutoring.turn", fragment_names)
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
        fragment_names = _leak_judge_fragment_names(
            images=images, problem_summary=problem_summary,
        )
        phase = "response"
        if not (text or "").strip() and isinstance(problem_summary, str):
            try:
                parsed_summary = json.loads(problem_summary)
                if isinstance(parsed_summary, dict) and parsed_summary.get("image_review_phase") == "evidence_only":
                    phase = "evidence"
            except ValueError:
                pass
        return self._judge(
            "tutoring.leak-judge", user, with_reason=True,
            system_fragments=fragment_names, phase=phase,
        )

    def check_math(self, *, text: str, context: dict, images: list[str]) -> bool | None:
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
        fragment_names = _leak_judge_fragment_names(
            images=images, context=context, force_math=True,
        )
        spec = _with_system_fragments(
            catalog.component_by_id(review_id, "tutoring.leak-judge"),
            "tutoring.leak-judge",
            fragment_names,
        )
        try:
            with review:
                payload = components.invoke_json_component(
                    spec=spec,
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

    def _judge(
        self, component_id: str, user: str | list[dict], *,
        with_reason: bool = False, photo_review: bool = False,
        system_fragments: tuple[str, ...] = (), phase: str = "response",
    ) -> bool | dict | None:
        catalog = load_catalog()
        spec = _with_system_fragments(
            catalog.component_by_id(review_workflow_id(catalog.specs), component_id),
            component_id,
            system_fragments,
        )
        try:
            payload = components.invoke_json_component(
                spec=spec,
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
        verdict = normalize_judge(component_id, payload, phase=phase)
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
