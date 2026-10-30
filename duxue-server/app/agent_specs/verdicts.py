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
    if unit_id in {"tutoring.leak-judge", "tutoring.visual-leak-judge"}:
        value = payload.get("leaks")
        reason = payload.get("reason")
        return GateVerdict(verdict="allow" if value is False else "deny" if value is True else "unknown",
                           reason_code=reason if isinstance(reason, str) else "leak_detected" if value else "ok")
    raise ValueError(f"unregistered Judge adapter {unit_id}")
