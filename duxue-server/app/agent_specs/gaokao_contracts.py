"""Optional Gaokao blueprint & science/vision tool contracts.

Preserves byte-for-byte compatibility fingerprints of existing published Admin
artifacts when these optional files are absent.
"""

from __future__ import annotations

import copy

from app.application.ports.image_inspection import InspectImageRequest
from app.application.ports.math_engine import MathInput

PLANNER_ID = "tutoring.blueprint-planner"
SCIENCE_TOOL_ID = "tutoring.science"
INSPECT_IMAGE_TOOL_ID = "tutoring.inspect_image"
WORKFLOW_ID = "tutoring-blueprint"
WORKFLOWS = {WORKFLOW_ID: [PLANNER_ID]}

FILES = frozenset(
    {
        f"agents/{PLANNER_ID}.json",
        f"tools/{SCIENCE_TOOL_ID}.json",
        f"tools/{INSPECT_IMAGE_TOOL_ID}.json",
        f"workflows/{WORKFLOW_ID}.json",
    }
)

TOOL_AUTHORITY_ADDITIONS = (SCIENCE_TOOL_ID, INSPECT_IMAGE_TOOL_ID)


def _planner_output_schema() -> dict:
    return {
        "type": "object",
        "properties": {
            "subject": {"type": "string"},
            "shared_stem_ref": {"type": ["string", "null"]},
            "shared_stem_summary": {"type": ["string", "null"]},
            "subproblem_label": {"type": ["string", "null"]},
            "implicit_constraints": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "id": {"type": "string"},
                        "expression": {"type": "string"},
                        "description": {"type": "string"},
                    },
                    "required": ["id", "expression"],
                    "additionalProperties": True,
                },
            },
            "approaches": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "id": {"type": "string"},
                        "name": {"type": "string"},
                        "milestones": {
                            "type": "array",
                            "items": {
                                "type": "object",
                                "properties": {
                                    "id": {"type": "string"},
                                    "goal": {"type": "string"},
                                    "check_kind": {"type": "string"},
                                    "canonical_target": {"type": ["string", "null"]},
                                    "verify_request": {"type": ["object", "null"]},
                                    "common_pitfalls": {
                                        "type": "array",
                                        "items": {"type": "string"},
                                    },
                                },
                                "required": ["id", "goal"],
                                "additionalProperties": True,
                            },
                        },
                    },
                    "required": ["id", "name", "milestones"],
                    "additionalProperties": True,
                },
            },
        },
        "required": ["subject", "approaches"],
        "additionalProperties": True,
    }


def frozen_contracts() -> dict[str, dict]:
    return {
        f"agents/{PLANNER_ID}.json": {
            "id": PLANNER_ID,
            "kind": "agent",
            "implementation": "llm",
            "agent_label": "tutoring",
            "risk_tier": "protected",
            "operation": PLANNER_ID,
            "input_contract": PLANNER_ID + ".input.v1",
            "output_contract": PLANNER_ID + ".output.v1",
            "input_schema": {
                "type": "object",
                "properties": {
                    "user": {"oneOf": [{"type": "string"}, {"type": "array"}]}
                },
                "required": ["user"],
                "additionalProperties": False,
            },
            "output_schema": _planner_output_schema(),
            "context_builder_id": "tutoring.blueprint_planner.context",
            "prompt": {"id": PLANNER_ID + ".prompt"},
            "models": [{"component_id": PLANNER_ID}],
            "accepts_images": True,
            "requires_agent_switch": True,
            "error_codes": [
                "agent_execution_failed",
                "invalid_model_candidate",
                "model_provider_disabled",
                "model_provider_not_configured",
                "model_transport_error",
            ],
        },
        f"tools/{SCIENCE_TOOL_ID}.json": {
            "id": SCIENCE_TOOL_ID,
            "kind": "tool",
            "input_schema": MathInput.model_json_schema(),
            "output_schema": {
                "type": "object",
                "properties": {"status": {"type": "string"}},
                "required": ["status"],
                "additionalProperties": True,
            },
            "handler_id": SCIENCE_TOOL_ID,
            "access": "read",
        },
        f"tools/{INSPECT_IMAGE_TOOL_ID}.json": {
            "id": INSPECT_IMAGE_TOOL_ID,
            "kind": "tool",
            "input_schema": InspectImageRequest.model_json_schema(),
            "output_schema": {
                "type": "object",
                "properties": {"status": {"type": "string"}},
                "required": ["status"],
                "additionalProperties": True,
            },
            "handler_id": INSPECT_IMAGE_TOOL_ID,
            "access": "read",
        },
    }


def workflow_documents() -> dict[str, dict]:
    return {
        f"workflows/{WORKFLOW_ID}.json": {
            "kind": "workflow",
            "id": WORKFLOW_ID,
            "handler": WORKFLOW_ID,
            "entry": f"{WORKFLOW_ID}.plan",
            "nodes": [
                {
                    "id": f"{WORKFLOW_ID}.plan",
                    "kind": "agent",
                    "ref": PLANNER_ID,
                }
            ],
            "edges": [
                {"from": "START", "to": f"{WORKFLOW_ID}.plan"},
                {"from": f"{WORKFLOW_ID}.plan", "to": "END"},
            ],
        }
    }


def provision_planner(*, model: str, prompt: str, enable_thinking: bool = True, thinking_budget: int = 4096) -> dict:
    doc = copy.deepcopy(frozen_contracts()[f"agents/{PLANNER_ID}.json"])
    doc["display_name"] = "内部解题蓝图规划"
    doc["description"] = "首轮复杂新题生成服务端私有路线、里程碑与预验算锚点；绝不下发学生端。"
    doc["prompt"]["template"] = prompt
    doc["tools"] = []
    model_cfg: dict = {
        "component_id": PLANNER_ID,
        "name": model,
        "temperature": 0,
        "max_output_tokens": 4096,
        "timeout_ms": 45000,
        "enable_thinking": enable_thinking,
    }
    if enable_thinking:
        model_cfg["thinking_budget"] = thinking_budget
    doc["models"] = [model_cfg]
    return doc
