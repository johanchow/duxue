"""Reviewed subworkflow call sites and parallel vetting topology in the tutoring loop."""

from contextlib import contextmanager

RETRY_NODE = "tutoring.model_loop"
VET_NODE = "tutoring.review_candidate"
MATH_NODE = "tutoring.math_consistency"
VET_MATH_NODE = "tutoring-vet.math_consistency"
CALL_TARGETS = {RETRY_NODE: "tutoring-retry", VET_NODE: "tutoring-vet"}

PARALLEL_VET_CONDITIONS = frozenset(
    {
        "authority_allowed_no_review",
        "needs_math_review",
        "needs_text_review",
        "needs_visual_review",
    }
)


def parallel_vet_workflow() -> dict:
    """Declarative fan-out/fan-in topology for tutoring-vet stored in Admin releases."""
    return {
        "kind": "workflow",
        "id": "tutoring-vet",
        "version": "v1",
        "handler": "tutoring-vet",
        "entry": "tutoring-vet.authority",
        "nodes": [
            {
                "id": "tutoring-vet.authority",
                "kind": "gate",
                "ref": "tutoring.authority",
                "trace": "tutoring.authority",
                "display_name": "教学权限与本地证据校验",
                "required": True,
            },
            {
                "id": VET_MATH_NODE,
                "kind": "gate",
                "ref": "tutoring.leak-judge",
                "trace": MATH_NODE,
                "trace_kind": "check",
                "display_name": "数学一致性检查",
            },
            {
                "id": "tutoring-vet.text_leak",
                "kind": "gate",
                "ref": "tutoring.leak-judge",
                "trace": "tutoring.text_leak",
                "display_name": "正文答案保护审核",
                "required": True,
            },
            {
                "id": "tutoring-vet.visual_leak",
                "kind": "gate",
                "ref": "tutoring.visual-leak-judge",
                "trace": "tutoring.visual_leak",
                "display_name": "配图答案保护审核",
                "required": True,
            },
            {
                "id": "tutoring-vet.complete",
                "kind": "action",
                "handler_id": "tutoring.complete_vetting",
                "display_name": "按优先级汇总裁决",
            },
        ],
        "edges": [
            {"from": "START", "to": "tutoring-vet.authority"},
            {
                "from": "tutoring-vet.authority",
                "to": "tutoring-vet.complete",
                "condition_id": "authority_denied",
            },
            {
                "from": "tutoring-vet.authority",
                "to": "tutoring-vet.complete",
                "condition_id": "authority_allowed_no_review",
            },
            {
                "from": "tutoring-vet.authority",
                "to": VET_MATH_NODE,
                "condition_id": "needs_math_review",
            },
            {
                "from": "tutoring-vet.authority",
                "to": "tutoring-vet.text_leak",
                "condition_id": "needs_text_review",
            },
            {
                "from": "tutoring-vet.authority",
                "to": "tutoring-vet.visual_leak",
                "condition_id": "needs_visual_review",
            },
            {"from": VET_MATH_NODE, "to": "tutoring-vet.complete"},
            {"from": "tutoring-vet.text_leak", "to": "tutoring-vet.complete"},
            {"from": "tutoring-vet.visual_leak", "to": "tutoring-vet.complete"},
            {"from": "tutoring-vet.complete", "to": "END"},
        ],
        "required_gates": [
            {"ref": "tutoring.authority", "when": "always"},
            {"ref": "tutoring.leak-judge", "when": "requires_text_leak"},
            {"ref": "tutoring.visual-leak-judge", "when": "requires_visual_leak"},
        ],
    }


def has_parallel_vet(catalog) -> bool:
    """Return True when the pinned tutoring-vet topology declares parallel math/text/visual fan-out."""
    spec = catalog.spec("tutoring-vet")
    return any(node.id == VET_MATH_NODE for node in spec.nodes)


def upgrade_files(files):
    flow = files["workflows/tutoring.json"]
    nodes = {node["id"]: node for node in flow["nodes"]}
    loop = nodes[RETRY_NODE]
    if loop["kind"] != "workflow":
        loop.pop("handler_id", None)
        loop.update(
            kind="workflow", ref=CALL_TARGETS[RETRY_NODE], display_name="生成与重试"
        )
    # Remove legacy serial MATH_NODE from tutoring.json if present; math review now lives inside
    # tutoring-vet.json as a declarative parallel branch alongside text_leak & visual_leak.
    flow["nodes"] = [node for node in flow["nodes"] if node["id"] != MATH_NODE]
    flow["edges"] = [
        edge
        for edge in flow["edges"]
        if edge.get("from") != MATH_NODE and edge.get("to") != MATH_NODE
    ]
    if not any(node["id"] == VET_NODE for node in flow["nodes"]):
        flow["nodes"].append(
            {
                "id": VET_NODE,
                "kind": "workflow",
                "ref": CALL_TARGETS[VET_NODE],
                "trace": VET_NODE,
                "trace_kind": "check",
                "display_name": "出口并行审核",
                "parent": "tutoring.exit_gate",
            }
        )
    else:
        for node in flow["nodes"]:
            if node["id"] == VET_NODE:
                node["display_name"] = "出口并行审核"
    if not any(
        edge.get("from") == "tutoring.exit_gate" and edge.get("to") == VET_NODE
        for edge in flow["edges"]
    ):
        flow["edges"].append({"from": "tutoring.exit_gate", "to": VET_NODE})

    # Upgrade tutoring-vet.json to declarative parallel fan-out/fan-in topology.
    vet_doc = parallel_vet_workflow()
    existing_vet = files.get("workflows/tutoring-vet.json")
    if isinstance(existing_vet, dict) and "version" in existing_vet:
        vet_doc["version"] = existing_vet["version"]
    else:
        vet_doc.pop("version", None)
    files["workflows/tutoring-vet.json"] = vet_doc


@contextmanager
def math_review_step(explicit_calls):
    """Bind the shared Judge to the legacy serial math node when running pre-parallel snapshots."""
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
