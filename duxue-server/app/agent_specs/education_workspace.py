"""Wire contracts for model proposals. Verification status is assigned by the application."""

from copy import deepcopy
from typing import Literal
from pydantic import BaseModel, ConfigDict, Field
from app.agent_specs.configuration import code_contract


class Proposal(BaseModel):
    model_config = ConfigDict(extra="forbid")


class SkillSelection(Proposal):
    skill: Literal[
        "general",
        "edu.homework_tutoring",
        "edu.worksheet_grading",
        "edu.lesson_pack",
        "edu.interactive_courseware",
    ]


class SearchStep(Proposal):
    query: str = Field(min_length=1, max_length=200)
    learning_purpose: str = Field(min_length=1, max_length=180)


class SkillChoiceLegacy(SkillSelection):
    search: SearchStep | None = None
    answer: str | None = Field(default=None, min_length=1, max_length=4000)


class SkillChoice(SkillChoiceLegacy):
    action: Literal["run_skill", "call_read_tool", "finish"] | None = None
    sub_goal: str | None = Field(default=None, min_length=1, max_length=1000)
    finish_reason: Literal[
        "all_done", "precondition_unmet", "needs_clarification"
    ] | None = None


class Question(Proposal):
    label: str = Field(max_length=80)
    stem: str = Field(max_length=4000)
    student_answer: str = Field(max_length=2000)
    legible: bool


class Page(Proposal):
    complete: bool
    questions: list[Question] = Field(max_length=60)


class Lesson(Proposal):
    title: str = Field(min_length=1, max_length=80)
    teaching_notes: str = Field(min_length=1, max_length=6000)
    variants: list[str] = Field(min_length=1, max_length=16)


class Comparison(Proposal):
    verdict: Literal["correct", "incorrect", "uncertain"]
    explanation: str = Field(min_length=1, max_length=700)


UNITS = {
    "edu.skill-planner": SkillChoice,
    "edu.worksheet-page": Page,
    "edu.lesson-author": Lesson,
    "edu.answer-compare": Comparison,
}
FILES = {f"agents/{name}.json" for name in UNITS}


def contracts(files=None):
    base = code_contract()["files"]["agents/companion.intent.json"]
    result = {}
    for name, model in UNITS.items():
        doc = deepcopy(base)
        doc.update(
            id=name,
            operation=name,
            agent_label="tutoring",
            input_contract=name + ".input.v1",
            output_contract=name + ".output.v1",
            context_builder_id=name.replace("-", "_") + ".context",
            prompt={"id": name + ".prompt"},
            models=[{"component_id": name}],
            output_schema=model.model_json_schema(),
            accepts_images=name
            in {"edu.worksheet-page", "edu.skill-planner", "edu.lesson-author"},
        )
        result[f"agents/{name}.json"] = doc
    lesson = "agents/edu.lesson-author.json"
    if files and files[lesson].get("accepts_images") is False:
        # Preserve compilation of the first immutable, text-only snapshot.
        result[lesson]["accepts_images"] = False
    planner = "agents/edu.skill-planner.json"
    if files:
        planner_props = files[planner]["output_schema"]["properties"]
        if "search" not in planner_props:
            prior = SkillSelection.model_json_schema()
            prior["title"] = "SkillChoice"
            result[planner]["output_schema"] = prior
        elif "action" not in planner_props:
            prior = SkillChoiceLegacy.model_json_schema()
            prior["title"] = "SkillChoice"
            result[planner]["output_schema"] = prior
    return result


def workflow(unit):
    name = unit.replace(".", "-")
    return {
        "id": name,
        "kind": "workflow",
        "handler": name,
        "entry": name + ".run",
        "nodes": [{"id": name + ".run", "kind": "agent", "ref": unit}],
        "edges": [
            {"from": "START", "to": name + ".run"},
            {"from": name + ".run", "to": "END"},
        ],
    }


RETIRED_WORKFLOWS = {"planning", "reflection", "review-aspects", "task-intake"}
RETIRED_FILES = {f"workflows/{name}.json" for name in RETIRED_WORKFLOWS} | {
    "agents/planning.intake.json",
    "agents/planning.session-turn.json",
    "agents/reflection.session-turn.json",
    "gates/planning.confirmation-gate.json",
    "agents/task.intake.json",
    "agents/evaluation.review-aspects.json",
}


def retired_configuration(files):
    return FILES <= set(files) and not RETIRED_FILES.intersection(files)
