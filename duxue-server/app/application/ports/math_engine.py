"""Tutoring-owned wire DTOs; all formula strings are untrusted data."""

from __future__ import annotations

from typing import Literal, Protocol

from pydantic import BaseModel, ConfigDict, Field, model_validator


class MathSymbol(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    name: str = Field(pattern=r"^[a-zA-Z][a-zA-Z0-9]{0,15}$")
    domain: Literal["real", "complex", "integer"]


class MathInput(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    op: Literal[
        "evaluate", "equivalent", "solve", "differentiate", "integrate", "limit"
    ]
    args: dict
    symbols: list[MathSymbol] = Field(default_factory=list, max_length=8)
    assumptions: list[str] = Field(default_factory=list, max_length=16)
    # References identify the authorized input; they are not a model-created identity.
    image_ref: str | None = Field(default=None, max_length=64)
    step_ref: str | None = Field(default=None, max_length=100)


class MathResult(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    engine_version: str | None = Field(default=None, max_length=64)
    status: Literal["ok", "unknown", "error"]
    result: str | None = Field(default=None, max_length=4096)
    verdict: Literal["equal", "not_equal", "unknown"] | None = None
    conditions: list[str] = Field(default_factory=list, max_length=100)
    checked_scope: Literal["value", "equivalence", "solution_set"] = "value"
    error_code: (
        Literal[
            "invalid_input", "unsupported", "timeout", "resource_limit", "unavailable"
        ]
        | None
    ) = None

    @model_validator(mode="after")
    def consistent(self):
        if self.verdict is not None and self.checked_scope != "equivalence":
            raise ValueError("verdict_requires_equivalence_scope")
        if self.verdict == "unknown" and self.status == "ok":
            raise ValueError("unknown_verdict_not_success")
        if self.status != "ok" and self.verdict in {"equal", "not_equal"}:
            raise ValueError("failed_calculation_cannot_decide")
        if self.status == "ok" and (self.error_code or self.result is None):
            raise ValueError("successful_calculation_requires_result")
        return self


class MathEnginePort(Protocol):
    def execute(self, request: MathInput) -> MathResult: ...
