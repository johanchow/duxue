"""Adult teaching materials built from page-level evidence and independent problem solves."""

from concurrent.futures import ThreadPoolExecutor
from contextvars import copy_context
from hashlib import sha256
import json
from dataclasses import dataclass
from fastapi import HTTPException

from app.agent_specs.catalog import load_catalog
from app.agent_specs.contexts import build_context
from app.agent_specs.definitions import load_definitions
from app.agent_specs.education_workspace import SkillChoice, UNITS
from app.agent_specs.release_runtime import configured_call
from app.agent_specs.runtime import execute_workflow
from app.application.ports.problem_solving import QwenProblemSolverGateway
from app.application.workflows.guardian_experience import _image
from app.application.workflows.guardian_mentor import _resolve_math_engine
from app.application.commands.problem_solving import solve_and_verify_problem
from app.contexts.problem_solving.domain.dossier import StructuredStem
from app.infrastructure.ai.errors import ModelGatewayError
from app.infrastructure.ai import components


def proposal(unit, payload, images=None):
    def invoke(state):
        spec = components.COMPONENTS.get(unit)
        try:
            raw = components.invoke_json_component(
                spec=spec, user=build_context(unit, payload=payload, images=images)
            )
        except ModelGatewayError as error:
            if str(error) != "invalid_model_candidate":
                raise
            corrected = {
                **payload,
                "required_output_fields": list(UNITS[unit].model_fields),
                "validation_error": "上一次结构错误。仅输出当前步骤要求的 JSON 字段。",
            }
            raw = components.invoke_json_component(
                spec=spec, user=build_context(unit, payload=corrected, images=images)
            )
        return UNITS[unit].model_validate(raw)

    name = unit.replace(".", "-")
    run = execute_workflow(
        load_catalog().spec(name), handlers={unit: invoke}, conditions={}
    )
    return UNITS[unit].model_validate(run["results"][name + ".run"].unwrap())


@dataclass(frozen=True)
class Document:
    kind: str
    title: str
    blocks: list[dict]
    source_images: tuple[str | None, ...] = ()
    # Application-owned evidence, independent of mutable delivery blocks.
    verified_items: tuple[str, ...] = ()


def evidence_digest(block):
    return sha256(
        json.dumps(block, sort_keys=True, ensure_ascii=False).encode()
    ).hexdigest()


def verify(stem):
    engine = _resolve_math_engine()
    result = solve_and_verify_problem(
        stem=StructuredStem(subject="general", raw_text=stem),
        solver=QwenProblemSolverGateway(),
        math_engine=engine,
        initial_tier="T2",
    )
    if (
        result
        and result.confidence == "high"
        and result.status == "ready"
        and result.final_answers
    ):
        return dict(result.final_answers)
    # For an entire arithmetic expression, the isolated grammar can verify
    # the final answer directly even when route milestones lack anchors.
    if (
        result
        and len(result.final_answers) == 1
        and result.evidence.get("comparison") == "consistent"
        and not result.evidence.get("stem_disputed")
    ):
        expression = stem.strip().removesuffix("=").strip()
        answer = next(iter(result.final_answers.values()))
        if engine.check_arithmetic([(expression, answer)], 3) == ["equal"]:
            return dict(result.final_answers)
    return {}


def assess(item):
    reviewed = {**item, "status": "needs_manual_review", "needs_manual_review": True}
    if not item["legible"] or not item["stem"].strip():
        return {**reviewed, "explanation": "题面、图形或作答信息不足"}
    try:
        answers = verify(item["stem"])
        if not answers:
            return {**reviewed, "explanation": "独立求解未形成可靠基准"}
        if item["kind"] == "variant_question":
            return {
                **item,
                "reference_answers": answers,
                "status": "verified",
                "needs_manual_review": False,
            }
        comparison = proposal(
            "edu.answer-compare", {**item, "reference_answers": answers}
        )
        return {
            **reviewed,
            "reference_answers": answers,
            "explanation": comparison.explanation,
            "status": comparison.verdict
            if comparison.verdict != "uncertain"
            else "needs_manual_review",
            "needs_manual_review": comparison.verdict == "uncertain",
        }
    except Exception:
        return {**reviewed, "explanation": "独立核验暂不可用"}


def verified_blocks(items):
    with ThreadPoolExecutor(max_workers=3) as pool:
        jobs = [pool.submit(copy_context().run, assess, item) for item in items]
        blocks = [job.result() for job in jobs]
    return blocks, tuple(
        evidence_digest(block) for block in blocks if not block["needs_manual_review"]
    )


@configured_call
def choose_skill(*, content, keys, previous, role, tool_results=None):
    from app.application.agent.role_policy import evaluate_role_policy
    from app.application.tools.core_tools import build_default_registries

    if "edu.skill-planner" not in load_definitions().units:
        return SkillChoice(skill="edu.homework_tutoring")
    _, skills = build_default_registries()
    catalog = skills.visible_catalog(evaluate_role_policy(role=role))
    choice = proposal(
        "edu.skill-planner",
        {
            "message": content,
            "page_count": len(keys),
            "previous": previous or {},
            "skills": catalog,
            "tool_results": tool_results or [],
            "general_tools": ["web.search"] if len(tool_results or []) < 2 else [],
        },
    )
    if choice.skill != "general" and choice.skill not in {
        item["id"] for item in catalog
    }:
        return SkillChoice(skill="general")
    return choice


@configured_call
def prepare(
    *,
    owner,
    content,
    keys,
    skill_hint=None,
    previous=None,
    source_images=None,
    thread_id=None,
    role="guardian",
):
    skill = (
        skill_hint
        or choose_skill(content=content, keys=keys, previous=previous, role=role).skill
    )
    if skill not in {"edu.lesson_pack", "edu.worksheet_grading"}:
        return None
    from app.application.agent.selected_skill import execute_selected_skill
    from app.application.commands.workspace_documents import honest

    kind = "lesson_pack" if skill == "edu.lesson_pack" else "grading_report"
    if kind == "grading_report" and not keys:
        raise HTTPException(422, "请按顺序上传需要批改的作业页")
    return execute_selected_skill(
        role=role,
        owner=owner,
        thread_id=thread_id,
        message=content,
        attachments=keys,
        skill=skill,
        tool="artifact.create_or_revise",
        arguments={"artifact_type": kind},
        invoke=lambda: build_document(
            owner=owner,
            content=content,
            keys=keys,
            skill=skill,
            previous=previous,
            source_images=source_images,
        ),
        gates={
            "artifact.verification_honesty": lambda phase, candidate: (
                phase == "write" or honest(phase, candidate)
            )
        },
        summarize=lambda document: document.title,
    )


def build_document(*, owner, content, keys, skill, previous, source_images=None):
    from app.application.tools.core_tools import build_default_registries

    _, skills = build_default_registries()
    request = {"request": content, "skill_instructions": skills.get(skill).instructions}
    images = (
        tuple(source_images)
        if source_images is not None
        else tuple(_image(owner, key) for key in keys)
    )
    if skill == "edu.lesson_pack":
        lesson = proposal(
            "edu.lesson-author",
            {**request, "previous": previous or {}},
            [image for image in images if image],
        )
        variants = [
            {"kind": "variant_question", "label": str(i), "stem": stem, "legible": True}
            for i, stem in enumerate(lesson.variants, 1)
        ]
        blocks, evidence = verified_blocks(variants)
        return Document(
            "lesson_pack",
            lesson.title,
            [{"kind": "teaching_notes", "text": lesson.teaching_notes}, *blocks],
            images,
            evidence,
        )
    if not keys:
        raise HTTPException(422, "请按顺序上传需要批改的作业页")
    items = []
    for page_no, image in enumerate(images, 1):
        try:
            page = (
                proposal("edu.worksheet-page", {**request, "page": page_no}, [image])
                if image
                else None
            )
        except ModelGatewayError:
            page = None
        if page:
            items.extend(
                {**q.model_dump(), "kind": "grading_item", "page": page_no}
                for q in page.questions
            )
        if not page or not page.complete or not page.questions:
            items.append(
                {
                    "kind": "grading_item",
                    "page": page_no,
                    "label": "未辨明部分",
                    "stem": "",
                    "legible": False,
                    "student_answer": "",
                }
            )
    blocks, evidence = verified_blocks(items)
    return Document("grading_report", "作业批改诊断", blocks, images, evidence)
