"""Registered read-only handler for validated, configuration-owned tool results."""

from copy import deepcopy

from jsonschema import Draft202012Validator

from app.agent_specs.definitions import load_definitions


def static_tool_result(tool_id: str, args: dict | None = None) -> dict:
    definition = load_definitions().tools[tool_id]
    if definition.handler_id != "tool.static_result" or definition.access != "read":
        raise ValueError(f"{tool_id}: not a static read-only Tool")
    if not Draft202012Validator(definition.input_schema).is_valid(args if args is not None else {}):
        raise ValueError(f"{tool_id}: invalid static Tool input")
    return deepcopy(definition.static_result)
