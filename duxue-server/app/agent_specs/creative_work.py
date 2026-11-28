"""Code-owned wire contracts for illustrated story pages and the Ward authorship gate."""

from copy import deepcopy

from pydantic import BaseModel, ConfigDict, Field

from app.agent_specs.configuration import code_contract
from app.application.workflows.tutor_visual import SvgVisual

AUTHOR = "ward.story-pages"
GATE = "ward.anti_ghostwriting"
WORKFLOW = "ward-creative"
WORKFLOW_FILE = f"workflows/{WORKFLOW}.json"
FILES = {WORKFLOW_FILE, f"agents/{AUTHOR}.json", f"gates/{GATE}.json"}


class StoryPage(BaseModel):
    model_config = ConfigDict(extra="forbid")
    text: str = Field(min_length=1, max_length=600)
    illustration: SvgVisual


class Story(BaseModel):
    model_config = ConfigDict(extra="forbid")
    title: str = Field(min_length=1, max_length=80)
    pages: list[StoryPage] = Field(min_length=1, max_length=6)


def contracts():
    base = code_contract()["files"]
    result = {}
    for name, src, folder in (
        (AUTHOR, "companion.intent", "agents"),
        (GATE, "companion.scene-switch", "gates"),
    ):
        doc = deepcopy(base[f"{folder}/{src}.json"])
        doc.update(
            id=name,
            agent_label="tutoring",
            operation=name,
            input_contract=f"{name}.input.v1",
            output_contract=f"{name}.output.v1",
            context_builder_id=name.replace("-", "_") + ".context",
            prompt={"id": name + ".prompt"},
            models=[{"component_id": name}],
        )
        if name == GATE:
            doc.update(
                safety_class="protected",
                risk_tier="protected",
                provider_output_schema={
                    "type": "object",
                    "properties": {"allow_creation": {"type": "boolean"}},
                    "required": ["allow_creation"],
                    "additionalProperties": False,
                },
            )
        else:
            doc["output_schema"] = Story.model_json_schema()
        result[f"{folder}/{name}.json"] = doc
    return result


def workflow():
    return {
        "id": WORKFLOW,
        "kind": "workflow",
        "handler": WORKFLOW,
        "entry": "ward-creative.check",
        "nodes": [
            {"id": "ward-creative.check", "kind": "gate", "ref": GATE},
            {"id": "ward-creative.draw", "kind": "agent", "ref": AUTHOR},
        ],
        "edges": [
            {"from": "START", "to": "ward-creative.check"},
            {
                "from": "ward-creative.check",
                "to": "ward-creative.draw",
                "condition_id": "permitted",
            },
            {"from": "ward-creative.check", "to": "END", "condition_id": "denied"},
            {"from": "ward-creative.draw", "to": "END"},
        ],
    }
