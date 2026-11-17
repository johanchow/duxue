"""Optional, code-owned extension; old immutable releases retain their fingerprint."""

VISUAL_NEED_SCHEMA = {
    "type": "string", "enum": ["requested", "helpful", "not_needed", "uncertain"],
}
VISUAL_FIELDS = {
    "visual_need": VISUAL_NEED_SCHEMA,
    "visual_adequate": {"type": "boolean"},
    "visual_evidence": {"type": "string", "maxLength": 500},
}


def _complete(schema: dict) -> bool:
    properties = schema.get("properties", {})
    return all(properties.get(key) == value and key in schema.get("required", [])
               for key, value in VISUAL_FIELDS.items())


def enabled() -> bool:
    from app.agent_specs.definitions import load_definitions
    return _complete(load_definitions().units["tutoring.leak-judge"].provider_output_schema)


def strip_extension(document: dict) -> None:
    if document.get("id") != "tutoring.leak-judge":
        return
    schema = document.get("provider_output_schema", {})
    properties = schema.get("properties", {})
    if not set(VISUAL_FIELDS).intersection(properties):
        return
    if not _complete(schema):
        raise ValueError("invalid or incomplete visual delivery contract")
    for key in VISUAL_FIELDS:
        properties.pop(key)
        schema["required"].remove(key)
