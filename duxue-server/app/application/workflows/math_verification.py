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

    def reconcile_image(self, candidate):
        """Arithmetic transcriptions use the same isolated engine and evidence ledger."""
        report = candidate.image_review
        if report is None or report.conclusion == "not_checking":
            return candidate
        questions, claims = [], list(candidate.math_claims)
        for question in report.questions:
            if question.calculation is not None and question.verdict != "uncertain":
                record = self.run(
                    {
                        "op": "equivalent",
                        "args": {
                            "left": question.calculation.expression,
                            "right": question.calculation.submitted,
                        },
                        "image_ref": question.image_ref,
                        "step_ref": question.location,
                    }
                )
                assertion = record.get("verdict")
                verdict = (
                    "correct"
                    if assertion == "equal"
                    else "incorrect"
                    if assertion == "not_equal"
                    else "uncertain"
                )
                question = question.model_copy(
                    update={
                        "verdict": verdict,
                        "basis": "仅核验转写原式与作答值；未证明转写、列式或中间步骤正确",
                    }
                )
                if "request_id" in record:
                    claim = MathClaim(
                        request_id=record["request_id"],
                        step_ref=question.location,
                        assertion=assertion if verdict != "uncertain" else "unknown",
                    )
                    if claim not in claims:
                        claims.append(claim)
            questions.append(question)
        conclusion = (
            "some_incorrect"
            if any(q.verdict == "incorrect" for q in questions)
            else "all_correct"
            if questions
            and report.coverage == "complete"
            and all(q.verdict == "correct" for q in questions)
            else "uncertain"
        )
        return candidate.model_copy(
            update={
                "math_claims": claims,
                "image_review": report.model_copy(
                    update={"questions": questions, "conclusion": conclusion}
                ),
            }
        )
