"""Optional Admin tool contract. Existing published snapshots stay compatible."""
from copy import deepcopy

TOOL = "tutoring.web_search"
FILE = f"tools/{TOOL}.json"
CONTRACT = {
    "id": TOOL, "kind": "tool", "access": "read", "handler_id": TOOL,
    "input_schema": {
        "type": "object", "additionalProperties": False,
        "required": ["query", "mode", "learning_purpose"],
        "properties": {
            "query": {"type": "string", "minLength": 1, "maxLength": 200},
            "learning_purpose": {"type": "string", "minLength": 1, "maxLength": 180},
            "mode": {"enum": ["web", "image"]},
            "count": {"type": "integer", "minimum": 1, "maximum": 10},
        },
    },
    "output_schema": {"type": "object", "required": ["status"],
                      "properties": {"status": {"type": "string"}}, "additionalProperties": True},
}

PHOTO_CHECKS = ("learning_related", "age_appropriate", "caption_supported")
PHOTO_REVIEW = {
    "type": "object",
    "properties": {
        "observation": {"type": "string", "minLength": 1, "maxLength": 160},
        **{name: {"type": "boolean"} for name in PHOTO_CHECKS},
    },
    "required": ["observation", *PHOTO_CHECKS],
    "additionalProperties": False,
}


def upgraded_contracts(base):
    gate_file = "gates/tutoring.visual-leak-judge.json"
    visual_gate = deepcopy(base[gate_file])
    visual_gate["accepts_images"] = True
    visual_gate["provider_output_schema"]["properties"]["photo_review"] = PHOTO_REVIEW
    return {FILE: CONTRACT, gate_file: visual_gate}
