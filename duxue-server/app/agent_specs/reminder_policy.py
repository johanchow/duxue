"""Optional upgrade to the Admin release; older snapshots keep their contracts."""

from copy import deepcopy

from app.agent_specs.definitions import load_definitions
from app.contexts.behavior_analysis.domain.reminder_rules import RuleActivityResult

FILE = "policies/observation-support.json"
VISION = "agents/behavior.visible-activity.json"
INTAKE = "agents/planning.intake.json"


def upgraded_contracts(base):
    changed = {name: deepcopy(base[name]) for name in (VISION, INTAKE)}
    changed[VISION]["output_schema"] = RuleActivityResult.model_json_schema()
    actions = changed[INTAKE]["output_schema"]["$defs"]["StudyActionProposal"][
        "properties"
    ]["action"]["enum"]
    actions.extend(["quiet_start", "quiet_extend", "quiet_end"])
    return changed


def current_policy():
    return getattr(load_definitions(), "observation_policy", None)


def policy_source():
    catalog = load_definitions()
    return {"bundle_digest": catalog.artifact_digest, **(getattr(catalog, "activation", None) or {})}


def policy_identity(policy):
    from app.agent_specs.admin_bundle import digest
    return digest({"policy": policy, "activation": policy_source()})


def activation_time():
    from datetime import datetime

    value = (getattr(load_definitions(), "activation", {}) or {}).get("activated_at")
    return datetime.fromisoformat(value) if value else None
