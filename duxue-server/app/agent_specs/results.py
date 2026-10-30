"""Agent execution envelope, independent of provider and domain protocols."""
from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path
from typing import Literal

from jsonschema import Draft202012Validator
from pydantic import BaseModel, ConfigDict, model_validator

ErrorCode = Literal[
    "invalid_model_candidate", "model_transport_error", "model_provider_disabled",
    "model_provider_not_configured", "agent_execution_failed",
]
ERROR_CODES = {
    "invalid_model_candidate", "model_transport_error", "model_provider_disabled",
    "model_provider_not_configured", "agent_execution_failed",
}


class AgentResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    status: Literal["ok", "needs_input", "failed"]
    data: dict | None = None
    error_code: ErrorCode | None = None

    @model_validator(mode="after")
    def coherent_result(self):
        if self.status == "failed":
            if self.error_code is None or self.data is not None:
                raise ValueError("failed Agent results require an error code and forbid candidate data")
        elif self.data is None or self.error_code is not None:
            raise ValueError("successful Agent results require data and forbid an error code")
        return self

    def unwrap(self) -> dict:
        if self.status == "failed":
            from app.infrastructure.ai.errors import ModelGatewayError
            raise ModelGatewayError(self.error_code)
        assert self.data is not None
        return self.data


@lru_cache(maxsize=1)
def result_validator():
    path = Path(__file__).resolve().parents[2] / "agent_specs/schemas/agent-result.json"
    schema = json.loads(path.read_text(encoding="utf-8"))
    Draft202012Validator.check_schema(schema)
    return Draft202012Validator(schema)


def validate_result(result: AgentResult) -> AgentResult:
    payload = result.model_dump(mode="json")
    result_validator().validate(payload)
    return AgentResult.model_validate(payload)


def completed(data: dict, *, needs_input: bool = False) -> AgentResult:
    return validate_result(AgentResult(status="needs_input" if needs_input else "ok", data=data))
