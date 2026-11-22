"""Replay the production solution workflow and project its result for grading."""

import json

from evals.outcome import Observation


def identity():
    from app.agent_specs.blueprint_steps import WORKFLOW_ID
    from app.agent_specs.catalog import load_catalog

    workflow = load_catalog().spec(WORKFLOW_ID)
    return {"execution_target": "solve", "workflow_id": workflow.id}


def execute(question: str, images: list[str]) -> Observation:
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
