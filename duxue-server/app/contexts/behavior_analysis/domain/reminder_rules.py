"""Published rule descriptions and deterministic evidence continuity."""

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from .model_contracts import ActivityCell


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, str_strip_whitespace=True)


class Rule(StrictModel):
    id: str = Field(min_length=1, max_length=80)
    assessment_rule: str = Field(min_length=1, max_length=500)
    min_continuous_seconds: int = Field(ge=15, le=3600)


class Groups(StrictModel):
    offer_help: list[Rule] = Field(max_length=8)
    invite_return: list[Rule] = Field(max_length=8)


class ReminderPolicy(StrictModel):
    schema_version: Literal[1]
    groups: Groups

    @model_validator(mode="after")
    def unique_ids(self):
        ids = [r.id for r in self.groups.offer_help + self.groups.invite_return]
        if len(ids) != len(set(ids)):
            raise ValueError("duplicate reminder rule id")
        return self


class RuleMatch(StrictModel):
    rule_id: str
    verdict: Literal["matched", "not_matched", "uncertain"]
    evidence_frame_ids: list[str] = Field(min_length=1, max_length=8)


class RuleCell(ActivityCell):
    rule_matches: list[RuleMatch] = Field(max_length=16)


class RuleActivityResult(StrictModel):
    cells: list[RuleCell] = Field(max_length=4)


def checked_matches(manifest, rows, cells):
    rules = manifest["rule_groups"]
    expected = {rule["id"] for group in rules.values() for rule in group}
    by_slot = {cell.start: cell for cell in cells}
    quiet = {datetime.fromisoformat(t) for t in manifest.get("quiet_slots", [])}
    matched = {}
    for row in RuleActivityResult.model_validate({"cells": rows}).cells:
        start = datetime.fromisoformat(row.start)
        ids = [match.rule_id for match in row.rule_matches]
        if len(ids) != len(set(ids)) or set(ids) != (
            set() if start in quiet else expected
        ):
            raise ValueError("rule result does not cover manifest")
        for match in row.rule_matches:
            if not set(match.evidence_frame_ids) <= set(by_slot[start].evidence):
                raise ValueError("rule result references another slot")
        matched[start] = [m.model_dump() for m in row.rule_matches]
    return matched


def trailing_rules(slots, groups, digest):
    """Only the latest uninterrupted run for each rule may prompt."""
    result = []
    for kind in ("offer_help", "invite_return"):
        for rule in groups[kind]:
            start = end = assignment = None
            refs = []
            for cell, source, policy, matches in reversed(slots):
                if policy != digest or (
                    start and (cell.end != start or source != assignment)
                ):
                    break
                match = next((m for m in matches if m["rule_id"] == rule["id"]), None)
                if not match or match["verdict"] != "matched":
                    break
                start, end, assignment = cell.start, end or cell.end, source
                refs.extend(match["evidence_frame_ids"])
            if (
                start
                and (end - start).total_seconds() >= rule["min_continuous_seconds"]
            ):
                result.append(
                    {
                        "start": start.isoformat(),
                        "end": end.isoformat(),
                        "seconds": (end - start).total_seconds(),
                        "evidence": sorted(set(refs)),
                        "rule_id": rule["id"],
                        "min_seconds": rule["min_continuous_seconds"],
                        "kind": kind,
                        "policy_digest": digest,
                        "assessment_rule": rule["assessment_rule"],
                    }
                )
    return result
