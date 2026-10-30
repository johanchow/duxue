"""Second, Python-owned validation layer for model I/O contracts."""

from __future__ import annotations

from jsonschema import Draft202012Validator

from app.agent_specs.definitions import ModelUnit


def validate_input(unit: ModelUnit, user: str | list[dict]) -> None:
    Draft202012Validator(unit.input_schema).validate({"user": user})
    if isinstance(user, str):
        return
    if not isinstance(user, list) or any(
        not isinstance(part, dict) or part.get("type") not in {"text", "image_url"}
        for part in user
    ):
        raise ValueError(f"{unit.id}: invalid model input parts")


def validate_output(unit: ModelUnit, payload: dict) -> None:
    schema = unit.provider_output_schema or (unit.verdict_schema if unit.kind == "gate" else unit.output_schema)
    assert schema is not None
    Draft202012Validator(schema).validate(payload)
    unit_id = unit.id
    if unit_id == "companion.intent":
        if payload["intent"] not in {"planning", "tutoring", "reflection", "unclear"}:
            raise ValueError("invalid intent")
    elif unit_id == "companion.scene-switch":
        if type(payload["allow_switch"]) is not bool:
            raise ValueError("invalid switch verdict")
    elif unit_id == "planning.reply":
        from app.infrastructure.ai.model_gateway import AgentTextCandidate
        AgentTextCandidate.model_validate(payload)
    elif unit_id == "planning.intake":
        from app.application.commands.plan_intake import PlanIntakeResult
        PlanIntakeResult.model_validate(payload)
    elif unit_id == "task.intake":
        from app.application.commands.task_intake import TaskIntakeResult
        TaskIntakeResult.model_validate(payload)
    elif unit_id == "tutoring.turn":
        if "tool" in payload:
            if not isinstance(payload["tool"], str):
                raise ValueError("invalid tool request")
        else:
            from app.application.workflows.tutor_turn import TutorTurnCandidate
            TutorTurnCandidate.model_validate(payload)
    elif unit_id == "evaluation.review-aspects":
        if not all(isinstance(row, dict) for row in payload["aspects"]):
            raise ValueError("invalid review aspects")
    elif unit_id == "tutoring.image-target":
        if ("ambiguous" not in payload and "target_image_ids" not in payload):
            raise ValueError("missing image target")
    elif unit_id == "tutoring.leak-judge":
        pass  # All semantic facts are typed by provider_output_schema above.
    elif unit_id == "tutoring.visual-leak-judge":
        if type(payload["leaks"]) is not bool:
            raise ValueError("invalid leak verdict")
    else:
        raise ValueError(f"unregistered Python output contract: {unit_id}")
    if unit.kind == "gate":
        from app.agent_specs.verdicts import normalize_judge
        verdict = normalize_judge(unit_id, payload)
        Draft202012Validator(unit.verdict_schema).validate(verdict.model_dump())


def has_python_contract(unit_id: str) -> bool:
    return unit_id in {
        "companion.intent", "companion.scene-switch", "planning.reply", "planning.intake",
        "task.intake", "tutoring.turn", "evaluation.review-aspects",
        "tutoring.image-target", "tutoring.leak-judge", "tutoring.visual-leak-judge",
    }
