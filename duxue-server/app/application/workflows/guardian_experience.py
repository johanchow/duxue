"""Guardian-only tutoring sandbox. No Ward lookup, persistence, or learning facts."""
from __future__ import annotations

import base64
import json
from dataclasses import asdict
from pathlib import Path
from typing import Literal
from uuid import uuid4

from app.agent_specs.release_runtime import pin_release
from app.application.queries.run_transcript import select_recent_utterances
from app.application.workflows.guardian_mentor import explain_for_guardian
from app.application.workflows.image_target import prepare_images
from app.application.workflows.teaching_skills import history_candidates
from app.application.workflows.tutor_loop import judge_problem_summary, run_tutor_turn
from app.application.workflows.tutor_tools import TutorToolbox
from app.application.workflows.tutor_turn import (
    SAFE_TEXT,
    build_tutor_instruction,
    fallback_text,
)
from app.application.workflows.tutor_visual import describe
from app.contexts.tutoring.domain.tutor_permit import (
    ProblemAssessment,
    ProblemState,
    TutorPermitPolicy,
)
from app.infrastructure.ai.tutor_turn_model import QwenLeakJudge, QwenTutorTurnGateway
from app.infrastructure.ai.tutoring_safety import LocalSafetyScreening
from app.infrastructure.security.experience_tokens import seal
from app.infrastructure.storage.object_storage import storage


def media_prefix(guardian_id: str) -> str:
    return f"guardian/{guardian_id}/experience/"


def owns_image(guardian_id: str, key: str) -> bool:
    prefix = media_prefix(guardian_id)
    return (key.startswith(prefix) and bool(key[len(prefix):])
            and "/" not in key[len(prefix):] and "\\" not in key[len(prefix):]
            and Path(key).suffix.lower() in {".jpg", ".jpeg", ".png", ".webp"})


def _image(guardian_id: str, key: str) -> str | None:
    if not owns_image(guardian_id, key):
        return None
    try:
        raw = storage.read_bytes(key)
        if len(raw) > 10 * 1024 * 1024:
            return None
        mime = {".png": "image/png", ".webp": "image/webp"}.get(Path(key).suffix.lower(), "image/jpeg")
        return f"data:{mime};base64,{base64.b64encode(raw).decode()}"
    except (FileNotFoundError, OSError):
        return None


ExperienceMode = Literal["student_guide", "guardian_explain"]


def experience_turn(
    *,
    guardian_id: str,
    content: str,
    attachment_keys: list[str],
    state: dict,
    mode: ExperienceMode = "student_guide",
    bank_lookup=None,
) -> dict:
    with pin_release():
        return _turn(
            guardian_id=guardian_id,
            content=content,
            attachment_keys=attachment_keys,
            state=state,
            mode=mode,
            bank_lookup=bank_lookup,
        )


def _prepare_adult_window(guardian_id: str, rows: list[dict], attachment_keys: list[str]) -> tuple[list[dict], list[str | None]]:
    window: list[dict] = []
    image_budget = 0 if attachment_keys else 8
    for row in reversed(rows):
        keys = row.get("attachment_refs", [])[-image_budget:] if image_budget else []
        image_budget -= len(keys)
        view: dict = {"author": row["author"], "text": row["text"]}
        if keys:
            view["image_urls"] = [_image(guardian_id, key) for key in keys]
        elif row.get("attachment_refs"):
            view["had_images"] = True
        window.insert(0, view)
    images = [_image(guardian_id, key) for key in attachment_keys]
    return window, images


def _turn(
    *,
    guardian_id: str,
    content: str,
    attachment_keys: list[str],
    state: dict,
    mode: ExperienceMode = "student_guide",
    bank_lookup=None,
) -> dict:
    rows = state.get("window", [])
    window, images = _prepare_adult_window(guardian_id, rows, attachment_keys)
    if mode == "guardian_explain":
        return explain_for_guardian(
            guardian_id=guardian_id,
            content=content,
            attachment_keys=attachment_keys,
            window=window,
            images=images,
            rows=rows,
            bank_lookup=bank_lookup,
        )
    prepared = prepare_images(window, images, content=content)
    answer = {"content": "这次图片没有读取成功或指向不明确，请重新拍照或说明要看哪一张。", "act": "clarify"}
    problem = ProblemState(**state["problem"]) if state.get("problem") else None
    summaries = state.get("summaries", [])
    safety = LocalSafetyScreening()
    if safety.blocks_input(text=content):
        answer = {"content": SAFE_TEXT, "act": "safety"}
    elif not prepared.target.ambiguous:
        permit = TutorPermitPolicy.permit(problem)
        window, images = prepared.window, prepared.images
        tools = TutorToolbox(None, tutoring_session_id=None, problem=None,
                             task_title=None, task_active=False, window=window)
        result = run_tutor_turn(
            QwenTutorTurnGateway(),
            {"actor": {"role": "guardian", "experience": True}, "objective": {"agent_type": "tutoring"},
             "session": {}, "memory": [], "profile": {}, "signals": []},
            build_tutor_instruction(content=content, permit=permit, history_candidates=history_candidates(window), tutoring_intent=None),
            window, images, tools, permit=permit, leak_judge=QwenLeakJudge(),
            task_title=None, problem_summary=judge_problem_summary(summaries, content, recent_utterances=window),
            backup_model=QwenTutorTurnGateway(component_id="tutoring.turn-backup"),
            judge_images=[url for url in [*(url for row in window for url in row.get("image_urls", [])), *images] if url],
        )
        vetted = result.vetting
        if vetted is None or vetted.failure:
            answer = {"content": fallback_text(vetted.failure if vetted else result.call.failure,
                                              vetted.leak_reason if vetted else None), "act": "unavailable"}
        else:
            candidate = vetted.candidate
            review = candidate.content + (describe(vetted.visual) if vetted.visual else "")
            review += json.dumps([lesson.model_dump() for lesson in candidate.lessons], ensure_ascii=False)
            if candidate.act == "safety" or safety.blocks_output(text=review):
                answer = {"content": SAFE_TEXT, "act": "safety"}
            else:
                answer = {"content": candidate.content, "act": candidate.act}
                if vetted.visual:
                    answer["visual"] = vetted.visual.model_dump(mode="json")
                if candidate.lessons:
                    answer["lessons"] = [
                        {**lesson.model_dump(), "supported_rates": [0.5, 0.75, 1.0],
                         "speech_ref": seal(guardian_id, "speech", lesson.model_dump())}
                        for lesson in candidate.lessons
                    ]
                if candidate.work:
                    if candidate.relation in {"new", "subproblem"}:
                        problem = None
                        summaries = [content[:500], *summaries][:3]
                    elif not summaries:
                        summaries = [content[:500]]
                    problem = TutorPermitPolicy.advance(problem, ProblemAssessment(
                        effective_work_product=True, student_move=candidate.student_move,
                        progress=candidate.progress, act=candidate.act,
                        counts_as_attempt=bool(content.strip()), subgoal_evidence=candidate.subgoal_evidence,
                        next_subgoal=candidate.next_subgoal,
                    ))
    turn_id = str(uuid4())
    rows = [*rows, {"turn_id": turn_id, "author": "ward", "text": content, "attachment_refs": attachment_keys},
            {"turn_id": turn_id, "author": "companion", "text": answer["content"]}]
    rows, _ = select_recent_utterances(rows, exclude_turn_id=None)
    answer["mode"] = "student_guide"
    answer["state_token"] = seal(guardian_id, "conversation", {
        "window": rows, "problem": asdict(problem) if problem else None, "summaries": summaries,
    })
    return answer
