"""Normalize provider protocols into the common Gate contract."""
from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict


class GateVerdict(BaseModel):
    model_config = ConfigDict(extra="forbid")
    verdict: Literal["allow", "deny", "unknown"]
    reason_code: str


def normalize_judge(unit_id: str, payload: dict | None) -> GateVerdict:
    if payload is None:
        return GateVerdict(verdict="unknown", reason_code="judge_unavailable")
    if unit_id == "companion.scene-switch":
        if set(payload) != {"allow_switch"}:
            return GateVerdict(verdict="unknown", reason_code="invalid_judge_output")
        value = payload.get("allow_switch")
        return GateVerdict(verdict="allow" if value is True else "deny" if value is False else "unknown",
                           reason_code="confirmed" if value is True else "not_confirmed")
    if unit_id == "tutoring.leak-judge":
        from jsonschema import Draft202012Validator
        from app.agent_specs.definitions import load_definitions
        schema = load_definitions().units[unit_id].provider_output_schema
        if not Draft202012Validator(schema).is_valid(payload):
            return GateVerdict(verdict="unknown", reason_code="invalid_judge_output")
        # Semantic facts come from the independent judge. This is a protocol
        # mapping, never a scan of student/tutor text or a new permission grant.
        if payload["choice_verdict"]:
            reason = "choice_verdict"
        elif payload["new_final_answer"]:
            reason = "final_answer"
        elif payload["complete_solution"]:
            reason = "complete_solution"
        elif payload["affirms_student_answer"] and payload["student_answer_correct"] is not True:
            reason = "incorrect_confirmation"
        elif payload["premature_conclusion"]:
            reason = "premature_conclusion"
        else:
            reason = "none"
        return GateVerdict(verdict="allow" if reason == "none" else "deny", reason_code=reason)
    if unit_id == "tutoring.visual-leak-judge":
        value = payload.get("leaks")
        reason = payload.get("reason")
        return GateVerdict(verdict="allow" if value is False else "deny" if value is True else "unknown",
                           reason_code=reason if isinstance(reason, str) else "leak_detected" if value else "ok")
    raise ValueError(f"unregistered Judge adapter {unit_id}")
