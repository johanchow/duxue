"""Execute a pinned turn graph with request-local domain data outside trace payloads."""

from app.agent_specs.runtime import GateDecision, execute_workflow
from app.agent_specs.tutoring_paths import PORTS
from app.application.ports.companion import WorkflowOutcome


def execute_turn(spec, turn):
    outcome = None

    def finish():
        if outcome is None:
            raise ValueError("turn has no deliverable outcome")
        return outcome

    operations = {
        "turn": turn.load,
        "close": turn.close,
        "intake": turn.intake,
        "blocked_input": turn.blocked_input,
        "understood": turn.understood,
        "media_access": turn.media_access,
        "reject_media": turn.reject_media,
        "image_target": turn.select_images,
        "clarify_image": turn.clarify_image,
        "self_review": lambda: "context_ready",
        "model_loop": turn.generate,
        "output_safety": turn.screen,
        "apply_problem": turn.apply_work,
        "answer": turn.answer,
        "fallback": turn.fallback,
        "blocked_output": turn.blocked_output,
        "pronounce": turn.pronounce,
        "clarify": turn.clarify,
        "result": finish,
    }

    def bind(name, operation):
        def run(state):
            nonlocal outcome
            value = operation()
            if isinstance(value, WorkflowOutcome):
                outcome = value
                value = "completed"
            if value not in PORTS[name][1]:
                raise ValueError(f"unexpected result from tutoring.{name}")
            state["decision"] = value
            if name == "output_safety":
                return GateDecision(
                    "deny" if value in {"failed", "unsafe_output"} else "allow", value
                )
            return {"decision": value}

        return run

    execute_workflow(
        spec,
        handlers={
            "tutoring." + name: bind(name, operation)
            for name, operation in operations.items()
        },
        conditions={
            edge.condition: (
                lambda state, expected=edge.condition: state["decision"] == expected
            )
            for edge in spec.edges
            if edge.condition
        },
        initial_state={"decision": "start"},
    )
    return finish()
