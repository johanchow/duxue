"""Reviewed subworkflow call sites and parallel vetting topology in the tutoring loop."""

from contextlib import contextmanager

from app.agent_specs.registrations import LEGACY_LOOP, LEGACY_REVIEW, MODEL_LOOP, REVIEW

RETRY_NODE = MODEL_LOOP
VET_NODE = REVIEW
MATH_NODE = "tutoring.math_consistency"
VET_MATH_NODE = "tutoring-vet.math_consistency"

def review_workflow_id(specs):
    return LEGACY_REVIEW if LEGACY_REVIEW in specs else REVIEW


def call_targets(specs):
    return {RETRY_NODE: LEGACY_LOOP if LEGACY_LOOP in specs else MODEL_LOOP,
            VET_NODE: review_workflow_id(specs)}


PARALLEL_VET_CONDITIONS = frozenset(
    {
        "authority_allowed_no_review",
        "needs_math_review",
        "needs_text_review",
        "needs_visual_review",
    }
)

COMPACT_LOOP_CONDITIONS = frozenset(
    {
        "needs_repair",
        "accepted_or_terminal",
    }
)


def compact_model_loop_workflow(workflow_id=MODEL_LOOP) -> dict:
    """Streamlined 3-action tutoring model loop (`primary -> repair -> finish`)."""
    p = f"{workflow_id}.primary"
    r = f"{workflow_id}.repair"
    f = f"{workflow_id}.finish"
    return {
        "kind": "workflow",
        "id": workflow_id,
        "handler": workflow_id,
        "entry": p,
        "nodes": [
            {
                "id": p,
                "kind": "action",
                "handler_id": "primary",
                "display_name": "首次生成与审核",
            },
            {
                "id": r,
                "kind": "action",
                "handler_id": "repair",
                "display_name": "统一修复与重试",
            },
            {
                "id": f,
                "kind": "action",
                "handler_id": "finish",
                "display_name": "汇总候选与降级",
            },
        ],
        "edges": [
            {"from": "START", "to": p},
            {"from": p, "to": r, "condition_id": "needs_repair"},
            {"from": p, "to": f, "condition_id": "accepted_or_terminal"},
            {"from": r, "to": f},
            {"from": f, "to": "END"},
        ],
    }


def parallel_vet_workflow(workflow_id=LEGACY_REVIEW) -> dict:
    """Declarative fan-out/fan-in topology for tutoring-vet stored in Admin releases."""
    return {
        "kind": "workflow",
        "id": workflow_id,
        "version": "v1",
        "handler": workflow_id,
        "entry": f"{workflow_id}.authority",
        "nodes": [
            {
                "id": f"{workflow_id}.authority",
                "kind": "gate",
                "ref": "tutoring.authority",
                "trace": "tutoring.authority",
                "display_name": "教学权限与本地证据校验",
                "required": True,
            },
            {
                "id": f"{workflow_id}.math_consistency",
                "kind": "gate",
                "ref": "tutoring.leak-judge",
                "trace": MATH_NODE,
                "trace_kind": "check",
                "display_name": "数学一致性检查",
            },
            {
                "id": f"{workflow_id}.text_leak",
                "kind": "gate",
                "ref": "tutoring.leak-judge",
                "trace": "tutoring.text_leak",
                "display_name": "正文答案保护审核",
                "required": True,
            },
            {
                "id": f"{workflow_id}.visual_leak",
                "kind": "gate",
                "ref": "tutoring.visual-leak-judge",
                "trace": "tutoring.visual_leak",
                "display_name": "配图答案保护审核",
                "required": True,
            },
            {
                "id": f"{workflow_id}.complete",
                "kind": "action",
                "handler_id": "tutoring.complete_vetting",
                "display_name": "按优先级汇总裁决",
            },
        ],
        "edges": [
            {"from": "START", "to": f"{workflow_id}.authority"},
            {
                "from": f"{workflow_id}.authority",
                "to": f"{workflow_id}.complete",
                "condition_id": "authority_denied",
            },
            {
                "from": f"{workflow_id}.authority",
                "to": f"{workflow_id}.complete",
                "condition_id": "authority_allowed_no_review",
            },
            {
                "from": f"{workflow_id}.authority",
                "to": f"{workflow_id}.math_consistency",
                "condition_id": "needs_math_review",
            },
            {
                "from": f"{workflow_id}.authority",
                "to": f"{workflow_id}.text_leak",
                "condition_id": "needs_text_review",
            },
            {
                "from": f"{workflow_id}.authority",
                "to": f"{workflow_id}.visual_leak",
                "condition_id": "needs_visual_review",
            },
            {"from": f"{workflow_id}.math_consistency", "to": f"{workflow_id}.complete"},
            {"from": f"{workflow_id}.text_leak", "to": f"{workflow_id}.complete"},
            {"from": f"{workflow_id}.visual_leak", "to": f"{workflow_id}.complete"},
            {"from": f"{workflow_id}.complete", "to": "END"},
        ],
        "required_gates": [
            {"ref": "tutoring.authority", "when": "always"},
            {"ref": "tutoring.leak-judge", "when": "requires_text_leak"},
            {"ref": "tutoring.visual-leak-judge", "when": "requires_visual_leak"},
        ],
    }


def has_parallel_vet(catalog) -> bool:
    """Return True when the pinned tutoring-vet topology declares parallel math/text/visual fan-out."""
    spec = catalog.spec(review_workflow_id(catalog.specs))
    return any(node.id == f"{spec.id}.math_consistency" for node in spec.nodes)


def upgrade_files(files):
    review_id = REVIEW if f"workflows/{REVIEW}.json" in files else LEGACY_REVIEW
    review_path = f"workflows/{review_id}.json"
    review_title = "候选回复审核" if review_id == REVIEW else "出口并行审核"
    flow = files["workflows/tutoring.json"]
    nodes = {node["id"]: node for node in flow["nodes"]}
    loop = nodes[RETRY_NODE]
    if loop["kind"] != "workflow":
        loop.pop("handler_id", None)
        loop.update(
            kind="workflow", ref=LEGACY_LOOP if f"workflows/{LEGACY_LOOP}.json" in files else MODEL_LOOP, display_name="生成与重试"
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
                "ref": review_id,
                "trace": VET_NODE,
                "trace_kind": "check",
                "display_name": review_title,
                "parent": "tutoring.exit_gate",
            }
        )
    else:
        for node in flow["nodes"]:
            if node["id"] == VET_NODE:
                node["display_name"] = review_title
    if not any(
        edge.get("from") == "tutoring.exit_gate" and edge.get("to") == VET_NODE
        for edge in flow["edges"]
    ):
        flow["edges"].append({"from": "tutoring.exit_gate", "to": VET_NODE})

    # Upgrade tutoring-vet.json to declarative parallel fan-out/fan-in topology.
    vet_doc = parallel_vet_workflow(review_id)
    existing_vet = files.get(review_path)
    if isinstance(existing_vet, dict) and "version" in existing_vet:
        vet_doc["version"] = existing_vet["version"]
    else:
        vet_doc.pop("version", None)
    files[review_path] = vet_doc


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
