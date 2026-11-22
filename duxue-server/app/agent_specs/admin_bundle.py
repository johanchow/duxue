"""Complete Admin artifacts with code-owned contracts and editable component values."""

from __future__ import annotations

import copy
import hashlib
import json
import tempfile
from dataclasses import dataclass
from pathlib import Path

from app.agent_specs import blueprint_steps, reminder_policy, web_search
from app.contexts.behavior_analysis.domain.reminder_rules import ReminderPolicy
from app.agent_specs.configuration import code_contract
from app.agent_specs.definitions import DefinitionCatalog
from app.agent_specs.gaokao_contracts import FILES as GAOKAO_FILES
from app.agent_specs.gaokao_contracts import PLANNER_ID as GAOKAO_PLANNER_ID
from app.agent_specs.gaokao_contracts import TOOL_AUTHORITY_ADDITIONS as GAOKAO_TOOLS
from app.agent_specs.gaokao_contracts import WORKFLOWS as GAOKAO_WORKFLOWS
from app.agent_specs.gaokao_contracts import frozen_contracts as gaokao_contracts
from app.agent_specs.guardian_contracts import FILES as GUARDIAN_MENTOR_FILES
from app.agent_specs.guardian_contracts import MENTOR_EXPLAIN_ID, MENTOR_REPAIR_ID, MENTOR_REVIEW_ID, staged_contracts
from app.agent_specs.guardian_contracts import WORKFLOWS as GUARDIAN_MENTOR_WORKFLOWS
from app.agent_specs.guardian_contracts import (
    bundle_contracts as guardian_mentor_contracts,
)
from app.agent_specs.observation_contracts import FILES as OBSERVATION_FILES
from app.agent_specs.observation_contracts import WORKFLOWS as OBSERVATION_WORKFLOWS
from app.agent_specs.observation_contracts import contracts as observation_contracts
from app.agent_specs.registrations import WORKFLOW_BINDINGS

# Every JSON is carried by the published artifact. Code owns the file whitelist
# and protected contract; values are not filled from local defaults at load time.
WORKFLOW_FILES = {f"workflows/{name}.json" for name in WORKFLOW_BINDINGS}
BUNDLE_FILES = tuple(sorted(set(code_contract()["files"]) | WORKFLOW_FILES))


def digest(value) -> str:
    return hashlib.sha256(
        json.dumps(
            value, ensure_ascii=False, sort_keys=True, separators=(",", ":")
        ).encode()
    ).hexdigest()


def _artifact_document(raw):
    doc = copy.deepcopy(raw)
    if doc.get("kind") in {"agent", "gate", "tool", "workflow"}:
        doc.pop("version", None)
    for model in doc.get("models", []):
        model.pop("version", None)
    if "prompt" in doc:
        doc["prompt"]["id"] = doc["id"] + ".prompt"
        for name, fragment in doc["prompt"].get("fragments", {}).items():
            fragment["id"] = doc["id"] + ".fragment." + name
    return doc


def _frozen(doc):
    result = copy.deepcopy(doc)
    from app.agent_specs.visual_delivery import strip_extension
    strip_extension(result)
    if doc.get("kind") in {"agent", "gate", "tool"}:
        result.pop("display_name", None)
        result.pop("description", None)
    if result.get("implementation") in {"llm", "judge"}:
        for model in result["models"]:
            for key in (
                "name",
                "temperature",
                "max_output_tokens",
                "timeout_ms",
                "enable_thinking",
                "thinking_budget",
                "guardian_t1_reasoning_effort",
                "guardian_crop_handoff",
                "guardian_distance_evidence",
            ):
                model.pop(key, None)
        result["prompt"].pop("template")
        for fragment in result["prompt"].get("fragments", {}).values():
            fragment.pop("template")
        result.pop("tools")
    elif result.get("handler_id") == "tool.static_result":
        result.pop("static_result")
    return result


def contract_compatibility(files: dict) -> str:
    # The envelope binds code contracts and the topology supplied by Admin.
    # Never reconstruct topology from a repository baseline. Keeping the same
    # fingerprint algorithm preserves already-published immutable artifacts.
    has_obs = OBSERVATION_FILES <= set(files)
    has_gaokao = GAOKAO_FILES <= set(files)
    has_mentor = GUARDIAN_MENTOR_FILES <= set(files)
    reminder_contracts = reminder_policy.upgraded_contracts({**code_contract()["files"], **observation_contracts()}) if reminder_policy.FILE in files else {}
    return digest({
        "files": {**code_contract()["files"],
                  **(web_search.upgraded_contracts(code_contract()["files"]) if web_search.FILE in files else {}),
                  **(blueprint_steps.contracts(files) if f"agents/{blueprint_steps.EXTRACT}.json" in files else {}),
                  **(observation_contracts() if has_obs else {}), **reminder_contracts,
                  **(gaokao_contracts() if has_gaokao else {}),
                  **(guardian_mentor_contracts(files) if has_mentor else {}),
                  **(staged_contracts(include_repair=f"agents/{MENTOR_REPAIR_ID}.json" in files) if f"gates/{MENTOR_REVIEW_ID}.json" in files else {}),
                  **{name: ({k: v for k, v in doc.items() if k not in {"edges", "rollout_percent"}}
                            if name == "workflows/tutoring.json" and doc.get("execution") == "turn_graph" else doc)
                     for name, doc in files.items() if name in WORKFLOW_FILES or (has_obs and name in {f"workflows/{key}.json" for key in OBSERVATION_WORKFLOWS}) or (has_gaokao and name in {f"workflows/{key}.json" for key in GAOKAO_WORKFLOWS}) or (has_mentor and name in {f"workflows/{key}.json" for key in GUARDIAN_MENTOR_WORKFLOWS})}},
        "handlers": {key: {field: sorted(items) for field, items in value.items()}
                     for key, value in WORKFLOW_BINDINGS.items()},
        "protocol": 3,
    })


@dataclass(frozen=True)
class CompiledBundle:
    digest: str
    catalog: DefinitionCatalog
    bundle: dict


def compile_bundle(bundle: dict) -> CompiledBundle:
    contracts = copy.deepcopy(code_contract())
    file_names = set(bundle.get("files", {})) if isinstance(bundle, dict) else set()
    has_observation = OBSERVATION_FILES <= file_names
    has_gaokao = GAOKAO_FILES <= file_names
    has_mentor = GUARDIAN_MENTOR_FILES <= file_names
    split_files = {}
    if has_gaokao and f"agents/{blueprint_steps.EXTRACT}.json" in file_names:
        split_files = blueprint_steps.contracts(bundle["files"])
        contracts["files"].update(split_files)
        for uid in (blueprint_steps.EXTRACT, blueprint_steps.REREAD):
            contracts["tool_authority"][uid] = list(blueprint_steps.VISION_TOOLS)
        contracts["tool_authority"][blueprint_steps.BACKUP] = list(blueprint_steps.SOLVER_TOOLS)
    if web_search.FILE in file_names:
        contracts["files"].update(web_search.upgraded_contracts(contracts["files"]))
        contracts["tool_authority"]["tutoring.turn"].append(web_search.TOOL)
    if has_observation:
        contracts["files"].update(observation_contracts())
        contracts["tool_authority"].update({doc["id"]: [] for doc in observation_contracts().values()})
    if has_gaokao:
        contracts["files"].update(gaokao_contracts())
        contracts["tool_authority"][GAOKAO_PLANNER_ID] = (
            list(blueprint_steps.SOLVER_TOOLS) if split_files else []
        )
        contracts["tool_authority"]["tutoring.turn"] = list(
            dict.fromkeys([*contracts["tool_authority"]["tutoring.turn"], *GAOKAO_TOOLS])
        )
    if has_mentor:
        contracts["files"].update(guardian_mentor_contracts(bundle["files"]))
        contracts["tool_authority"][MENTOR_EXPLAIN_ID] = []
    mentor_stage = staged_contracts(include_repair=f"agents/{MENTOR_REPAIR_ID}.json" in file_names) if has_mentor and f"gates/{MENTOR_REVIEW_ID}.json" in file_names else {}
    if mentor_stage:
        contracts["files"].update(mentor_stage)
        contracts["tool_authority"].update({MENTOR_REVIEW_ID: [], MENTOR_REPAIR_ID: []})
    policy = None
    if reminder_policy.FILE in file_names:
        if not has_observation:
            raise ValueError("reminder policy requires observation workflow")
        policy = ReminderPolicy.model_validate(bundle["files"][reminder_policy.FILE]).model_dump()
        contracts["files"].update(reminder_policy.upgraded_contracts(contracts["files"]))
    expected_files = (
        set(BUNDLE_FILES) | set(split_files)
        | (OBSERVATION_FILES if has_observation else set())
        | (GAOKAO_FILES if has_gaokao else set())
        | (GUARDIAN_MENTOR_FILES if has_mentor else set())
        | ({reminder_policy.FILE} if policy else set())
        | ({web_search.FILE} if web_search.FILE in file_names else set())
        | set(mentor_stage)
    )
    if (
        not isinstance(bundle, dict)
        or set(bundle) != {"format_version", "compatibility", "files"}
        or type(bundle["format_version"]) is not int
        or bundle["format_version"] != 3
    ):
        raise ValueError("invalid bundle format")
    if not isinstance(bundle["files"], dict) or set(bundle["files"]) != expected_files:
        raise ValueError(
            "bundle files differ from the registered complete configuration manifest"
        )
    if bundle["compatibility"] != contract_compatibility(bundle["files"]):
        raise ValueError("code compatibility mismatch; validate the complete Admin snapshot")
    for name, doc in bundle["files"].items():
        if name == reminder_policy.FILE:
            continue
        if not isinstance(doc, dict):
            raise ValueError(f"{name}: malformed configuration")
        if "version" in doc or any(
            "version" in model for model in doc.get("models", [])
        ):
            raise ValueError("manual configuration versions are not supported")
        if name in WORKFLOW_FILES or (has_observation and name in {f"workflows/{key}.json" for key in OBSERVATION_WORKFLOWS}) or (has_gaokao and name in {f"workflows/{key}.json" for key in GAOKAO_WORKFLOWS}) or (has_mentor and name in {f"workflows/{key}.json" for key in GUARDIAN_MENTOR_WORKFLOWS}):
            continue  # Validated by AgentCatalog against code bindings below.
        original = contracts["files"][name]
        try:
            fixed = _frozen(doc)
        except (AttributeError, KeyError, TypeError) as error:
            raise ValueError(f"{name}: malformed configuration") from error
        if fixed != original:
            raise ValueError(f"{name}: read-only contract or workflow changed")
        if "models" in doc and not set(doc["tools"]).issubset(contracts["tool_authority"][doc["id"]]):
            raise ValueError(f"{name}: tool authority cannot expand")
    judge_doc = bundle["files"]["gates/tutoring.leak-judge.json"]
    judge_schema = judge_doc.get("provider_output_schema") or {}
    judge_props = set((judge_schema.get("properties") or {}).keys())
    required_text_fields = {
        "answer_protected",
        "student_answer_correct",
        "affirms_student_answer",
        "new_final_answer",
        "complete_solution",
        "choice_verdict",
        "premature_conclusion",
    }
    if not required_text_fields.issubset(judge_props):
        missing = sorted(required_text_fields - judge_props)
        raise ValueError(f"leak-judge schema missing required text review fields: {missing}")
    if "tutoring.math" in bundle["files"]["agents/tutoring.turn.json"]["tools"]:
        for name in ("agents/tutoring.turn.json", "gates/tutoring.leak-judge.json"):
            if "[math.v1]" not in bundle["files"][name]["prompt"]["template"]:
                raise ValueError("math tool requires matching tutor and judge protocol")
        if "math_consistent" not in judge_doc["prompt"]["template"] or "math_consistent" not in judge_props:
            raise ValueError("math tool requires leak-judge prompt and schema to declare math_consistent")
    bundle_id = digest(bundle)
    with tempfile.TemporaryDirectory(prefix="duxue-config-") as directory:
        root = Path(directory)
        for name, raw in bundle["files"].items():
            doc = copy.deepcopy(raw)
            if doc.get("kind") in {"agent", "gate", "tool", "workflow"}:
                doc["version"] = bundle_id
            if "prompt" in doc:
                doc["prompt"]["id"] += "+" + bundle_id[:12]
                for fragment in doc["prompt"].get("fragments", {}).values():
                    fragment["id"] += "+" + bundle_id[:12]
                for model in doc["models"]:
                    model["version"] = bundle_id
            target = root / name
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(json.dumps(doc, ensure_ascii=False))
        catalog = DefinitionCatalog(root)
        catalog.observation_policy = policy
        catalog.artifact_digest = bundle_id
        from app.agent_specs.catalog import AgentCatalog
        from app.agent_specs.definitions import use_definitions
        with use_definitions(catalog):
            catalog.workflow_catalog = AgentCatalog.from_directory(root)
    if mentor_stage and ({m.name for m in catalog.units[MENTOR_REVIEW_ID].models} &
                        {m.name for uid in (MENTOR_EXPLAIN_ID, MENTOR_REPAIR_ID) if uid in catalog.units for m in catalog.units[uid].models}):
        raise ValueError("Guardian Judge must be independent from generation models")
    main = catalog.units["tutoring.turn"].models[0].name
    if any(
        catalog.units[name].models[0].name == main
        for name in ("tutoring.leak-judge", "tutoring.visual-leak-judge")
    ):
        raise ValueError("independent Judges must not share the primary tutor model")
    return CompiledBundle(bundle_id, catalog, copy.deepcopy(bundle))
