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
    payload = {"contract": "tutor-turn.v4", "instruction": instruction, "context": envelope}
    if observations:
        payload["observations"] = observations
    if repair_error:
        payload["repair_error"] = repair_error
    return user_content(payload, recent_utterances, list(current_images or []))


def planning_reply(*, envelope, instruction, recent_utterances=None, current_images=None):
    return [{"type": "text", "text": json.dumps({"instruction": instruction, "context": envelope}, ensure_ascii=False)},
            *image_parts(list(recent_utterances or []), list(current_images or []))]


def text_judge(*, text, task_title, problem_summary, images=None):
    body = json.dumps({"task_title": task_title, "problem": problem_summary, "reply": text}, ensure_ascii=False)
    return [{"type": "text", "text": body}, *image_parts([], images)] if images else body


def visual_judge(*, text, task_title, problem_summary):
    return json.dumps({"task_title": task_title, "problem": problem_summary, "visual": text}, ensure_ascii=False)


def image_target(*, window, content):
    return user_content({"student_said": content}, window)


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


BUILDERS = {
    "companion.intent.context": intent,
    "companion.scene_switch.context": scene_switch,
    "tutoring.turn.context": tutor_turn,
    "planning.reply.context": planning_reply,
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
