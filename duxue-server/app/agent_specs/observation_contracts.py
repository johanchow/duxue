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
    "behavior.eligibility": "持续状态与新鲜度判断",
    "behavior.delivery": "提示呈现与过期复核",
}
PHASES = {
    "behavior-visible-activity": ["prepare", "activity", "validate-activity"],
    "behavior-aggregate": ["aggregate"],
    "behavior-eligibility": ["eligibility"],
    "behavior-support-opportunity": ["support-images", "support", "validate-support"],
    "behavior-invitation": ["invitation"],
    "behavior-delivery": ["delivery"],
}
MAIN_NODES = {
    "prepare": "behavior.evidence",
    "activity": "behavior.visible-activity",
    "validate-activity": "behavior.validate-activity",
    "aggregate": "behavior.aggregate",
    "eligibility": "behavior.eligibility",
    "support-images": "behavior.evidence",
    "support": "behavior.support-opportunity",
    "validate-support": "behavior.validate-support",
    "invitation": "behavior.invitation",
    "delivery": "behavior.delivery",
}
WORKFLOWS = {
    "behavior-observation": list(MAIN_NODES.values()),
    "behavior-report": ["behavior.report"],
}
LEGACY_FILES = {f"workflows/{name}.json" for name in PHASES}
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
    for doc in result.values():
        doc["display_name"] = CODE_AGENTS[doc["id"]]
    nodes = [
        {"id": "behavior-observation." + key, "kind": "agent", "ref": ref}
        for key, ref in MAIN_NODES.items()
    ]
    path = ["START", *[n["id"] for n in nodes], "END"]
    edges = [{"from": a, "to": b} for a, b in zip(path, path[1:])]
    for edge in edges:
        if edge["from"] == "behavior-observation.eligibility":
            edge["condition_id"] = "eligible"
    edges.append(
        {
            "from": "behavior-observation.eligibility",
            "to": "END",
            "condition_id": "ineligible",
        }
    )
    result["workflows/behavior-observation.json"] = {
        "kind": "workflow",
        "id": "behavior-observation",
        "handler": "behavior-observation",
        "entry": nodes[0]["id"],
        "nodes": nodes,
        "edges": edges,
    }
    result["workflows/behavior-report.json"] = {
        "kind": "workflow",
        "id": "behavior-report",
        "handler": "behavior-report",
        "entry": "behavior-report.publish",
        "nodes": [
            {"id": "behavior-report.publish", "kind": "agent", "ref": "behavior.report"}
        ],
        "edges": [
            {"from": "START", "to": "behavior-report.publish"},
            {"from": "behavior-report.publish", "to": "END"},
        ],
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
