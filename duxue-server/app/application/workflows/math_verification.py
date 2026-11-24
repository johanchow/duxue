"""Turn-local tool evidence ledger, never a persistence model or global cache."""

from __future__ import annotations

import hashlib
import json
import time
from typing import Literal
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.application.ports.math_engine import MathEnginePort, MathInput, MathResult
from app.contexts.tutoring.domain.math_evidence import MathEvidence


class MathClaim(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    request_id: str = Field(min_length=1, max_length=64)
    step_ref: str | None = Field(default=None, max_length=100)
    assertion: Literal["equal", "not_equal", "unknown", "result"]
    value: str | None = Field(default=None, max_length=4096)

    @model_validator(mode="after")
    def value_matches_assertion(self):
        if (self.assertion == "result") != (self.value is not None):
            raise ValueError("only_result_claim_requires_value")
        return self



class MathVerification:
    def __init__(
        self, engine: MathEnginePort | None, source: dict, image_refs: set[str]
    ):
        self.engine = engine
        self.source = source
        self.image_refs = image_refs
        self.records: dict[str, dict] = {}
        self.evidence: dict[str, MathEvidence] = {}
        self.worksheet_cache = {}
        self.worksheet_seconds = 0.0
        self.calls = 0
        self.compute_seconds = 0.0
        self.by_request: dict[str, dict] = {}

    def run(self, args: dict):
        request = MathInput.model_validate(args)
        if request.image_ref and request.image_ref not in self.image_refs:
            raise ValueError("unselected_math_image")
        body = request.model_dump()
        digest = hashlib.sha256(
            json.dumps(
                {"source": self.source, "request": body},
                sort_keys=True,
                ensure_ascii=False,
            ).encode()
        ).hexdigest()
        if digest in self.by_request:
            return self.by_request[digest]
        if self.calls >= 8 or self.compute_seconds >= 16:
            return {"status": "unknown", "error_code": "resource_limit"}
        self.calls += 1
        started = time.monotonic()
        try:
            result = (
                self.engine.execute(request)
                if self.engine is not None
                else MathResult(status="unknown", error_code="unavailable")
            )
        except Exception:  # noqa: BLE001 - port failure must not become a mathematical verdict
            result = MathResult(status="unknown", error_code="unavailable")
        finally:
            self.compute_seconds += time.monotonic() - started
        request_id = "math_" + uuid4().hex
        record = {
            "request_id": request_id,
            "input_digest": digest,
            "source": self.source,
            "request": body,
            **result.model_dump(exclude_none=True),
        }
        self.records[request_id] = record
        if result.error_code not in {"unavailable", "timeout", "resource_limit"}:
            self.by_request[digest] = record
        self.evidence[request_id] = MathEvidence(
            request_id,
            digest,
            result.status,
            result.verdict,
            result.checked_scope,
            tuple(result.conditions),
            request.step_ref,
            result.result,
        )
        return record

    def validate(self, claims: list[MathClaim]):
        if len(claims) > 16:
            raise ValueError("too_many_math_claims")
        for claim in claims:
            evidence = self.evidence.get(claim.request_id)
            if evidence is None or not evidence.supports(
                claim.assertion, claim.step_ref, claim.value
            ):
                raise ValueError("math_claim_not_supported")

    def context(self, claims: list[MathClaim]):
        return {
            "math_review_required": True,
            "source": self.source,
            "math_records": list(self.records.values()),
            "math_claims": [c.model_dump() for c in claims],
        }

    def verify_derivation_chain(
        self,
        *,
        steps: list[str],
        symbols: list[dict] | None = None,
        assumptions: list[str] | None = None,
        image_ref: str | None = None,
    ) -> dict:
        """Verify adjacent steps (L_i -> L_{i+1}) to pinpoint the FIRST broken transition."""
        if not isinstance(steps, list) or not 2 <= len(steps) <= 8:
            raise ValueError("derivation_chain_requires_2_to_8_steps")
        transitions = []
        first_error = None
        for idx in range(len(steps) - 1):
            step_ref = f"step_{idx + 1}_to_{idx + 2}"
            record = self.run(
                {
                    "op": "equivalent",
                    "args": {"left": steps[idx], "right": steps[idx + 1]},
                    "symbols": list(symbols or []),
                    "assumptions": list(assumptions or []),
                    "image_ref": image_ref,
                    "step_ref": step_ref,
                }
            )
            verdict = record.get("verdict") or "unknown"
            transitions.append(
                {
                    "from_step": idx + 1,
                    "to_step": idx + 2,
                    "request_id": record.get("request_id"),
                    "verdict": verdict,
                    "conditions": record.get("conditions", []),
                }
            )
            if first_error is None and verdict == "not_equal":
                first_error = {"from_step": idx + 1, "to_step": idx + 2}
        return {
            "status": "ok",
            "step_count": len(steps),
            "first_error_transition": first_error,
            "transitions": transitions,
        }

    def reconcile_image(self, candidate):
        """Arithmetic transcriptions use the same isolated engine and evidence ledger."""
        report = candidate.image_review
        if report is None or report.conclusion == "not_checking":
            return candidate
        from math_executor.arithmetic import WORKSHEET_BATCH_SIZE

        keys = {}
        for index, question in enumerate(report.questions):
            if question.image_ref not in self.image_refs:
                raise ValueError("unselected_math_image")
            if question.calculation is not None and question.verdict != "uncertain":
                keys[index] = (question.image_ref, question.location,
                               question.calculation.expression, question.calculation.submitted)
        pending = list(dict.fromkeys(k for k in keys.values() if k not in self.worksheet_cache))
        results = {}
        for start in range(0, len(pending), WORKSHEET_BATCH_SIZE):
            chunk = pending[start:start + WORKSHEET_BATCH_SIZE]
            remaining = 16 - self.worksheet_seconds
            if remaining <= 0:
                results.update(dict.fromkeys(pending[start:], "timeout"))
                break
            before = time.monotonic()
            try:
                outcomes = self.engine.check_arithmetic([key[2:] for key in chunk], remaining)
            except Exception:  # noqa: BLE001 - a failed executor cannot authorize a grade.
                outcomes = ["unavailable"] * len(chunk)
            finally:
                self.worksheet_seconds += time.monotonic() - before
            for key, status in zip(chunk, outcomes, strict=True):
                results[key] = status
                if status in ("equal", "not_equal", "invalid_input"):
                    self.worksheet_cache[key] = status
            if all(value == "unavailable" for value in outcomes):
                results.update(dict.fromkeys(pending[start + len(chunk):], "unavailable"))
                break

        questions = list(report.questions)
        for index, key in keys.items():
            img_ref, location, expression, submitted = key
            status = results.get(key) or self.worksheet_cache[key]
            verdict = {"equal": "correct", "not_equal": "incorrect"}.get(status, "uncertain")
            question = questions[index].model_copy(update={
                "verdict": verdict,
                "basis": "仅核验原式与所转写的作答值" if verdict != "uncertain" else f"未完成复算（{status}）",
            })
            question._calculation_status = status
            questions[index] = question
            self._record_worksheet_item(
                image_ref=img_ref,
                location=location,
                expression=expression,
                submitted=submitted,
                status=status,
            )
        coverage = report.coverage
        if not report.complete_coverage(self.image_refs) or any(q.verdict == "uncertain" for q in questions):
            coverage = "partial"
        conclusion = (
            "some_incorrect"
            if any(q.verdict == "incorrect" for q in questions)
            else "all_correct"
            if questions
            and coverage == "complete"
            and all(q.verdict == "correct" for q in questions)
            else "uncertain"
        )
        return candidate.model_copy(
            update={
                "image_review": report.model_copy(
                    update={"questions": questions, "conclusion": conclusion, "coverage": coverage}
                ),
            }
        )

    def _record_worksheet_item(
        self,
        *,
        image_ref: str,
        location: str,
        expression: str,
        submitted: str,
        status: str,
    ) -> None:
        """Unify batch worksheet arithmetic checks into the same math_records ledger."""
        digest = hashlib.sha256(
            json.dumps(
                {
                    "source": self.source,
                    "image_ref": image_ref,
                    "location": location,
                    "expression": expression,
                    "submitted": submitted,
                },
                sort_keys=True,
                ensure_ascii=False,
            ).encode()
        ).hexdigest()
        request_id = f"ws_{digest[:12]}"
        # Replace any stale worksheet record for the same (image_ref, location).
        for existing_id in [
            rid
            for rid, rec in self.records.items()
            if rec.get("op") == "check_arithmetic"
            and rec.get("image_ref") == image_ref
            and rec.get("location") == location
            and rid != request_id
        ]:
            self.records.pop(existing_id, None)
            self.evidence.pop(existing_id, None)
        is_verified = status in ("equal", "not_equal")
        self.records[request_id] = {
            "request_id": request_id,
            "op": "check_arithmetic",
            "image_ref": image_ref,
            "location": location,
            "expression": expression,
            "submitted": submitted,
            "status": "ok" if is_verified else "unknown",
            **({"verdict": status} if is_verified else {"error_code": status}),
        }
        self.evidence[request_id] = MathEvidence(
            request_id=request_id,
            input_digest=digest,
            status="ok" if is_verified else "unknown",
            verdict=status if is_verified else None,
            checked_scope="equivalence" if is_verified else None,
            conditions=(),
            step_ref=location,
            result=None,
        )
