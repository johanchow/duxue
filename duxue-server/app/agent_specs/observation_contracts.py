"""Optional complete observation extension; no runtime model or Prompt defaults."""

import copy

from app.contexts.behavior_analysis.domain.model_contracts import (
    SupportOpportunityResult,
    VisibleActivityResult,
)

IDS = {
    "behavior.visible-activity": VisibleActivityResult,
    "behavior.support-opportunity": SupportOpportunityResult,
}
CODE_AGENTS = {
    "behavior.evidence": "受权图片准备",
    "behavior.validate-activity": "可见活动契约校验",
    "behavior.validate-support": "帮助机会契约校验",
    "behavior.aggregate": "观察日归并",
    "behavior.invitation": "邀请门禁与额度",
    "behavior.report": "晚间报告发布",
}
WORKFLOWS = {
    "behavior-visible-activity": [
        "behavior.evidence",
        "behavior.visible-activity",
        "behavior.validate-activity",
    ],
    "behavior-support-opportunity": [
        "behavior.evidence",
        "behavior.support-opportunity",
        "behavior.validate-support",
    ],
    "behavior-aggregate": ["behavior.aggregate"],
    "behavior-invitation": ["behavior.invitation"],
    "behavior-report": ["behavior.report"],
}
FILES = {f"agents/{identifier}.json" for identifier in {*IDS, *CODE_AGENTS}} | {
    f"workflows/{name}.json" for name in WORKFLOWS
}


def code_documents():
    return {
        f"agents/{identifier}.json": {
            "id": identifier,
            "kind": "agent",
            "implementation": "code",
            "handler_id": identifier,
            "input_schema": {"type": "object"},
            "output_schema": {"type": "object"},
            "error_codes": ["agent_execution_failed"],
        }
        for identifier in CODE_AGENTS
    }


def workflow_documents():
    result = code_documents()
    for name, identifiers in WORKFLOWS.items():
        nodes = [
            {"id": name + "." + str(index), "kind": "agent", "ref": identifier}
            for index, identifier in enumerate(identifiers)
        ]
        path = ["START", *[n["id"] for n in nodes], "END"]
        result[f"workflows/{name}.json"] = {
            "kind": "workflow",
            "id": name,
            "handler": name,
            "entry": nodes[0]["id"],
            "nodes": nodes,
            "edges": [{"from": a, "to": b} for a, b in zip(path, path[1:])],
        }
    return result


def frozen_contract(identifier):
    return {
        "id": identifier,
        "kind": "agent",
        "implementation": "llm",
        "agent_label": "reflection",
        "risk_tier": "standard",
        "operation": identifier,
        "input_contract": identifier + ".input.v1",
        "output_contract": identifier + ".output.v1",
        "input_schema": {
            "type": "object",
            "properties": {"user": {"type": "array"}},
            "required": ["user"],
            "additionalProperties": False,
        },
        "output_schema": IDS[identifier].model_json_schema(),
        "context_builder_id": identifier.replace("-", "_") + ".context",
        "prompt": {"id": identifier + ".prompt"},
        "models": [{"component_id": identifier}],
        "accepts_images": True,
        "requires_agent_switch": True,
        "error_codes": [
            "agent_execution_failed",
            "invalid_model_candidate",
            "model_provider_disabled",
            "model_provider_not_configured",
            "model_transport_error",
        ],
    }


def contracts():
    return {
        **{f"agents/{i}.json": frozen_contract(i) for i in IDS},
        **code_documents(),
    }


def provision(identifier, *, model, prompt):
    """Explicit import helper only; caller supplies editable values."""
    doc = copy.deepcopy(frozen_contract(identifier))
    doc["prompt"]["template"] = prompt
    doc["tools"] = []
    doc["models"][0].update(
        name=model, temperature=0, max_output_tokens=1600, timeout_ms=30000
    )
    return doc
