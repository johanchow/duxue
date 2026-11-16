"""Evaluation-only stateless solution adapter; never a Ward workflow or policy change."""

import hashlib
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

PROMPT = Path(__file__).with_name("solve-prompt.txt").read_text()


class Solution(BaseModel):
    model_config = ConfigDict(extra="forbid")
    solution: str = Field(min_length=1, max_length=30000)


def identity(spec):
    return {
        "execution_target": "solve",
        "model_from": "snapshot:tutoring.turn",
        "model": spec.model,
        "temperature": spec.temperature,
        "max_output_tokens": spec.max_tokens,
        "enable_thinking": bool(getattr(spec, "enable_thinking", False)),
        "thinking_budget": getattr(spec, "thinking_budget", None),
        "prompt_id": "evals.local.solve.v1",
        "prompt_sha256": hashlib.sha256(PROMPT.encode()).hexdigest(),
    }


def complete(case, spec, images):
    if images and not spec.accepts_images:
        raise ValueError("solution model cannot receive required images")
    from app.infrastructure.ai.components import (
        _CompletionClassifiedError,
        _record_call_evidence,
        complete_json_chat,
        validate_json_completion,
    )

    # This adapter is deliberately not a production TutorTurnLoop invocation.
    # The model/parameters stay pinned; the explicit evaluation prompt has its own digest.
    user = [{"type": "text", "text": case.student_said}]
    user.extend({"type": "image_url", "image_url": {"url": u}} for u in images)
    telemetry: dict[str, Any] = {}
    try:
        completion = complete_json_chat(
            timeout=spec.timeout_seconds or 60,
            model=spec.model,
            temperature=spec.temperature,
            max_tokens=spec.max_tokens,
            messages=[
                {"role": "system", "content": PROMPT},
                {"role": "user", "content": user},
            ],
            enable_thinking=bool(getattr(spec, "enable_thinking", False)),
            thinking_budget=getattr(spec, "thinking_budget", None),
            telemetry=telemetry,
        )
        validated: dict[str, str] = {}

        def _check(data: dict[str, Any]) -> None:
            validated["solution"] = Solution.model_validate(data).solution

        _, outcome, abrupt_detail = validate_json_completion(
            completion,
            unit_id="evals.local.solve",
            validate_payload=_check,
        )
        _record_call_evidence(
            {
                "component_id": "evals.local.solve",
                "operation": "eval_solve",
                "model": spec.model,
                "provider_request_id": completion.provider_request_id,
                "finish_reason": completion.finish_reason,
                "stream_completed": completion.stream_completed,
                "tokens_in": completion.tokens_in,
                "tokens_out": completion.tokens_out,
                "tokens_answer": completion.tokens_answer,
                "tokens_reasoning": completion.tokens_reasoning,
                "outcome": outcome,
                "abrupt_detail": abrupt_detail,
            }
        )
        return validated["solution"]
    except _CompletionClassifiedError as error:
        _record_call_evidence(
            {
                "component_id": "evals.local.solve",
                "operation": "eval_solve",
                "model": spec.model,
                "provider_request_id": telemetry.get("provider_request_id"),
                "finish_reason": telemetry.get("finish_reason"),
                "stream_completed": bool(telemetry.get("stream_completed")),
                "tokens_in": telemetry.get("tokens_in"),
                "tokens_out": telemetry.get("tokens_out"),
                "tokens_answer": telemetry.get("tokens_answer"),
                "tokens_reasoning": telemetry.get("tokens_reasoning"),
                "outcome": error.outcome,
                "abrupt_detail": None,
            }
        )
        raise ValueError(f"solution_{error.outcome}") from error
    except Exception as error:
        _record_call_evidence(
            {
                "component_id": "evals.local.solve",
                "operation": "eval_solve",
                "model": spec.model,
                "provider_request_id": telemetry.get("provider_request_id"),
                "finish_reason": telemetry.get("finish_reason"),
                "stream_completed": bool(telemetry.get("stream_completed")),
                "tokens_in": telemetry.get("tokens_in"),
                "tokens_out": telemetry.get("tokens_out"),
                "tokens_answer": telemetry.get("tokens_answer"),
                "tokens_reasoning": telemetry.get("tokens_reasoning"),
                "outcome": "api_error",
                "abrupt_detail": None,
                "error_type": type(error).__name__,
            }
        )
        raise
