"""Typed operation ports for executable Ward turns. Wiring is supplied by the release."""

from graphlib import TopologicalSorter
from uuid import UUID

from app.agent_specs.registrations import LEGACY_LOOP, MODEL_LOOP

# Node id, accepted input facts, possible output facts. Disjoint input sets keep a
# denied candidate away from any handler that could display or persist its text.
PORTS = {
    "turn": ({"start"}, {"closing", "open"}),
    "close": ({"closing"}, {"completed"}),
    "intake": ({"open"}, {"unsafe_input", "confirmed", "question"}),
    "blocked_input": ({"unsafe_input"}, {"completed"}),
    "understood": ({"confirmed"}, {"completed"}),
    "media_access": ({"question"}, {"foreign_media", "authorized"}),
    "reject_media": ({"foreign_media"}, {"completed"}),
    "image_target": ({"authorized"}, {"ambiguous", "resolved"}),
    "clarify_image": ({"ambiguous"}, {"completed"}),
    "self_review": ({"resolved"}, {"context_ready"}),
    "model_loop": ({"resolved", "context_ready"}, {"generated"}),
    "output_safety": (
        {"generated"},
        {"work", "conversation", "failed", "unsafe_output", "pronounce", "clarify"},
    ),
    "apply_problem": ({"work"}, {"applied"}),
    "answer": ({"applied", "conversation"}, {"completed"}),
    "fallback": ({"failed"}, {"completed"}),
    "blocked_output": ({"unsafe_output"}, {"completed"}),
    "pronounce": ({"pronounce"}, {"completed"}),
    "clarify": ({"clarify"}, {"completed"}),
    "result": ({"completed"}, {"completed"}),
}

SPECIAL_BINDINGS = {
    "image_target": ("agent", "tutoring.image-target"),
    "model_loop": ("workflow", MODEL_LOOP),
    "output_safety": ("gate", "tutoring.output_safety"),
}


def validate_paths(spec):
    if spec.id != "tutoring" or spec.entry != "tutoring.turn":
        raise ValueError("invalid executable turn entry")
    inputs = {"END": {"completed"}}
    outputs = {"START": {"start"}}
    nodes = {node.id: node for node in spec.nodes}
    for name, (accepts, produces) in PORTS.items():
        key = f"tutoring.{name}"
        node = nodes.get(key)
        if name == "self_review" and node is None:
            continue
        expected = SPECIAL_BINDINGS.get(name, ("action", key))
        if name == "model_loop" and node and node.ref == LEGACY_LOOP:
            expected = ("workflow", LEGACY_LOOP)
        if name == "model_loop" and node and node.kind == "action":
            # Historical releases use the same operation with an action binding.
            expected = ("action", key)
        if not node or (node.kind, node.ref or node.handler) != expected:
            raise ValueError(f"missing or invalid executable turn binding: {key}")
        inputs[key], outputs[key] = accepts, produces
    graph = TopologicalSorter()
    covered = {key: set() for key in outputs}
    for edge in spec.edges:
        facts = outputs.get(edge.source)
        if not facts or edge.target not in inputs or edge.via:
            raise ValueError("unexpected executable turn edge")
        branch = {edge.condition} if edge.condition else facts
        if (
            not branch <= facts
            or not branch <= inputs[edge.target]
            or covered[edge.source] & branch
        ):
            raise ValueError(
                f"unsafe or ambiguous turn edge: {edge.source} -> {edge.target}"
            )
        covered[edge.source].update(branch)
        graph.add(edge.target, edge.source)
    graph.prepare()
    if covered != outputs:
        raise ValueError("missing executable turn outcome")


def new_run_version(spec, run_id):
    """Assign once at run creation. Rollback to a legacy release overrides the pin."""
    if spec.execution and UUID(run_id).int % 100 < spec.rollout_percent:
        return "turn_graph"
    return "v1"
