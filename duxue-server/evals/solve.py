"""Replay the production Guardian mentor-explanation workflow and project its result for grading."""

import json
from uuid import uuid4

from evals.outcome import Observation


def _has_mentor_workflow() -> bool:
    from app.agent_specs.catalog import load_catalog
    from app.agent_specs.guardian_contracts import MENTOR_WORKFLOW_ID

    return MENTOR_WORKFLOW_ID in load_catalog().specs


def identity():
    from app.agent_specs.blueprint_steps import WORKFLOW_ID
    from app.agent_specs.catalog import load_catalog
    from app.agent_specs.guardian_contracts import MENTOR_WORKFLOW_ID

    catalog = load_catalog()
    workflow = catalog.specs.get(MENTOR_WORKFLOW_ID) or catalog.spec(WORKFLOW_ID)
    return {"execution_target": "solve", "workflow_id": workflow.id}


def execute(question: str, images: list[str]) -> Observation:
    if _has_mentor_workflow():
        from app.application.workflows.guardian_mentor import explain_for_guardian

        answer = explain_for_guardian(
            guardian_id=f"eval-solve-{uuid4().hex}",
            content=question,
            attachment_keys=[],
            window=[],
            images=list(images),
            rows=[],
        )
        act = str(answer.get("act") or "")
        content = str(answer.get("content") or "")
        if act in {"explain", "answer"} and content.strip():
            return Observation("answer", content=content, delivered_content=content)
        if act == "clarify" and content.strip():
            return Observation("clarify", content=content, delivered_content=content)
        if act == "safety":
            return Observation(
                "blocked", reason="safety", content=content, delivered_content=content
            )
        return Observation(
            "fallback",
            reason=act or "unavailable",
            content=content,
            delivered_content=content,
        )

    from app.application.commands.problem_solving import execute_blueprint
    from app.application.ports.problem_solving import QwenProblemSolverGateway
    from app.bootstrap.math_engine import math_engine
    from app.contexts.problem_solving.domain.dossier import StructuredStem

    engine = math_engine()
    solution = execute_blueprint(
        stem=StructuredStem(subject="general", raw_text=question),
        question=question,
        images=images,
        solver=QwenProblemSolverGateway(math_engine=engine),
        math_engine=engine,
    )
    content = json.dumps(solution.mentor_projection(), ensure_ascii=False)
    has_answer = solution.status != "failed" and any(
        answer.strip() for answer in solution.final_answers.values()
    )
    return Observation(
        "answer" if has_answer else "fallback",
        reason=None if has_answer else solution.failure_reason or "no_final_answer",
        content=content,
        delivered_content=content,
    )
