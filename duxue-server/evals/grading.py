"""Versioned scoring contract. No application imports or semantic string matching."""

from __future__ import annotations

import hashlib
import json
from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

GRADER_VERSION = "grading.v2.2"
Status = Literal["pass", "fail", "error", "not_run"]
Text = Annotated[str, Field(min_length=1)]
OUTCOMES = {
    "answer",
    "hint_like",
    "chat",
    "clarify",
    "redirect",
    "pronounce",
    "blocked",
    "fallback",
}
INTENTS = {"planning", "tutoring", "reflection", "unclear"}
FIELDS = {
    "outcome": ("str", OUTCOMES),
    "intent": ("str", INTENTS),
    "answer_protected": ("bool", None),
    "selected_images": ("list", None),
    "visual_present": ("bool", None),
    "visual_kind": (
        "nullable_str",
        {"steps", "compare", "segment", "number_line", "svg"},
    ),
    "review_conclusion": (
        "nullable_str",
        {"all_correct", "some_incorrect", "uncertain", "not_checking"},
    ),
    "lesson_sources": ("list", None),
    "lesson_count": ("int", None),
    "leaks": ("bool", None),
    "reason": ("nullable_str", None),
    "exit_gate.leaks": ("bool", None),
    "exit_gate.reason": ("nullable_str", None),
    "exit_gate.answer_protected": ("bool", None),
    "image_target_unambiguous": ("bool", None),
    "history_isolated": ("bool", None),
    "latency_ms": ("number", None),
}


class Strict(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)


def valid_value(field, value):
    kind, choices = FIELDS[field]
    if kind == "nullable_str" and value is None:
        return True
    valid = {
        "str": lambda: type(value) is str,
        "nullable_str": lambda: type(value) is str,
        "bool": lambda: type(value) is bool,
        "int": lambda: type(value) is int and value >= 0,
        "number": lambda: type(value) in (int, float) and 0 <= value < float("inf"),
        "list": lambda: (
            type(value) is list and all(type(x) is str and x for x in value)
        ),
    }[kind]()
    return valid and (choices is None or value in choices)


class FieldCheck(Strict):
    id: Text
    field: Text
    op: Literal["eq", "in", "not_in", "set_eq", "lte", "gte"]
    expected: Any

    @model_validator(mode="after")
    def typed(self):
        if self.field not in FIELDS:
            raise ValueError("unknown observation field")
        kind = FIELDS[self.field][0]
        if self.op in ("in", "not_in"):
            if (
                kind == "list"
                or not isinstance(self.expected, list)
                or not self.expected
                or not all(valid_value(self.field, v) for v in self.expected)
            ):
                raise ValueError(
                    "membership requires a nonempty list of typed scalar values"
                )
        else:
            if not valid_value(self.field, self.expected):
                raise ValueError("expected value has the wrong type or enum")
            if self.op == "set_eq" and kind != "list":
                raise ValueError("set_eq requires a list field")
            if self.op in ("lte", "gte") and kind not in ("int", "number"):
                raise ValueError("numeric comparison requires a numeric field")
        return self


class ToolCalled(Strict):
    id: Text
    assertion: Literal["tool_called"] = Field(alias="assert")
    with_name: Text


class ParameterMatch(Strict):
    id: Text
    assertion: Literal["parameter_match"] = Field(alias="assert")
    tool: Text
    param: Text
    equals: Any


class NoForbiddenTools(Strict):
    id: Text
    assertion: Literal["no_forbidden_tools"] = Field(alias="assert")
    forbidden: list[Text] = Field(min_length=1)


class SemanticCheck(Strict):
    id: Text
    type: Literal["score", "binary"]
    rubric: Text | None = None
    rubric_ref: Text | None = None
    min_score: int | None = Field(default=None, ge=1, le=5, strict=True)
    expected: Literal["pass"] | None = None

    @model_validator(mode="after")
    def rubric_and_threshold(self):
        if bool(self.rubric) == bool(self.rubric_ref):
            raise ValueError("provide exactly one rubric or rubric_ref")
        if self.rubric_ref:
            from evals.rubrics import resolve

            resolve(self.rubric_ref)
        if self.type == "score" and (
            self.min_score is None or self.expected is not None
        ):
            raise ValueError("score requires min_score only")
        if self.type == "binary" and (
            self.expected != "pass" or self.min_score is not None
        ):
            raise ValueError("binary requires expected=pass only")
        return self

    def instructions(self):
        if self.rubric is not None:
            return self.rubric
        from evals.rubrics import resolve

        return resolve(self.rubric_ref)


class Grading(Strict):
    native_evaluators: list[Text] = Field(default_factory=list)
    deterministic: list[FieldCheck | ToolCalled | ParameterMatch | NoForbiddenTools] = (
        Field(min_length=1)
    )
    model_graded: list[SemanticCheck] = Field(default_factory=list)
    reference_response: Text | None = None
    # Human annotation rationale for fixed-label comparisons; not another grader.
    rationale: list[Text] = Field(default_factory=list)
    aggregation: Literal["all_required"] = "all_required"

    @model_validator(mode="after")
    def unique(self):
        ids = [c.id for c in [*self.deterministic, *self.model_graded]]
        if len(ids) != len(set(ids)):
            raise ValueError("duplicate grading id")
        return self

    def for_component(self, component):
        allowed = (
            {"intent", "latency_ms"}
            if component == "companion.intent"
            else {"leaks", "reason", "answer_protected", "latency_ms"}
            if component == "tutoring.leak-judge"
            else set(FIELDS) - {"intent", "leaks", "reason"}
        )
        if any(
            isinstance(c, FieldCheck) and c.field not in allowed
            for c in self.deterministic
        ):
            raise ValueError(f"grading field does not belong to {component}")
        if component != "tutoring.turn" and self.model_graded:
            raise ValueError(
                "label-only components use deterministic comparisons, not semantic grading"
            )
        if component != "tutoring.turn" and any(
            not isinstance(c, FieldCheck) for c in self.deterministic
        ):
            raise ValueError("tool assertions require tutoring.turn capture")
        if component == "tutoring.turn":
            if not self.model_graded and not self.native_evaluators:
                raise ValueError("teaching responses require model_graded")
            boundaries = [
                c
                for c in self.deterministic
                if isinstance(c, FieldCheck) and c.field == "outcome"
            ]
            if not any(
                c.op in ("eq", "in") or (c.op == "not_in" and "fallback" in c.expected)
                for c in boundaries
            ):
                raise ValueError(
                    "teaching responses require an explicit outcome/fallback boundary"
                )
        return self

    def expectation(self, field, default=None):
        for rule in self.deterministic:
            if (
                isinstance(rule, FieldCheck)
                and rule.field == field
                and rule.op in ("eq", "set_eq")
            ):
                return rule.expected
        return default

    def is_specific(self):
        return bool(
            self.model_graded
            or len(self.deterministic) > 1
            or any(
                not (
                    isinstance(r, FieldCheck)
                    and r.field == "outcome"
                    and r.op == "not_in"
                    and r.expected == ["fallback"]
                )
                for r in self.deterministic
            )
        )


class Grade(Strict):
    id: str
    kind: Literal["deterministic", "model_graded"]
    status: Status
    actual: Any = None
    expected: Any = None
    score: int | None = None
    verdict: Literal["pass", "fail"] | None = None
    explanation: str = ""
    evidence: list[str] = Field(default_factory=list)


class GradingResult(Strict):
    grades: list[Grade]
    status: Status
    calibration_status: Literal["uncalibrated", "not_applicable"]
    # No calibration artifact exists yet; never infer formal quality from a score.
    quality_passed: None = None
    meta: dict = Field(default_factory=dict)


def aggregate(statuses):
    values = list(statuses)
    for status in ("fail", "error", "not_run"):
        if status in values:
            return status
    return "pass" if values else "not_run"


def result(grading, grades, meta=None):
    rubric_payload = [(r.id, r.instructions()) for r in grading.model_graded]
    return GradingResult(
        grades=grades,
        status=aggregate(g.status for g in grades),
        calibration_status="uncalibrated" if grading.model_graded else "not_applicable",
        meta={
            "grader_version": GRADER_VERSION,
            "rubric_digest": hashlib.sha256(
                json.dumps(rubric_payload, ensure_ascii=False).encode()
            ).hexdigest(),
            **(meta or {}),
        },
    )


def unavailable(grading, reason, *, status="error", meta=None):
    return result(
        grading,
        [
            Grade(id=r.id, kind=kind, status=status, explanation=reason)
            for kind, rules in [
                ("deterministic", grading.deterministic),
                ("model_graded", grading.model_graded),
            ]
            for r in rules
        ],
        meta,
    )


def _exact(a, b):
    if type(a) is not type(b):
        return False
    if isinstance(a, dict):
        return a.keys() == b.keys() and all(_exact(a[k], b[k]) for k in a)
    if isinstance(a, list):
        return len(a) == len(b) and all(_exact(x, y) for x, y in zip(a, b))
    return a == b


def deterministic(rule, observed):
    if isinstance(rule, FieldCheck):
        if rule.field not in observed or not valid_value(
            rule.field, observed[rule.field]
        ):
            raise ValueError("missing or invalid observation: " + rule.field)
        actual, expected = observed[rule.field], rule.expected
        passed = {
            "eq": lambda: _exact(actual, expected),
            "in": lambda: any(_exact(actual, x) for x in expected),
            "not_in": lambda: all(not _exact(actual, x) for x in expected),
            "set_eq": lambda: set(actual) == set(expected),
            "lte": lambda: actual <= expected,
            "gte": lambda: actual >= expected,
        }[rule.op]()
    else:
        actual = observed.get("tool_calls")
        if not isinstance(actual, list) or any(
            not isinstance(c, dict)
            or not isinstance(c.get("name"), str)
            or not isinstance(c.get("args"), dict)
            for c in actual
        ):
            raise ValueError("missing or invalid tool capture")
        expected = rule.model_dump(by_alias=True, exclude={"id"})
        if isinstance(rule, ToolCalled):
            passed = any(c["name"] == rule.with_name for c in actual)
        elif isinstance(rule, ParameterMatch):
            passed = any(
                c["name"] == rule.tool
                and rule.param in c["args"]
                and _exact(c["args"][rule.param], rule.equals)
                for c in actual
            )
        else:
            passed = all(c["name"] not in rule.forbidden for c in actual)
    return Grade(
        id=rule.id,
        kind="deterministic",
        status="pass" if passed else "fail",
        actual=actual,
        expected=expected,
    )


def semantic(rule, judge):
    if judge is None:
        raise ValueError("semantic grader unavailable")
    payload = judge(rule)
    value_key = "score" if rule.type == "score" else "verdict"
    if not isinstance(payload, dict) or set(payload) != {
        value_key,
        "explanation",
        "evidence",
    }:
        raise ValueError("invalid semantic response fields")
    if (
        not isinstance(payload["explanation"], str)
        or not payload["explanation"].strip()
        or not isinstance(payload["evidence"], list)
        or not payload["evidence"]
        or not all(isinstance(e, str) and e.strip() for e in payload["evidence"])
    ):
        raise ValueError("semantic response requires explanation and evidence")
    value = payload[value_key]
    if rule.type == "score":
        if type(value) is not int or not 1 <= value <= 5:
            raise ValueError("invalid semantic score")
        passed = value >= rule.min_score
    else:
        if value not in ("pass", "fail"):
            raise ValueError("invalid semantic verdict")
        passed = value == rule.expected
    return Grade(
        id=rule.id, kind="model_graded", status="pass" if passed else "fail", **payload
    )


def evaluate(grading, observed, *, judge=None, meta=None, only_fields=None):
    grades = []
    for kind, rules in [
        ("deterministic", grading.deterministic),
        ("model_graded", grading.model_graded),
    ]:
        for rule in rules:
            if only_fields is not None and (
                not isinstance(rule, FieldCheck) or rule.field not in only_fields
            ):
                grades.append(
                    Grade(
                        id=rule.id,
                        kind=kind,
                        status="not_run",
                        explanation="excluded_by_scope",
                    )
                )
                continue
            try:
                grades.append(
                    deterministic(rule, observed)
                    if kind == "deterministic"
                    else semantic(rule, judge)
                )
            except Exception as error:
                grades.append(
                    Grade(
                        id=rule.id,
                        kind=kind,
                        status="error",
                        explanation=f"{type(error).__name__}: {error}",
                    )
                )
    return result(grading, grades, meta)
