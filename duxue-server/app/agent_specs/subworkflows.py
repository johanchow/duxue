"""Reviewed subworkflow call sites in the tutoring loop."""

from contextlib import contextmanager

RETRY_NODE = "tutoring.model_loop"
VET_NODE = "tutoring.review_candidate"
MATH_NODE = "tutoring.math_consistency"
CALL_TARGETS = {RETRY_NODE: "tutoring-retry", VET_NODE: "tutoring-vet"}


def upgrade_files(files):
    flow = files["workflows/tutoring.json"]
    nodes = {node["id"]: node for node in flow["nodes"]}
    loop = nodes[RETRY_NODE]
    if loop["kind"] == "workflow":
        return
    loop.pop("handler_id")
    loop.update(
        kind="workflow", ref=CALL_TARGETS[RETRY_NODE], display_name="生成与重试"
    )
    flow["nodes"].extend(
        [
            {
                "id": MATH_NODE,
                "kind": "gate",
                "ref": "tutoring.leak-judge",
                "trace": MATH_NODE,
                "trace_kind": "check",
                "display_name": "数学一致性检查",
                "parent": "tutoring.exit_gate",
            },
            {
                "id": VET_NODE,
                "kind": "workflow",
                "ref": CALL_TARGETS[VET_NODE],
                "trace": VET_NODE,
                "trace_kind": "check",
                "display_name": "教学与答案保护审核",
                "parent": "tutoring.exit_gate",
            },
        ]
    )
    flow["edges"].extend(
        [
            {"from": "tutoring.exit_gate", "to": MATH_NODE},
            {"from": MATH_NODE, "to": VET_NODE, "condition_id": "math_allowed"},
        ]
    )


@contextmanager
def math_review_step(explicit_calls):
    """Bind the shared Judge to the math node for this invocation only."""
    from app.agent_specs.catalog import executing_node
    from app.infrastructure.observability.telemetry import agent_step_span

    if not explicit_calls:
        yield None
        return
    token = executing_node.set(("tutoring", MATH_NODE))
    try:
        with agent_step_span("check", MATH_NODE) as span:
            yield span
    finally:
        executing_node.reset(token)
