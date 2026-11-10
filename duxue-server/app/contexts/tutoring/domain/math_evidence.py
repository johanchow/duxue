"""Immutable mathematical evidence. Computation does not grant disclosure permission."""

from dataclasses import dataclass


@dataclass(frozen=True)
class MathEvidence:
    request_id: str
    input_digest: str
    status: str
    verdict: str | None
    checked_scope: str
    conditions: tuple[str, ...]
    step_ref: str | None = None

    result: str | None = None

    def supports(
        self, assertion: str, step_ref: str | None, value: str | None = None
    ) -> bool:
        if self.step_ref != step_ref:
            return False
        if assertion == "unknown":
            return self.status != "ok" or self.verdict == "unknown"
        if assertion == "result":
            return (
                self.status == "ok"
                and self.checked_scope in {"value", "solution_set"}
                and value is not None
                and value == self.result
            )
        return (
            self.status == "ok"
            and assertion in {"equal", "not_equal"}
            and self.verdict == assertion
            and self.step_ref == step_ref
            and not self.conditions
        )
