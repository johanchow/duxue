"""Registered model-specific projections of already authorized application data.

Builders cannot fetch additional data. Application services retain Ward access
checks; each explicit signature limits which evidence reaches a model.
"""
from __future__ import annotations

import json

from app.infrastructure.ai.utterance_window import image_parts, user_content


def intent(*, content, focus_agent_type, recent_utterances=None, current_images=None):
    return user_content({"content": content, "focus_agent_type": focus_agent_type}, recent_utterances, current_images)


def scene_switch(*, content, current_agent_type, proposed_agent_type, recent_utterances, current_images):
    return user_content({"content": content, "current_agent_type": current_agent_type,
                         "proposed_agent_type": proposed_agent_type}, recent_utterances, current_images)


def tutor_turn(*, envelope, instruction, recent_utterances=None, current_images=None,
               repair_error=None, observations=None):
    clean_envelope = dict(envelope)
    clean_envelope.pop("_dossier_gate", None)
    inspected_crops = clean_envelope.pop("inspected_crops", None) or []
    payload = {"contract": "tutor-turn.v4", "instruction": instruction, "context": clean_envelope}
    has_images = current_images or any(row.get("image_urls") for row in recent_utterances or [])
    if has_images and clean_envelope.get("image_review_phase") != "response":
        from app.application.workflows.image_review import ImageReview
        payload["image_review_rule"] = (
            "仅识题、讲解或给提示且未判断学生作答时，"
            "必须返回 image_review.conclusion=not_checking、questions=[]，"
            "不要把识别出的题干或未作答题目填进 questions。content 写本轮实际回复。"
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


def visual_judge(*, text, task_title, problem_summary):
    return json.dumps({"task_title": task_title, "problem": _judge_problem(problem_summary), "visual": text}, ensure_ascii=False)


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
