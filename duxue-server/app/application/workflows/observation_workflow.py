"""Execute the Admin-owned topology against reviewed observation handlers."""

from functools import wraps

from app.agent_specs.catalog import load_catalog
from app.agent_specs.release_runtime import pin_release
from app.agent_specs.runtime import execute_workflow


def execute_observation(workflow_id, handlers):
    from app.agent_specs.observation_contracts import PHASES

    with pin_release():
        if workflow_id == "behavior-report":
            return execute_workflow(load_catalog().spec(workflow_id), handlers=handlers)
        phase = PHASES[workflow_id]
        spec = load_catalog().spec("behavior-observation")
        keys = ["behavior-observation." + key for key in phase]
        boundary = {
            edge.target
            for edge in spec.edges
            if edge.source == keys[-1] and edge.target != "END"
        }

        def eligible(state):
            result = state["results"].get("behavior-observation.eligibility")
            return bool(result and result.unwrap().get("eligible"))

        return execute_workflow(
            spec,
            handlers=handlers,
            entry_node=keys[0],
            pause_before=boundary,
            conditions={
                "eligible": eligible,
                "ineligible": lambda state: not eligible(state),
            },
        )


def check_eligibility(eligible):
    execute_observation(
        "behavior-eligibility",
        {"behavior.eligibility": lambda _state: {"eligible": eligible}},
    )
    return eligible


def observation_step(identifier):
    """Keep durable command transactions in Python; execute the configured node."""

    def decorate(function):
        @wraps(function)
        def invoke(*args, **kwargs):
            result = []

            def run(_state):
                value = function(*args, **kwargs)
                result.append(value)
                return {"completed": True, "produced_result": value is not None}

            execute_observation(identifier.replace(".", "-"), {identifier: run})
            return result[0]

        return invoke

    return decorate


def validate_activity(payload, response):
    from datetime import datetime

    from app.contexts.behavior_analysis.domain.observation import (
        EvidenceFrame,
        Manifest,
        validate_outcome,
    )

    manifest = Manifest(
        payload["ward_id"],
        payload["camera_id"],
        payload["assignment_revision"],
        datetime.fromisoformat(payload["start"]),
        datetime.fromisoformat(payload["end"]),
        tuple(
            EvidenceFrame(f["id"], datetime.fromisoformat(f["at"]))
            for f in payload["frames"]
        ),
    )
    validate_outcome(manifest, response["cells"])
    return response


def validate_support(payload, response):
    from app.contexts.behavior_analysis.domain.support import validate_assessment

    validate_assessment(
        {k: v for k, v in response.items() if k != "provenance"},
        [f["id"] for f in payload["frames"]],
        has_learning_context=payload["learning_context"]["observed_learning"],
    )
    return response
