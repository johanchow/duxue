"""Registered model-specific projections of already authorized application data.

Builders cannot fetch additional data. Application services retain Ward access
checks; each explicit signature limits which evidence reaches a model.
"""
from __future__ import annotations

import json

from app.infrastructure.ai.utterance_window import (
    image_parts,
    user_content,
    window_text,
)


def intent(*, content, focus_agent_type, recent_utterances=None, current_images=None):
    """Build lightweight intent context: text-only history + current-turn images only.

    History utterances keep their ``image_ids`` markers so the router can still decide
    ``history_image_ref``, without attaching historical image bytes on every turn.
    """
    window = list(recent_utterances or [])
    images = list(current_images or [])
    rows, current_ids = window_text(window, len(images))
    body: dict = {
        "content": content,
        "focus_agent_type": focus_agent_type,
        "recent_utterances": rows,
    }
    if current_ids:
        body["current_image_ids"] = current_ids
    return [{"type": "text", "text": json.dumps(body, ensure_ascii=False)}, *image_parts([], images)]


def scene_switch(*, content, current_agent_type, proposed_agent_type, recent_utterances, current_images):
    return user_content({"content": content, "current_agent_type": current_agent_type,
                         "proposed_agent_type": proposed_agent_type}, recent_utterances, current_images)


def tutor_turn(*, envelope, instruction, recent_utterances=None, current_images=None,
               repair_error=None, observations=None):
    clean_envelope = dict(envelope)
    clean_envelope.pop("_dossier_gate", None)
    clean_envelope.pop("_disable_thinking", None)
    clean_envelope.pop("_thinking_budget", None)
    clean_envelope.pop("_thinking_effort", None)
    clean_envelope.pop("_preload_svg_guidelines", None)
    clean_envelope.pop("_enforce_confidence_gate", None)
    inspected_crops = clean_envelope.pop("inspected_crops", None) or []
    payload = {"contract": "tutor-turn.v4", "instruction": instruction, "context": clean_envelope}
    has_images = current_images or any(row.get("image_urls") for row in recent_utterances or [])
    if has_images and clean_envelope.get("image_review_phase") != "response":
        from app.application.workflows.image_review import ImageReview
        payload["image_review_rule"] = (
            "仅识题、讲解或给提示且未判断学生作答时，"
            "必须返回 image_review.conclusion=not_checking、questions=[]，"
            "不要把识别出的题干或未作答题目填进 questions。content 写本轮实际回复。整页批改先整图直读，已清楚读出的纯算式优先紧凑转写为 arithmetic_rows={图片ref:[[题目位置,原式,手写答案],...]}，其他题型和读不清的题放在 questions，两处不要重复。区分印刷题干与铅笔作答，不能用计算出的期望值补全字迹。有密集、缺口、截断或易混字迹时才用 inspect_image 核对相应局部，每轮最多两次。脱式计算的作答可写成以等号相连的各步算式。expected_count 仅在原图有明确计数依据时填写，不能猜数量。未确认全部题区或读不清时必须 coverage=partial，清楚的行仍逐项提交。"
        )
        report_schema = ImageReview.model_json_schema()
        definitions = report_schema.pop('$defs', {})
        payload["response_schema"] = {
            "type": "object", "$defs": definitions,
            "required": ["image_review", "act", "content"],
            "properties": {"image_review": report_schema, "act": {"type": "string"},
                           "turn": {"type": "object"}, "content": {"type": "string", "minLength": 1, "maxLength": 1200}},
            "additionalProperties": True,
        }
    if clean_envelope.get("image_review_phase") == "response":
        payload["grading_reply_rule"] = "直接回答学生的检查请求。若部分核验，只反馈已核验范围和未能核验的具体位置；保留字迹不明的不确定性。仅核验最终数值时只评价最终作答；只有转写并核验了中间各步时才评价计算过程。"
    from app.agent_specs.definitions import load_definitions
    from app.agent_specs.web_search import TOOL
    if TOOL in load_definitions().units["tutoring.turn"].tools:
        tool = load_definitions().tools[TOOL]
        payload["optional_search_tool"] = {"tool": "web_search", "args_schema": tool.input_schema}
    inspection_tool = "tutoring.inspect_image"
    if (has_images and clean_envelope.get("image_review_phase") != "response"
            and inspection_tool in load_definitions().units["tutoring.turn"].tools):
        payload["optional_inspect_image_tool"] = {
            "tool": "inspect_image",
            "args_schema": load_definitions().tools[inspection_tool].input_schema,
        }
    if observations:
        payload["observations"] = observations
    if repair_error:
        payload["repair_error"] = repair_error
    parts = user_content(payload, recent_utterances, list(current_images or []))
    for crop in inspected_crops:
        if isinstance(crop, dict) and crop.get("url") and crop.get("crop_ref"):
            label = f"（{crop['label']}）" if crop.get("label") else ""
            parts.append({"type": "text", "text": f"局部放大切片 {crop['crop_ref']}{label}："})
            parts.append({"type": "image_url", "image_url": {"url": crop["url"]}})
    return parts


def _judge_problem(summary):
    # Decode only the deterministic transport format; no semantic text parsing.
    try:
        value = json.loads(summary) if isinstance(summary, str) else summary
    except (ValueError, TypeError):
        return summary
    return value if isinstance(value, dict) and "current_request" in value else summary


def text_judge(*, text, task_title, problem_summary, images=None):
    from app.agent_specs.image_refs import image_manifest
    payload = {"task_title": task_title, "problem": _judge_problem(problem_summary), "reply": text}
    from app.agent_specs.visual_delivery import enabled
    if enabled():
        from app.agent_specs.definitions import load_definitions
        payload["response_schema"] = load_definitions().units["tutoring.leak-judge"].provider_output_schema
    if images:
        payload["image_manifest"] = image_manifest(images)
    body = json.dumps(payload, ensure_ascii=False)
    return [{"type": "text", "text": body}, *image_parts([], images)] if images else body


def visual_judge(*, text, task_title, problem_summary, image=None):
    payload = {"task_title": task_title, "problem": _judge_problem(problem_summary), "visual": text}
    if image:
        from app.agent_specs.web_search import PHOTO_REVIEW
        payload["required_photo_review"] = PHOTO_REVIEW
    body = json.dumps(payload, ensure_ascii=False)

    return [{"type": "text", "text": body}, *image_parts([], [image])] if image else body


def image_target(*, window, content):
    from app.agent_specs.image_refs import image_manifest
    manifest = image_manifest([url for row in window for url in row.get("image_urls", [])])
    return user_content({"student_said": content, "latest_image_ref": manifest[-1]["image_ref"] if manifest else None}, window)


def review_aspects(*, raw_expression):
    return json.dumps({"raw_expression": raw_expression}, ensure_ascii=False)


def task_intake(*, wards, request):
    from app.application.commands.task_intake import _data_url, _prompt
    return [{"type": "text", "text": _prompt(wards, request) + "\n\n本轮监护人消息：\n" + request.content},
            *({"type": "image_url", "image_url": {"url": _data_url(key)}} for key in request.attachment_keys)]


def plan_intake(*, ward, tasks, request):
    from app.application.commands.plan_intake import _prompt
    from app.application.commands.task_intake import _data_url
    return [{"type": "text", "text": _prompt(ward, tasks, request) + "\n\n本轮学生消息：\n" + request.content},
            *image_parts(request.recent_utterances, [_data_url(key) for key in request.attachment_keys])]


def sprint_intake(*, request):
    import json
    return json.dumps({"utterance": request.content,
                       "previous": request.previous.model_dump() if request.previous else {}}, ensure_ascii=False)


def eval_grade(*, payload, images=None, inspected_crops=None):
    body = json.dumps(payload, ensure_ascii=False)
    crops = [
        crop
        for crop in (inspected_crops or [])
        if isinstance(crop, dict) and crop.get("url") and crop.get("crop_ref")
    ]
    if not images and not crops:
        return body
    parts = [{"type": "text", "text": body}, *image_parts([], images or [])]
    for crop in crops:
        label = f"（{crop['label']}）" if crop.get("label") else ""
        parts.append({"type": "text", "text": f"局部放大切片 {crop['crop_ref']}{label}："})
        parts.append({"type": "image_url", "image_url": {"url": crop["url"]}})
    return parts


def guardian_mentor_explain(*, payload, recent_utterances=None, current_images=None):
    return user_content(payload, recent_utterances, list(current_images or []))


BUILDERS = {
    "ward.story_pages.context": eval_grade,
    "ward.anti_ghostwriting.context": eval_grade,
    "behavior.visible_activity.context": eval_grade,
    "behavior.support_opportunity.context": eval_grade,
    "evals.semantic_judge.context": eval_grade,
    "tutoring.stem_extract.context": eval_grade,
    "tutoring.stem_review.context": eval_grade,
    "tutoring.blueprint_planner.context": eval_grade,
    "tutoring.blueprint_backup.context": eval_grade,
    "tutoring.mentor_review.context": guardian_mentor_explain,
    "tutoring.mentor_repair.context": guardian_mentor_explain,
    "tutoring.mentor_explain.context": guardian_mentor_explain,
    "study.sprint_intake.context": sprint_intake,
    "companion.intent.context": intent,
    "companion.scene_switch.context": scene_switch,
    "tutoring.turn.context": tutor_turn,
    "tutoring.leak_judge.context": text_judge,
    "tutoring.visual_leak_judge.context": visual_judge,
    "tutoring.image_target.context": image_target,
    "evaluation.review_aspects.context": review_aspects,
    "task.intake.context": task_intake,
    "planning.intake.context": plan_intake,
}


def build_context(component_id: str, **data):
    from app.agent_specs.definitions import load_definitions
    unit, _ = load_definitions().component(component_id)
    return BUILDERS[unit.context_builder_id](**data)
